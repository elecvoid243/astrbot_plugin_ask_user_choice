"""InteractiveChoiceRegistry: in-memory 等待池,管理 ask_user_choice 工具的 Future。

单例(global `registry`),工具内 await Future,REST 端点 set_result。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PendingChoice:
    """单个等待中的 interactive_choice 状态。"""

    request_id: str
    umo: str
    sse_message_id: str
    """触发本次 tool 调用的 webchat event 的 message_id,用于推送 SSE 通知。"""
    future: asyncio.Future
    spec: dict
    created_at: float
    timeout_at: float
    cleanup_done: bool = False


class InteractiveChoiceRegistry:
    """In-memory pending 池,O(1) 查询 + per-umo 索引。

    Attributes:
        _pending: request_id → PendingChoice
        _by_umo: umo → set[request_id]
    """

    def __init__(self) -> None:
        self._pending: dict[str, PendingChoice] = {}
        self._by_umo: dict[str, set[str]] = {}

    def add(
        self,
        request_id: str,
        umo: str,
        future: asyncio.Future,
        spec: dict,
        created_at: float,
        timeout_at: float,
        sse_message_id: str = "",
    ) -> None:
        """注册一个等待中的 choice(同步,工具内 await 前调用)。

        Args:
            request_id: 唯一请求 ID。
            umo: unified_msg_origin。
            future: 阻塞 Future。
            spec: choice spec dict。
            created_at: 创建时间戳。
            timeout_at: 超时时间戳。
            sse_message_id: 触发本次 tool 调用的 webchat event 的 message_id,
                用于推送 SSE 通知。默认为空(不足以支持 SSE 推送)。
        """
        self._pending[request_id] = PendingChoice(
            request_id=request_id,
            umo=umo,
            sse_message_id=sse_message_id,
            future=future,
            spec=spec,
            created_at=created_at,
            timeout_at=timeout_at,
        )
        self._by_umo.setdefault(umo, set()).add(request_id)

    def remove(self, request_id: str) -> None:
        """从池中移除一个 choice。cancel 未完成的 future。"""
        pending = self._pending.pop(request_id, None)
        if pending is None:
            return
        ids = self._by_umo.get(pending.umo)
        if ids is not None:
            ids.discard(request_id)
            if not ids:
                self._by_umo.pop(pending.umo, None)
        if not pending.future.done():
            pending.future.cancel()

    def list_pending_for_umo(self, umo: str) -> list[dict]:
        """列出某 umo 下所有仍 pending 的 choice。

        Args:
            umo: 统一消息来源,如 'webchat:FriendMessage:webchat!alice!sess'。

        Returns:
            [{request_id, spec, created_at, timeout_at}, ...]
            排除已 resolve/已超时/已移除的条目。
        """
        ids = self._by_umo.get(umo, set())
        now = time.time()
        result = []
        for rid in list(ids):
            p = self._pending.get(rid)
            if p is None or p.future.done() or p.timeout_at < now:
                continue
            result.append(
                {
                    "request_id": p.request_id,
                    "spec": p.spec,
                    "created_at": p.created_at,
                    "timeout_at": p.timeout_at,
                }
            )
        return result

    def find_pending_by_umo(self, umo: str) -> PendingChoice | None:
        """返回给定 UMO 下最新的 pending choice,若没有则返回 None。

        用于 :meth:`on_message` 消费消息时快速查找。返回最近创建的
        (created_at 最大) 仍在 pending 的 choice。
        """
        ids = self._by_umo.get(umo, set())
        now = time.time()
        best: PendingChoice | None = None
        for rid in ids:
            p = self._pending.get(rid)
            if p is None or p.future.done() or p.timeout_at < now:
                continue
            if best is None or p.created_at > best.created_at:
                best = p
        return best

    def resolve(self, request_id: str, payload: dict) -> bool:
        """Set future result。已 resolve 或不存在返回 False。

        Args:
            request_id: 由 add() 注册的 ID。
            payload: 用户响应,通常是 {choice_id, free_text}。

        Returns:
            True if successful, False if unknown/already-done.
        """
        pending = self._pending.get(request_id)
        if pending is None:
            return False
        if pending.future.done():
            return False
        pending.future.set_result(payload)
        return True

    def stats(self) -> dict:
        """当前状态(用于调试/metrics)。"""
        return {
            "total_pending": len(self._pending),
            "by_umo": {umo: len(ids) for umo, ids in self._by_umo.items()},
        }

    def _ensure_gc(self) -> None:
        """确保 GC task 在运行(单例一次)。"""
        # TODO(PR 2): Start _gc_loop as a background task here, store as self._gc_task.
        # When filled in, update InteractiveChoiceRegistry.shutdown() to also
        # cancel self._gc_task (currently only iterates _pending).
        pass

    async def _gc_loop(self) -> None:
        """每 30s 扫描一次,清理已超时 / 已 done 的条目。"""
        while True:
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                return
            now = time.time()
            expired = [
                rid
                for rid, p in self._pending.items()
                if p.timeout_at < now or p.future.done()
            ]
            for rid in expired:
                self.remove(rid)
            if expired:
                logger.debug(f"[interactive_choice_gc] cleaned {len(expired)} expired")

    async def shutdown(self) -> None:
        """优雅关闭:cancel 所有 future + GC task。"""
        for pending in list(self._pending.values()):
            if not pending.future.done():
                pending.future.cancel()
        self._pending.clear()
        self._by_umo.clear()
        # GC task 由 __init__ 阶段延迟启动,本测试不触发


# 全局单例
registry = InteractiveChoiceRegistry()

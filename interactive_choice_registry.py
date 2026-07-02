"""InteractiveChoiceRegistry: in-memory 等待池,管理 ask_user_choice 工具的 Future。

单例(global `registry`),工具内 await Future,REST 端点 set_result。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PendingChoice:
    """单个等待中的 interactive_choice 状态。"""

    request_id: str
    umo: str
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
    ) -> None:
        """注册一个等待中的 choice(同步,工具内 await 前调用)。"""
        self._pending[request_id] = PendingChoice(
            request_id=request_id,
            umo=umo,
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


# 全局单例
registry = InteractiveChoiceRegistry()

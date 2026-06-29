"""ask_user_choice 工具的挂起状态管理。

Author: elecvoid243
Date: 2026-06-29
Spec: docs/superpowers/specs/2026-06-29-ask-user-choice-suspension-design.md §4.1 / §4.3
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass
class PendingRequest:
    """一次 ask_user_choice 调用的挂起态。"""

    key: tuple[str, str]
    """(unified_msg_origin, sender_id)"""

    future: asyncio.Future[str]
    """等待用户回执(文本)"""

    pending_id: str = field(default_factory=lambda: uuid4().hex[:12])
    """自生成短 id,用于跨 tool.call 与 on_message 的日志关联"""

    prompt: str = ""
    """选项框的 prompt(用于日志/调试)"""

    created_at: float = field(default_factory=time.monotonic)

    timeout_seconds: int = 300


class PendingRegistry:
    """ask_user_choice 工具的挂起态注册表。"""

    def __init__(self) -> None:
        self._pending: dict[tuple[str, str], PendingRequest] = {}

    def has_pending(self, key: tuple[str, str]) -> bool:
        return key in self._pending

    def register(self, req: PendingRequest) -> None:
        """tool.call() 调用。已存在同 key 时由调用方处理拒绝逻辑。

        并发安全:asyncio 单线程,dict __setitem__ 原子;
        调用方必须保证 "has_pending + register" 块内**没有 await**。
        """
        self._pending[req.key] = req

    def try_resolve(self, key: tuple[str, str], text: str) -> bool:
        """on_message 钩子调用。

        Returns:
            True  = 成功 resolve(消息应被消费)
            False = 无挂起或已 resolved(放行原消息)
        """
        req = self._pending.pop(key, None)
        if req is None or req.future.done():
            return False
        req.future.set_result(text)
        return True

    def cancel(self, key: tuple[str, str], reason: str = "cancelled") -> bool:
        req = self._pending.pop(key, None)
        if req is None or req.future.done():
            return False
        req.future.set_exception(asyncio.CancelledError(reason))
        return True

    def cleanup_all(self) -> None:
        for key in list(self._pending.keys()):
            self.cancel(key, reason="plugin_terminated")

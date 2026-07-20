"""REST 端点挂载辅助模块:幂等挂载 + Lazy Init 兼容。"""

from __future__ import annotations

from astrbot.api import logger

from .interactive_choice_api import router as api_router

_MOUNTED = False
""":meta private: True if the router has been successfully added to the dashboard app."""
_WARNED_ERROR = False
""":meta private: True if a non-transient log warning has already been emitted."""


def _mount_api_router() -> bool:
    """Mount the interactive-choice API router to the dashboard FastAPI app.

    Idempotent — subsequent calls after a successful mount are no-ops.
    Safe to call before the dashboard is fully initialized; returns
    ``False`` when ``APP`` is still ``None`` (no error logged).

    Returns:
        ``True`` if the router is mounted (or was already mounted),
        ``False`` if the dashboard app is not yet available.
    """
    global _MOUNTED, _WARNED_ERROR  # noqa: PLW0603
    if _MOUNTED:
        return True
    try:
        from astrbot.dashboard.server import APP

        if APP is None:
            logger.debug("ask_user_choice: dashboard APP 尚未初始化,REST 端点暂未挂载")
            return False
        underlying = getattr(APP, "_app", None)
        if underlying is None:
            if not _WARNED_ERROR:
                logger.warning(
                    "ask_user_choice: dashboard APP 缺少 _app 属性,REST 端点未挂载"
                )
                _WARNED_ERROR = True
            return False
        underlying.include_router(api_router)
    except Exception as exc:
        if not _WARNED_ERROR:
            logger.warning(f"ask_user_choice: REST 端点挂载失败 ({exc})")
            _WARNED_ERROR = True
        return False
    else:
        _MOUNTED = True
        logger.info("ask_user_choice: REST 端点已挂载到 dashboard app")
        return True


def _get_mount_state() -> dict:  # pragma: no cover (test helper)
    """Return mount state for test assertions.  Not part of public API."""
    return {"mounted": _MOUNTED, "warned": _WARNED_ERROR}


def _reset_mount_state() -> None:  # pragma: no cover (test helper)
    """Reset mount state.  Used by tests only."""
    global _MOUNTED, _WARNED_ERROR  # noqa: PLW0603
    _MOUNTED = False
    _WARNED_ERROR = False


def _extract_conversation_id(umo: str) -> str | None:
    """从 webchat UMO 中提取 conversation_id (session_key 的最后一段)。

    Example:
        ``"webchat:FriendMessage:webchat!alice!sess-abc"`` → ``"sess-abc"``
        ``"lark:..."`` → ``None``
    """
    parts = umo.split(":", 2)
    if len(parts) < 3:
        return None
    session_key = parts[2]
    chunks = session_key.split("!")
    if len(chunks) < 3:
        return None
    return chunks[-1]


async def _push_resolved_event_to_back_queue(
    request_id: str,
    umo: str,
    reason: str,
    sse_message_id: str,
) -> None:
    """推 interactive_choice_resolved 事件到 webchat SSE back_queue。

    用于 :func:`ask_user_choice_tool.AskUserChoiceTool.call` 和
    :meth:`main.AskUserChoicePlugin.on_message` 共享。

    Args:
        request_id: 本次交互请求的唯一 ID。
        umo: unified_msg_origin。
        reason: 解决原因 (如 submitted / cancelled)。
        sse_message_id: webchat event 的 message_id,作为 back_queue key。
    """
    from astrbot.core.platform.sources.webchat.webchat_queue_mgr import (  # noqa: PLC0415
        webchat_queue_mgr,
    )

    conversation_id = _extract_conversation_id(umo)
    if not conversation_id:
        return
    back_queue = webchat_queue_mgr.get_or_create_back_queue(
        request_id=sse_message_id,
        conversation_id=conversation_id,
    )
    await back_queue.put(
        {
            "type": "interactive_choice_resolved",
            "data": {
                "request_id": request_id,
                "reason": reason,
                "umo": umo,
            },
            "message_id": sse_message_id,
        }
    )

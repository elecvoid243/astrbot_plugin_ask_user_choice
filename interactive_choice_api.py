"""REST 端点:interactive-choice 提交、取消与 pending 列表。

挂在 dashboard app:POST   /api/chat/interactive-choice/<request_id>
                  DELETE /api/chat/interactive-choice/<request_id>
                  POST   /api/chat/interactive-choice/pending
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request

from astrbot.api import logger
from astrbot.dashboard.api.auth import require_dashboard_user
from astrbot.dashboard.responses import ApiError, ok

from .interactive_choice_registry import registry

router = APIRouter()


def _extract_username_from_umo(umo: str) -> str:
    """从 webchat umo 提取 dashboard username。

    预期格式: 'webchat:FriendMessage:webchat!alice!session_id'
    返回 'alice';失败(非 webchat / 格式错)返回 ''。
    """
    if not umo.startswith("webchat:"):
        return ""
    parts = umo.split(":", 2)
    if len(parts) < 3:
        return ""
    session_key = parts[2]
    chunks = session_key.split("!")
    if len(chunks) >= 3 and chunks[0] == "webchat":
        return chunks[1]
    return ""


# 路由注册顺序即匹配顺序(Starlette 按添加顺序逐一匹配,首个命中胜出)。
# 静态路径 /pending 必须先于 /{request_id} 注册,否则 "pending" 会被
# 路径参数吞掉,POST /pending 永远落入 submit 端点返回 404。
@router.post("/api/chat/interactive-choice/pending")
async def get_pending_choices(
    session_id: str | None = None,
    payload: dict | None = None,
    username: str = Depends(require_dashboard_user),
):
    """Return all pending choices for a given webchat UMO.

    Used by the frontend on mount/reconnect to reconcile any choices the
    user has not yet answered. Read-only; never mutates registry state.

    Args:
        session_id: Full UMO (query param) — ``None`` allowed so the
            endpoint can also accept it in the JSON body.
        payload: POST body, optional. Used as a fallback source for
            ``session_id`` when the query param is absent.
        username: Injected by ``require_dashboard_user``.

    Returns:
        200: ``{status: "ok", data: {pending: [...]}}``
        400: Missing ``session_id`` or session_id is not a webchat UMO.
        403: ``session_id`` belongs to a different dashboard user.
    """
    if (not session_id or not session_id.strip()) and payload:
        sid = payload.get("session_id")
        if isinstance(sid, str) and sid.strip():
            session_id = sid
    if not session_id or not session_id.strip():
        raise ApiError("Missing session_id (query or body)", status_code=400)

    expected = _extract_username_from_umo(session_id)
    if not expected:
        raise ApiError("session_id must be a webchat UMO", status_code=400)
    if expected != username:
        raise ApiError("Not authorized for this session", status_code=403)

    pending_list = registry.list_pending_for_umo(session_id)
    parts = []
    for item in pending_list:
        spec = item["spec"].copy()
        spec["request_id"] = item["request_id"]
        spec["expires_at"] = item["timeout_at"]
        parts.append(spec)
    return ok({"pending": parts})


@router.post("/api/chat/interactive-choice/{request_id}")
async def submit_interactive_choice(
    request_id: str,
    request: Request,
    username: str = Depends(require_dashboard_user),
):
    """用户提交选择,resolve 对应 future。

    Returns:
        200: {status: "ok", data: {request_id, resolved_at}}
        400: body 缺 choice_id
        403: pending 属于其他用户
        404: request_id 不存在或已超时
        409: 已被 resolve(防双调用)
    """
    pending = registry._pending.get(request_id)
    if pending is None:
        raise ApiError("Interactive choice not found or expired", status_code=404)

    # 鉴权层 2:UMO 归属
    expected = _extract_username_from_umo(pending.umo)
    if not expected or expected != username:
        raise ApiError("Not authorized to resolve this choice", status_code=403)

    # 解析 body
    try:
        body = await request.json()
    except Exception:
        raise ApiError("Invalid JSON body", status_code=400)
    if not isinstance(body, dict):
        raise ApiError("Body must be a JSON object", status_code=400)

    choice_id = body.get("choice_id")
    if not isinstance(choice_id, str) or not choice_id.strip():
        raise ApiError("Missing key: choice_id", status_code=400)
    free_text = body.get("free_text") or ""
    if not isinstance(free_text, str):
        free_text = ""

    payload = {"choice_id": choice_id.strip(), "free_text": free_text.strip()}
    if not registry.resolve(request_id, payload):
        raise ApiError("Already resolved or expired", status_code=409)

    return ok({"request_id": request_id, "resolved_at": time.time()})


@router.delete("/api/chat/interactive-choice/{request_id}")
async def cancel_interactive_choice(
    request_id: str,
    username: str = Depends(require_dashboard_user),
):
    """用户点击候选框右上角「取消」按钮,取消对应 future。

    前端 store.cancelChoice() 已乐观地把 UI 切到「已取消」并发出本
    DELETE 请求;本端点负责真正解除 ask_user_choice 工具的阻塞:
    registry.remove() 会 cancel 未完成的 asyncio.Future,工具侧
    `except asyncio.CancelledError` 分支返回
    "[User input was cancelled] ..." 给 LLM。

    Returns:
        200: {status: "ok", data: {request_id, cancelled_at}}
        403: pending 属于其他用户(不取消,保护他人会话)
        404: request_id 不存在/已 resolve/已超时(幂等,前端忽略错误)
    """
    pending = registry._pending.get(request_id)
    if pending is None:
        raise ApiError("Interactive choice not found or expired", status_code=404)

    # 鉴权层 2:UMO 归属(与 submit 端点同规则)
    expected = _extract_username_from_umo(pending.umo)
    if not expected or expected != username:
        raise ApiError("Not authorized to cancel this choice", status_code=403)

    # 先取出广播所需字段,再 remove(remove 后 entry 即消失)。
    # remove() 内部对未完成 future 调 cancel(),触发工具侧
    # CancelledError 分支;工具 finally 里的二次 remove 是幂等 no-op。
    umo = pending.umo
    sse_message_id = pending.sse_message_id
    registry.remove(request_id)

    # 跨标签页一致性:广播 interactive_choice_resolved{cancelled},
    # 其他打开同一会话的标签页收到 SSE 后同步切到「已取消」。
    # best-effort:广播失败不影响取消主流程(前端 reconcile 兜底)。
    # 延迟 import:api_mount 在模块顶层 import 本模块的 router,
    # 顶层反向 import 会造成循环导入。
    from .api_mount import _push_resolved_event_to_back_queue  # noqa: PLC0415

    try:
        await _push_resolved_event_to_back_queue(
            request_id=request_id,
            umo=umo,
            reason="cancelled",
            sse_message_id=sse_message_id,
        )
    except Exception as exc:
        logger.warning(f"ask_user_choice: cancel 事件广播失败 ({exc})")

    return ok({"request_id": request_id, "cancelled_at": time.time()})

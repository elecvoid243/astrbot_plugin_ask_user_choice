"""REST 端点:interactive-choice 提交与 pending 列表。

挂在 dashboard app:POST /api/chat/interactive-choice/<request_id>
                  GET  /api/chat/interactive-choice/pending
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request

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


@router.get("/api/chat/interactive-choice/pending")
async def get_pending_choices(
    session_id: str | None = None,
    username: str = Depends(require_dashboard_user),
):
    """Return all pending choices for a given webchat UMO.

    Used by the frontend on mount/reconnect to reconcile any choices the
    user has not yet answered. Read-only; never mutates registry state.

    Args:
        session_id: Full UMO, e.g.
            ``webchat:FriendMessage:webchat!alice!sess``.
        username: Injected by ``require_dashboard_user``.

    Returns:
        200: ``{status: "ok", data: {pending: [...]}}``
        400: Missing ``session_id`` or session_id is not a webchat UMO.
        403: ``session_id`` belongs to a different dashboard user.
    """
    if not session_id or not session_id.strip():
        raise ApiError("Missing query param: session_id", status_code=400)

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

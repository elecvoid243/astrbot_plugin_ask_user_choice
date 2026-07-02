"""REST 端点:interactive-choice 提交与 pending 列表。

挂在 dashboard app:POST /api/chat/interactive-choice/<request_id>
                  GET  /api/chat/interactive-choice/pending
"""
from __future__ import annotations

from .interactive_choice_registry import registry


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


# 端点实现见 Task 9, Task 10

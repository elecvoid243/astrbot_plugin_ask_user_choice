## Task 8: REST - _extract_username_from_umo

**Files:**
- Create: `astrbot_plugin_ask_user_choice/interactive_choice_api.py`
- Create: `astrbot_plugin_ask_user_choice/tests/test_interactive_choice_api.py`

**Interfaces:**
- Produces: `function _extract_username_from_umo(umo) -> str`

- [ ] **Step 1: Add failing test**

`astrbot_plugin_ask_user_choice/tests/test_interactive_choice_api.py`:

```python
"""REST 端点单元测试。"""
from astrbot_plugin_ask_user_choice.interactive_choice_api import (
    _extract_username_from_umo,
)


def test_extract_username_from_webchat_umo():
    umo = "webchat:FriendMessage:webchat!alice!sess-123"
    assert _extract_username_from_umo(umo) == "alice"


def test_extract_username_returns_empty_for_non_webchat():
    umo = "lark:FriendMessage:lark!alice!sess-123"
    assert _extract_username_from_umo(umo) == ""


def test_extract_username_returns_empty_for_malformed():
    assert _extract_username_from_umo("invalid") == ""
    assert _extract_username_from_umo("webchat:FriendMessage") == ""  # 缺 session_key
    assert _extract_username_from_umo("webchat:FriendMessage:bad") == ""  # 缺 !
    assert _extract_username_from_umo("webchat:FriendMessage:foo!bar") == ""  # 缺 platform 头


def test_extract_username_handles_dots_and_dashes():
    umo = "webchat:FriendMessage:webchat!alice.smith_2!sess-2025-07-02"
    assert _extract_username_from_umo(umo) == "alice.smith_2"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd astrbot_plugin_ask_user_choice && python -m pytest tests/test_interactive_choice_api.py -v
```

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation (只有辅助函数)**

`astrbot_plugin_ask_user_choice/interactive_choice_api.py`:

```python
"""REST 端点:interactive-choice 提交与 pending 列表。

挂在 dashboard app:POST /api/chat/interactive-choice/<request_id>
                  GET  /api/chat/interactive-choice/pending
"""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, Request

from astrbot.dashboard.api.auth import require_dashboard_user
from astrbot.dashboard.responses import ApiError, ok

from .interactive_choice_registry import registry

logger = logging.getLogger(__name__)

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


# 端点实现见 Task 9, Task 10
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd astrbot_plugin_ask_user_choice && python -m pytest tests/test_interactive_choice_api.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
cd astrbot_plugin_ask_user_choice
git add interactive_choice_api.py tests/test_interactive_choice_api.py
git commit -m "feat(api): add _extract_username_from_umo helper"
```

---

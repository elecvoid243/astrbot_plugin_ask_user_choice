## Task 9: REST - POST 端点

**Files:**
- Modify: `astrbot_plugin_ask_user_choice/interactive_choice_api.py`
- Modify: `astrbot_plugin_ask_user_choice/tests/test_interactive_choice_api.py`

**Interfaces:**
- Produces: `POST /api/chat/interactive-choice/<request_id>` with auth `Depends(require_dashboard_user)`

- [ ] **Step 1: Add failing tests for POST endpoint**

Append to `tests/test_interactive_choice_api.py`:

```python
import asyncio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from astrbot_plugin_ask_user_choice.interactive_choice_api import router
from astrbot_plugin_ask_user_choice.interactive_choice_registry import registry


@pytest.fixture
def app(monkeypatch):
    """构造测试用 FastAPI app,绕过真实 dashboard auth。"""
    test_app = FastAPI()
    test_app.include_router(router)
    # 替换 require_dashboard_user 为一个固定 username 返回
    from astrbot.dashboard.api.auth import require_dashboard_user
    def fake_auth():
        return "alice"
    test_app.dependency_overrides[require_dashboard_user] = lambda: "alice"
    return test_app


@pytest.fixture
def client(app):
    return TestClient(app)


def test_post_404_when_not_found(client):
    r = client.post(
        "/api/chat/interactive-choice/nonexistent",
        json={"choice_id": "A"},
    )
    assert r.status_code == 404


def test_post_400_when_missing_choice_id(client):
    # 先注册一个 pending
    fut = asyncio.get_event_loop().create_future()
    registry.add(
        "rid-1", "webchat:FriendMessage:webchat!alice!sess", fut,
        {"prompt": "x", "options": [{"id": "A", "label": "a"}]},
        0.0, time.time() + 60,
    )
    try:
        r = client.post("/api/chat/interactive-choice/rid-1", json={})
        assert r.status_code == 400
    finally:
        registry.remove("rid-1")


def test_post_403_when_other_user(client, monkeypatch):
    # 重新构造 client,bob 登录
    from astrbot.dashboard.api.auth import require_dashboard_user
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_dashboard_user] = lambda: "bob"
    c = TestClient(app)
    # pending 属于 alice
    fut = asyncio.get_event_loop().create_future()
    registry.add(
        "rid-1", "webchat:FriendMessage:webchat!alice!sess", fut,
        {"prompt": "x", "options": [{"id": "A", "label": "a"}]},
        0.0, time.time() + 60,
    )
    try:
        r = c.post("/api/chat/interactive-choice/rid-1", json={"choice_id": "A"})
        assert r.status_code == 403
    finally:
        registry.remove("rid-1")


def test_post_success_resolves_future(client):
    fut = asyncio.get_event_loop().create_future()
    registry.add(
        "rid-1", "webchat:FriendMessage:webchat!alice!sess", fut,
        {"prompt": "x", "options": [{"id": "A", "label": "alpha"}]},
        0.0, time.time() + 60,
    )
    try:
        r = client.post(
            "/api/chat/interactive-choice/rid-1",
            json={"choice_id": "A", "free_text": "我选 A"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        # future 已被 resolve
        assert fut.done()
        result = fut.result()
        assert result["choice_id"] == "A"
        assert result["free_text"] == "我选 A"
    finally:
        registry.remove("rid-1")


def test_post_double_call_returns_409(client):
    fut = asyncio.get_event_loop().create_future()
    registry.add(
        "rid-1", "webchat:FriendMessage:webchat!alice!sess", fut,
        {"prompt": "x", "options": [{"id": "A", "label": "alpha"}]},
        0.0, time.time() + 60,
    )
    try:
        client.post("/api/chat/interactive-choice/rid-1", json={"choice_id": "A"})
        # 第二次
        r = client.post("/api/chat/interactive-choice/rid-1", json={"choice_id": "B"})
        assert r.status_code == 409
    finally:
        registry.remove("rid-1")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd astrbot_plugin_ask_user_choice && python -m pytest tests/test_interactive_choice_api.py -v
```

Expected: FAIL(no POST endpoint)

- [ ] **Step 3: Implement POST endpoint**

Append to `interactive_choice_api.py`:

```python
@router.post("/api/chat/interactive-choice/<request_id>")
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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd astrbot_plugin_ask_user_choice && python -m pytest tests/test_interactive_choice_api.py -v
```

Expected: 9 passed (4 helper + 5 POST)

- [ ] **Step 5: Commit**

```bash
cd astrbot_plugin_ask_user_choice
git add interactive_choice_api.py tests/test_interactive_choice_api.py
git commit -m "feat(api): add POST /api/chat/interactive-choice/<request_id>"
```

---

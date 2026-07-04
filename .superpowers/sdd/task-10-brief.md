## Task 10: REST - GET pending 端点

**Files:**
- Modify: `astrbot_plugin_ask_user_choice/interactive_choice_api.py`
- Modify: `astrbot_plugin_ask_user_choice/tests/test_interactive_choice_api.py`

**Interfaces:**
- Produces: `GET /api/chat/interactive-choice/pending?session_id=<umo>`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_interactive_choice_api.py`:

```python
def test_get_pending_400_when_missing_session_id(client):
    r = client.get("/api/chat/interactive-choice/pending")
    assert r.status_code == 400


def test_get_pending_403_when_other_user():
    from astrbot.dashboard.api.auth import require_dashboard_user
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_dashboard_user] = lambda: "bob"
    c = TestClient(app)
    r = c.get("/api/chat/interactive-choice/pending?session_id=webchat:FriendMessage:webchat!alice!sess")
    assert r.status_code == 403


def test_get_pending_400_for_non_webchat_session(client):
    r = client.get("/api/chat/interactive-choice/pending?session_id=lark:...!alice!sess")
    assert r.status_code == 400


def test_get_pending_returns_alice_pending(client):
    # 注册 alice 的 pending
    fut1 = asyncio.get_event_loop().create_future()
    fut2 = asyncio.get_event_loop().create_future()
    registry.add(
        "rid-1", "webchat:FriendMessage:webchat!alice!sess",
        fut1, {"prompt": "p1", "options": [{"id": "A", "label": "a"}]},
        0.0, time.time() + 60,
    )
    registry.add(
        "rid-2", "webchat:FriendMessage:webchat!bob!sess",
        fut2, {"prompt": "p2", "options": [{"id": "B", "label": "b"}]},
        0.0, time.time() + 60,
    )
    try:
        r = client.get(
            "/api/chat/interactive-choice/pending?session_id=webchat:FriendMessage:webchat!alice!sess",
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        pending = body["data"]["pending"]
        assert len(pending) == 1
        assert pending[0]["request_id"] == "rid-1"
        assert pending[0]["prompt"] == "p1"  # 来自 spec
        assert "request_id" in pending[0]
        assert "expires_at" in pending[0]
    finally:
        registry.remove("rid-1")
        registry.remove("rid-2")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd astrbot_plugin_ask_user_choice && python -m pytest tests/test_interactive_choice_api.py -v
```

Expected: FAIL(no GET endpoint)

- [ ] **Step 3: Implement GET endpoint**

Append to `interactive_choice_api.py`:

```python
@router.get("/api/chat/interactive-choice/pending")
async def list_pending(
    request: Request,
    session_id: str = "",
    username: str = Depends(require_dashboard_user),
):
    """列出某 umo 下所有仍 pending 的 interactive_choice。

    Returns:
        200: {status: "ok", data: {pending: [{request_id, ...full InteractiveChoicePart}, ...]}}
        400: 缺 session_id 或非 webchat 会话
        403: session_id 属于其他用户
    """
    if not session_id:
        raise ApiError("Missing key: session_id", status_code=400)
    if not session_id.startswith("webchat:"):
        raise ApiError("Only webchat sessions supported", status_code=400)

    expected = _extract_username_from_umo(session_id)
    if not expected or expected != username:
        raise ApiError("Not authorized", status_code=403)

    pending_list = registry.list_pending_for_umo(session_id)
    parts = []
    for item in pending_list:
        spec = item["spec"].copy()
        spec["request_id"] = item["request_id"]
        spec["expires_at"] = item["timeout_at"]
        parts.append(spec)
    return ok({"pending": parts})
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd astrbot_plugin_ask_user_choice && python -m pytest tests/test_interactive_choice_api.py -v
```

Expected: 13 passed

- [ ] **Step 5: Commit**

```bash
cd astrbot_plugin_ask_user_choice
git add interactive_choice_api.py tests/test_interactive_choice_api.py
git commit -m "feat(api): add GET /api/chat/interactive-choice/pending"
```

---

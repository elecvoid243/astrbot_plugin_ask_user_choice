"""REST 端点单元测试。"""

import asyncio
import time

import pytest
from astrbot_plugin_ask_user_choice.interactive_choice_api import (
    _extract_username_from_umo,
    router,
)
from astrbot_plugin_ask_user_choice.interactive_choice_registry import registry
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_future() -> asyncio.Future:
    """Create a Future compatible with Python 3.12+ (no implicit event loop)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.create_future()


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
    assert (
        _extract_username_from_umo("webchat:FriendMessage:foo!bar") == ""
    )  # 缺 platform 头


def test_extract_username_handles_dots_and_dashes():
    umo = "webchat:FriendMessage:webchat!alice.smith_2!sess-2025-07-02"
    assert _extract_username_from_umo(umo) == "alice.smith_2"


# ---------------------------------------------------------------------------
# POST /api/chat/interactive-choice/<request_id>
# ---------------------------------------------------------------------------


@pytest.fixture
def app(monkeypatch):
    """构造测试用 FastAPI app,绕过真实 dashboard auth。"""
    from starlette.responses import JSONResponse

    from astrbot.dashboard.responses import ApiError, error

    test_app = FastAPI()
    test_app.include_router(router)

    # 注册 ApiError -> JSONResponse(同真实 dashboard)
    @test_app.exception_handler(ApiError)
    async def api_error_handler(_request, exc: ApiError):
        return JSONResponse(error(exc.message), status_code=exc.status_code)

    # 替换 require_dashboard_user 为一个固定 username 返回
    from astrbot.dashboard.api.auth import require_dashboard_user

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
    fut = _make_future()
    registry.add(
        "rid-1",
        "webchat:FriendMessage:webchat!alice!sess",
        fut,
        {"prompt": "x", "options": [{"id": "A", "label": "a"}]},
        0.0,
        time.time() + 60,
    )
    try:
        r = client.post("/api/chat/interactive-choice/rid-1", json={})
        assert r.status_code == 400
    finally:
        registry.remove("rid-1")


def test_post_403_when_other_user(client):
    # 重新构造 client,bob 登录
    from starlette.responses import JSONResponse

    from astrbot.dashboard.api.auth import require_dashboard_user
    from astrbot.dashboard.responses import ApiError, error

    app = FastAPI()
    app.include_router(router)

    @app.exception_handler(ApiError)
    async def api_error_handler(_request, exc: ApiError):
        return JSONResponse(error(exc.message), status_code=exc.status_code)

    app.dependency_overrides[require_dashboard_user] = lambda: "bob"
    c = TestClient(app)
    # pending 属于 alice
    fut = _make_future()
    registry.add(
        "rid-1",
        "webchat:FriendMessage:webchat!alice!sess",
        fut,
        {"prompt": "x", "options": [{"id": "A", "label": "a"}]},
        0.0,
        time.time() + 60,
    )
    try:
        r = c.post("/api/chat/interactive-choice/rid-1", json={"choice_id": "A"})
        assert r.status_code == 403
    finally:
        registry.remove("rid-1")


def test_post_success_resolves_future(client):
    fut = _make_future()
    registry.add(
        "rid-1",
        "webchat:FriendMessage:webchat!alice!sess",
        fut,
        {"prompt": "x", "options": [{"id": "A", "label": "alpha"}]},
        0.0,
        time.time() + 60,
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
    fut = _make_future()
    registry.add(
        "rid-1",
        "webchat:FriendMessage:webchat!alice!sess",
        fut,
        {"prompt": "x", "options": [{"id": "A", "label": "alpha"}]},
        0.0,
        time.time() + 60,
    )
    try:
        client.post("/api/chat/interactive-choice/rid-1", json={"choice_id": "A"})
        # 第二次
        r = client.post("/api/chat/interactive-choice/rid-1", json={"choice_id": "B"})
        assert r.status_code == 409
    finally:
        registry.remove("rid-1")


# ---------------------------------------------------------------------------
# DELETE /api/chat/interactive-choice/<request_id>
# ---------------------------------------------------------------------------


def _noop_push(*args, **kwargs):
    """Async noop used to stub the resolved-event broadcast."""

    async def _inner(*a, **k):
        pass

    return _inner(*args, **kwargs)


def test_delete_404_when_not_found(client):
    r = client.delete("/api/chat/interactive-choice/nonexistent")
    assert r.status_code == 404


def test_delete_403_when_other_user_keeps_future(client):
    # 重新构造 client,bob 登录
    from starlette.responses import JSONResponse

    from astrbot.dashboard.api.auth import require_dashboard_user
    from astrbot.dashboard.responses import ApiError, error

    app = FastAPI()
    app.include_router(router)

    @app.exception_handler(ApiError)
    async def api_error_handler(_request, exc: ApiError):
        return JSONResponse(error(exc.message), status_code=exc.status_code)

    app.dependency_overrides[require_dashboard_user] = lambda: "bob"
    c = TestClient(app)

    # pending 属于 alice
    fut = _make_future()
    registry.add(
        "rid-1",
        "webchat:FriendMessage:webchat!alice!sess",
        fut,
        {"prompt": "x", "options": [{"id": "A", "label": "a"}]},
        0.0,
        time.time() + 60,
    )
    try:
        r = c.delete("/api/chat/interactive-choice/rid-1")
        assert r.status_code == 403
        # 越权取消不得影响目标:future 仍在等待,条目仍在 registry
        assert not fut.done()
        assert "rid-1" in registry._pending
    finally:
        registry.remove("rid-1")


def test_delete_success_cancels_future_and_broadcasts(client, monkeypatch):
    calls = []

    async def fake_push(**kwargs):
        calls.append(kwargs)

    # 端点在函数体内延迟 import,因此 patch api_mount 模块属性即可生效
    monkeypatch.setattr(
        "astrbot_plugin_ask_user_choice.api_mount._push_resolved_event_to_back_queue",
        fake_push,
    )
    fut = _make_future()
    registry.add(
        "rid-1",
        "webchat:FriendMessage:webchat!alice!sess",
        fut,
        {"prompt": "x", "options": [{"id": "A", "label": "a"}]},
        0.0,
        time.time() + 60,
        sse_message_id="sse-1",
    )
    try:
        r = client.delete("/api/chat/interactive-choice/rid-1")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        # future 被取消,ask_user_choice 工具侧捕获 CancelledError
        assert fut.cancelled()
        # 条目已从 registry 移除
        assert "rid-1" not in registry._pending
        # 广播了一次 reason="cancelled" 的 resolved 事件(跨标签页一致性)
        assert len(calls) == 1
        assert calls[0]["request_id"] == "rid-1"
        assert calls[0]["reason"] == "cancelled"
        assert calls[0]["umo"] == "webchat:FriendMessage:webchat!alice!sess"
        assert calls[0]["sse_message_id"] == "sse-1"
    finally:
        registry.remove("rid-1")


def test_delete_twice_second_returns_404(client, monkeypatch):
    monkeypatch.setattr(
        "astrbot_plugin_ask_user_choice.api_mount._push_resolved_event_to_back_queue",
        _noop_push,
    )
    fut = _make_future()
    registry.add(
        "rid-1",
        "webchat:FriendMessage:webchat!alice!sess",
        fut,
        {"prompt": "x", "options": [{"id": "A", "label": "a"}]},
        0.0,
        time.time() + 60,
    )
    try:
        r1 = client.delete("/api/chat/interactive-choice/rid-1")
        assert r1.status_code == 200
        # 第二次:条目已移除 → 404(幂等语义,前端忽略错误)
        r2 = client.delete("/api/chat/interactive-choice/rid-1")
        assert r2.status_code == 404
    finally:
        registry.remove("rid-1")


def test_delete_broadcast_failure_still_cancels(client, monkeypatch):
    async def failing_push(**kwargs):
        raise RuntimeError("SSE queue unavailable")

    monkeypatch.setattr(
        "astrbot_plugin_ask_user_choice.api_mount._push_resolved_event_to_back_queue",
        failing_push,
    )
    fut = _make_future()
    registry.add(
        "rid-1",
        "webchat:FriendMessage:webchat!alice!sess",
        fut,
        {"prompt": "x", "options": [{"id": "A", "label": "a"}]},
        0.0,
        time.time() + 60,
    )
    try:
        # 广播失败不得影响取消主流程:仍返回 200,future 已被取消
        r = client.delete("/api/chat/interactive-choice/rid-1")
        assert r.status_code == 200
        assert fut.cancelled()
        assert "rid-1" not in registry._pending
    finally:
        registry.remove("rid-1")


# ---------------------------------------------------------------------------
# POST /api/chat/interactive-choice/pending?session_id=<umo>
# (端点为 POST:dashboard 静态文件 catch-all 会 shadow 所有 /api/* 的 GET)
# ---------------------------------------------------------------------------


def test_get_pending_400_when_missing_session_id(client):
    # 缺 session_id 查询参数
    r = client.post("/api/chat/interactive-choice/pending")
    assert r.status_code == 400


def test_get_pending_400_for_non_webchat_session(client):
    # alice 登录,但 session_id 不是 webchat 格式
    r = client.post(
        "/api/chat/interactive-choice/pending",
        params={"session_id": "lark:FriendMessage:lark!alice!sess"},
    )
    assert r.status_code == 400


def test_get_pending_403_when_other_user(client):
    # bob 登录,去查 alice 的 session
    from starlette.responses import JSONResponse

    from astrbot.dashboard.api.auth import require_dashboard_user
    from astrbot.dashboard.responses import ApiError, error

    app = FastAPI()
    app.include_router(router)

    @app.exception_handler(ApiError)
    async def api_error_handler(_request, exc: ApiError):
        return JSONResponse(error(exc.message), status_code=exc.status_code)

    app.dependency_overrides[require_dashboard_user] = lambda: "bob"
    c = TestClient(app)

    alice_umo = "webchat:FriendMessage:webchat!alice!sess"
    fut = _make_future()
    registry.add(
        "rid-1",
        alice_umo,
        fut,
        {"prompt": "x", "options": [{"id": "A", "label": "a"}]},
        0.0,
        time.time() + 60,
    )
    try:
        r = c.post(
            "/api/chat/interactive-choice/pending",
            params={"session_id": alice_umo},
        )
        assert r.status_code == 403
    finally:
        registry.remove("rid-1")


def test_get_pending_returns_alice_pending(client):
    fut1 = _make_future()
    fut2 = _make_future()
    registry.add(
        "rid-1",
        "webchat:FriendMessage:webchat!alice!sess",
        fut1,
        {"prompt": "p1", "options": [{"id": "A", "label": "a"}]},
        0.0,
        time.time() + 60,
    )
    registry.add(
        "rid-2",
        "webchat:FriendMessage:webchat!bob!sess",
        fut2,
        {"prompt": "p2", "options": [{"id": "B", "label": "b"}]},
        0.0,
        time.time() + 60,
    )
    try:
        r = client.post(
            "/api/chat/interactive-choice/pending?session_id=webchat:FriendMessage:webchat!alice!sess",
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        pending = body["data"]["pending"]
        assert len(pending) == 1
        assert pending[0]["request_id"] == "rid-1"
        assert pending[0]["prompt"] == "p1"
        assert "expires_at" in pending[0]
    finally:
        registry.remove("rid-1")
        registry.remove("rid-2")

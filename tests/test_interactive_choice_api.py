"""REST 端点单元测试。"""

import asyncio
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from astrbot_plugin_ask_user_choice.interactive_choice_api import (
    _extract_username_from_umo,
    router,
)
from astrbot_plugin_ask_user_choice.interactive_choice_registry import registry


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
    fut = asyncio.get_event_loop().create_future()
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
    fut = asyncio.get_event_loop().create_future()
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
    fut = asyncio.get_event_loop().create_future()
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
    fut = asyncio.get_event_loop().create_future()
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
# GET /api/chat/interactive-choice/pending?session_id=<umo>
# ---------------------------------------------------------------------------


def test_get_pending_400_when_missing_session_id(client):
    # 缺 session_id 查询参数
    r = client.get("/api/chat/interactive-choice/pending")
    assert r.status_code == 400


def test_get_pending_400_for_non_webchat_session(client):
    # alice 登录,但 session_id 不是 webchat 格式
    r = client.get(
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
    fut = asyncio.get_event_loop().create_future()
    registry.add(
        "rid-1",
        alice_umo,
        fut,
        {"prompt": "x", "options": [{"id": "A", "label": "a"}]},
        0.0,
        time.time() + 60,
    )
    try:
        r = c.get(
            "/api/chat/interactive-choice/pending",
            params={"session_id": alice_umo},
        )
        assert r.status_code == 403
    finally:
        registry.remove("rid-1")


def test_get_pending_returns_alice_pending(client):
    # alice 登录,查询自己 session 下的 pending
    alice_umo = "webchat:FriendMessage:webchat!alice!sess"
    fut = asyncio.get_event_loop().create_future()
    spec = {
        "prompt": "choose",
        "options": [{"id": "A", "label": "alpha"}],
    }
    registry.add(
        "rid-1",
        alice_umo,
        fut,
        spec,
        0.0,
        time.time() + 60,
    )
    try:
        r = client.get(
            "/api/chat/interactive-choice/pending",
            params={"session_id": alice_umo},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        items = body["data"]["pending"]
        assert len(items) == 1
        assert items[0]["request_id"] == "rid-1"
        assert items[0]["spec"] == spec
    finally:
        registry.remove("rid-1")

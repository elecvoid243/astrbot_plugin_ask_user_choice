"""InteractiveChoiceRegistry 单元测试。"""

import asyncio

import pytest

from astrbot_plugin_ask_user_choice.interactive_choice_registry import (
    InteractiveChoiceRegistry,
)


@pytest.fixture(autouse=True)
def _freeze_registry_clock(monkeypatch):
    """Freeze time.time() to 50.0 for tests so the brief's epoch-style timeout
    literals (e.g. 100.0, 110.0) remain unambiguously in the future.
    Restored automatically after each test.
    """
    from astrbot_plugin_ask_user_choice import interactive_choice_registry as reg_mod

    monkeypatch.setattr(reg_mod.time, "time", lambda: 50.0)


def _make_future() -> asyncio.Future:
    return asyncio.get_event_loop().create_future()


def test_add_registers_pending():
    reg = InteractiveChoiceRegistry()
    fut = _make_future()
    reg.add(
        request_id="r1",
        umo="webchat:FriendMessage:webchat!alice!sess",
        future=fut,
        spec={"prompt": "x", "options": [{"id": "A", "label": "a"}]},
        created_at=0.0,
        timeout_at=100.0,
    )
    assert "r1" in reg._pending
    assert "r1" in reg._by_umo["webchat:FriendMessage:webchat!alice!sess"]


def test_remove_clears_pending_and_by_umo():
    reg = InteractiveChoiceRegistry()
    fut = _make_future()
    umo = "webchat:FriendMessage:webchat!alice!sess"
    reg.add(
        "r1",
        umo,
        fut,
        {"prompt": "x", "options": [{"id": "A", "label": "a"}]},
        0.0,
        100.0,
    )
    reg.remove("r1")
    assert "r1" not in reg._pending
    assert umo not in reg._by_umo  # umo 索引被清空


def test_remove_unknown_is_noop():
    reg = InteractiveChoiceRegistry()
    reg.remove("nonexistent")  # 不应抛异常
    assert reg._pending == {}


def test_remove_cancels_unfinished_future():
    reg = InteractiveChoiceRegistry()
    fut = _make_future()
    reg.add(
        "r1",
        "webchat:FriendMessage:webchat!alice!sess",
        fut,
        {"prompt": "x", "options": [{"id": "A", "label": "a"}]},
        0.0,
        100.0,
    )
    reg.remove("r1")
    assert fut.cancelled() or fut.done()


def test_resolve_sets_future_result():
    reg = InteractiveChoiceRegistry()
    fut = _make_future()
    reg.add(
        "r1",
        "webchat:FriendMessage:webchat!alice!sess",
        fut,
        {"prompt": "x", "options": [{"id": "A", "label": "a"}]},
        0.0,
        100.0,
    )
    assert reg.resolve("r1", {"choice_id": "A", "free_text": ""}) is True
    assert fut.result() == {"choice_id": "A", "free_text": ""}


def test_resolve_unknown_returns_false():
    reg = InteractiveChoiceRegistry()
    assert reg.resolve("nonexistent", {"choice_id": "A"}) is False


def test_resolve_double_call_protected():
    reg = InteractiveChoiceRegistry()
    fut = _make_future()
    reg.add(
        "r1",
        "webchat:FriendMessage:webchat!alice!sess",
        fut,
        {"prompt": "x", "options": [{"id": "A", "label": "a"}]},
        0.0,
        100.0,
    )
    assert reg.resolve("r1", {"choice_id": "A"}) is True
    # 第二次 resolve 应返回 False(防双 resolve)
    assert reg.resolve("r1", {"choice_id": "B"}) is False
    # future 仍是第一次的结果
    assert fut.result() == {"choice_id": "A"}


def test_resolve_after_remove_returns_false():
    reg = InteractiveChoiceRegistry()
    fut = _make_future()
    reg.add(
        "r1",
        "webchat:FriendMessage:webchat!alice!sess",
        fut,
        {"prompt": "x", "options": [{"id": "A", "label": "a"}]},
        0.0,
        100.0,
    )
    reg.remove("r1")  # 移除后 future 被 cancel
    assert reg.resolve("r1", {"choice_id": "A"}) is False


def test_list_pending_for_umo_filters_correctly():
    reg = InteractiveChoiceRegistry()
    fut1 = _make_future()
    fut2 = _make_future()
    reg.add(
        "r1",
        "webchat:FriendMessage:webchat!alice!sess",
        fut1,
        {"prompt": "x", "options": [{"id": "A", "label": "a"}]},
        0.0,
        100.0,
    )
    reg.add(
        "r2",
        "webchat:FriendMessage:webchat!bob!sess",
        fut2,
        {"prompt": "y", "options": [{"id": "B", "label": "b"}]},
        0.0,
        100.0,
    )
    # alice 只能看到 r1
    alice_pending = reg.list_pending_for_umo("webchat:FriendMessage:webchat!alice!sess")
    assert len(alice_pending) == 1
    assert alice_pending[0]["request_id"] == "r1"


def test_list_pending_excludes_expired():
    reg = InteractiveChoiceRegistry()
    fut = _make_future()
    reg.add(
        "r1",
        "webchat:FriendMessage:webchat!alice!sess",
        fut,
        {"prompt": "x", "options": [{"id": "A", "label": "a"}]},
        created_at=0.0,
        timeout_at=-1.0,
    )  # 已超时
    assert reg.list_pending_for_umo("webchat:FriendMessage:webchat!alice!sess") == []


def test_list_pending_excludes_resolved():
    reg = InteractiveChoiceRegistry()
    fut = _make_future()
    reg.add(
        "r1",
        "webchat:FriendMessage:webchat!alice!sess",
        fut,
        {"prompt": "x", "options": [{"id": "A", "label": "a"}]},
        0.0,
        100.0,
    )
    reg.resolve("r1", {"choice_id": "A"})
    assert reg.list_pending_for_umo("webchat:FriendMessage:webchat!alice!sess") == []


def test_list_pending_includes_spec_and_timestamps():
    reg = InteractiveChoiceRegistry()
    fut = _make_future()
    spec = {"prompt": "test", "options": [{"id": "A", "label": "a"}]}
    reg.add(
        "r1",
        "webchat:FriendMessage:webchat!alice!sess",
        fut,
        spec,
        created_at=10.0,
        timeout_at=110.0,
    )
    result = reg.list_pending_for_umo("webchat:FriendMessage:webchat!alice!sess")
    assert len(result) == 1
    item = result[0]
    assert item["request_id"] == "r1"
    assert item["spec"] == spec
    assert item["created_at"] == 10.0
    assert item["timeout_at"] == 110.0


def test_stats_returns_counts():
    reg = InteractiveChoiceRegistry()
    fut = _make_future()
    reg.add("r1", "webchat:FriendMessage:webchat!alice!sess", fut,
            {"prompt": "x", "options": [{"id": "A", "label": "a"}]}, 0.0, 100.0)
    stats = reg.stats()
    assert stats["total_pending"] == 1
    assert stats["by_umo"]["webchat:FriendMessage:webchat!alice!sess"] == 1


@pytest.mark.asyncio
async def test_shutdown_cancels_all_futures():
    reg = InteractiveChoiceRegistry()
    fut1 = _make_future()
    fut2 = _make_future()
    reg.add("r1", "webchat:FriendMessage:webchat!alice!sess", fut1,
            {"prompt": "x", "options": [{"id": "A", "label": "a"}]}, 0.0, 100.0)
    reg.add("r2", "webchat:FriendMessage:webchat!bob!sess", fut2,
            {"prompt": "y", "options": [{"id": "B", "label": "b"}]}, 0.0, 100.0)
    await reg.shutdown()
    assert (fut1.cancelled() or fut1.done())
    assert (fut2.cancelled() or fut2.done())
    assert reg._pending == {}
    assert reg._by_umo == {}

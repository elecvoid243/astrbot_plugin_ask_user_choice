"""InteractiveChoiceRegistry 单元测试。"""

import asyncio

from astrbot_plugin_ask_user_choice.interactive_choice_registry import (
    InteractiveChoiceRegistry,
)


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

"""AskUserChoiceTool 单元测试。"""

import asyncio
import time
from unittest.mock import MagicMock

import pytest

from astrbot_plugin_ask_user_choice.ask_user_choice_tool import (
    AskUserChoiceTool,
    _PROMPT_MAX,
    _LABEL_MAX,
    _OPTIONS_MIN,
    _OPTIONS_MAX,
)
from astrbot_plugin_ask_user_choice.interactive_choice_registry import registry


def _make_context(umo: str = "webchat:FriendMessage:webchat!alice!sess"):
    """构造一个最小的 ContextWrapper mock。"""
    ctx = MagicMock()
    ctx.context.event.unified_msg_origin = umo
    return ctx


# ── _validate_and_build_spec 单元测试 ────────────────────────


def test_validate_rejects_empty_prompt():
    tool = AskUserChoiceTool()
    result = tool._validate_and_build_spec(
        {"prompt": "", "options": [{"id": "A", "label": "a"}]}
    )
    assert isinstance(result, str)
    assert "prompt" in result.lower()


def test_validate_rejects_too_few_options():
    tool = AskUserChoiceTool()
    result = tool._validate_and_build_spec(
        {
            "prompt": "test",
            "options": [{"id": "A", "label": "a"}],  # 只有 1 个,要求 >= 2
        }
    )
    assert isinstance(result, str)
    assert "options" in result.lower()


def test_validate_rejects_too_many_options():
    tool = AskUserChoiceTool()
    options = [
        {"id": chr(ord("A") + i), "label": f"opt{i}"} for i in range(_OPTIONS_MAX + 1)
    ]
    result = tool._validate_and_build_spec({"prompt": "test", "options": options})
    assert isinstance(result, str)


def test_validate_rejects_duplicate_ids():
    tool = AskUserChoiceTool()
    result = tool._validate_and_build_spec(
        {
            "prompt": "test",
            "options": [
                {"id": "A", "label": "a"},
                {"id": "A", "label": "b"},  # duplicate
            ],
        }
    )
    assert isinstance(result, str)
    assert "duplicate" in result.lower()


def test_validate_returns_dict_on_valid_input():
    tool = AskUserChoiceTool()
    result = tool._validate_and_build_spec(
        {
            "prompt": "test",
            "options": [
                {"id": "A", "label": "alpha"},
                {"id": "B", "label": "beta"},
            ],
        }
    )
    assert isinstance(result, dict)
    assert result["prompt"] == "test"
    assert result["type"] == "interactive_choice"
    assert len(result["options"]) == 2


def test_validate_truncates_long_prompt():
    tool = AskUserChoiceTool()
    long_prompt = "x" * (_PROMPT_MAX + 50)
    result = tool._validate_and_build_spec(
        {
            "prompt": long_prompt,
            "options": [{"id": "A", "label": "a"}, {"id": "B", "label": "b"}],
        }
    )
    assert isinstance(result, dict)
    assert len(result["prompt"]) == _PROMPT_MAX


def test_validate_truncates_long_label():
    tool = AskUserChoiceTool()
    long_label = "y" * (_LABEL_MAX + 50)
    result = tool._validate_and_build_spec(
        {
            "prompt": "test",
            "options": [{"id": "A", "label": long_label}, {"id": "B", "label": "b"}],
        }
    )
    assert isinstance(result, dict)
    assert len(result["options"][0]["label"]) == _LABEL_MAX


# ── call() 流程测试 (Task 6) ──────────────────────────────


@pytest.mark.asyncio
async def test_call_rejects_non_webchat_platform(monkeypatch):
    """非 webchat 会话应早 return 错误字符串,不推送事件。"""
    tool = AskUserChoiceTool()
    ctx = _make_context(umo="lark:FriendMessage:lark!user!sess")
    # monkeypatch webchat_queue_mgr,确认没被调用
    from unittest.mock import MagicMock

    mock_mgr = MagicMock()
    monkeypatch.setattr(
        "astrbot_plugin_ask_user_choice.ask_user_choice_tool.webchat_queue_mgr",
        mock_mgr,
        raising=False,
    )
    result = await tool.call(
        ctx,
        prompt="test",
        options=[{"id": "A", "label": "a"}, {"id": "B", "label": "b"}],
    )
    assert "Error" in result
    assert "webchat" in result.lower()
    mock_mgr.get_or_create_back_queue.assert_not_called()


@pytest.mark.asyncio
async def test_call_success_path_resolves_with_user_choice(monkeypatch):
    """成功路径:工具注册到 registry,推事件,await,resolve,return。"""
    import asyncio

    tool = AskUserChoiceTool()
    ctx = _make_context()

    # monkeypatch _push_to_webchat_back_queue 为 noop
    async def fake_push(*args, **kwargs):
        pass

    monkeypatch.setattr(tool, "_push_to_webchat_back_queue", fake_push)
    monkeypatch.setattr(tool, "_push_resolved_to_back_queue", fake_push)
    # monkeypatch config loader
    monkeypatch.setattr(
        tool,
        "_load_tool_config",
        lambda ctx: {
            "timeout_seconds": 5,
            "max_concurrent_pending": 32,
        },
    )

    # 启动工具调用协程
    call_task = asyncio.create_task(
        tool.call(
            ctx,
            prompt="Pick one",
            options=[{"id": "A", "label": "alpha"}, {"id": "B", "label": "beta"}],
        )
    )

    # 等 registry 注册
    await asyncio.sleep(0.05)
    assert len(registry._pending) == 1
    rid = next(iter(registry._pending.keys()))

    # 模拟用户选择
    registry.resolve(rid, {"choice_id": "A", "free_text": ""})

    # 等待工具返回
    result = await asyncio.wait_for(call_task, timeout=2.0)
    assert "User selected" in result
    assert "alpha" in result or "A" in result
    # registry 应被清理
    assert rid not in registry._pending


@pytest.mark.asyncio
async def test_call_timeout_returns_fallback(monkeypatch):
    """超时路径:工具返回 fallback 字符串。"""
    tool = AskUserChoiceTool()
    ctx = _make_context()

    async def fake_push(*args, **kwargs):
        pass

    monkeypatch.setattr(tool, "_push_to_webchat_back_queue", fake_push)
    monkeypatch.setattr(tool, "_push_resolved_to_back_queue", fake_push)
    monkeypatch.setattr(
        tool,
        "_load_tool_config",
        lambda ctx: {
            "timeout_seconds": 1,
            "timeout_fallback_message": "[User did not respond within 1 seconds.]",
            "max_concurrent_pending": 32,
        },
    )

    result = await tool.call(
        ctx,
        prompt="Pick one",
        options=[{"id": "A", "label": "a"}, {"id": "B", "label": "b"}],
    )
    assert "did not respond" in result
    assert len(registry._pending) == 0


# ── _format_choice_for_llm 单元测试 (Task 7) ────────────────────────


def test_format_choice_with_label_only():
    tool = AskUserChoiceTool()
    spec = {"options": [{"id": "A", "label": "alpha"}, {"id": "B", "label": "beta"}]}
    result = tool._format_choice_for_llm({"choice_id": "A", "free_text": ""}, spec)
    assert "alpha" in result
    assert "id=A" in result
    assert "Additional note" not in result


def test_format_choice_with_free_text():
    tool = AskUserChoiceTool()
    spec = {"options": [{"id": "A", "label": "alpha"}, {"id": "B", "label": "beta"}]}
    result = tool._format_choice_for_llm(
        {"choice_id": "B", "free_text": "因为快"},
        spec,
    )
    assert "beta" in result
    assert "id=B" in result
    assert "因为快" in result
    assert "Additional note" in result


def test_format_choice_with_free_text_only():
    tool = AskUserChoiceTool()
    spec = {"options": [{"id": "A", "label": "alpha"}, {"id": "B", "label": "beta"}]}
    result = tool._format_choice_for_llm(
        {"choice_id": "__free_text__", "free_text": "我选自己想的"},
        spec,
    )
    assert "__free_text__" in result
    assert "我选自己想的" in result


def test_format_choice_unknown_id_falls_back_to_id():
    tool = AskUserChoiceTool()
    spec = {"options": [{"id": "A", "label": "alpha"}]}
    result = tool._format_choice_for_llm({"choice_id": "Z", "free_text": ""}, spec)
    # Z 不在 options 里,label fallback 到 choice_id
    assert "Z" in result

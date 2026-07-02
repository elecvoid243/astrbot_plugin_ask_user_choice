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


def _make_context(umo: str = "webchat:FriendMessage:webchat!alice!sess"):
    """构造一个最小的 ContextWrapper mock。"""
    ctx = MagicMock()
    ctx.context.event.unified_msg_origin = umo
    return ctx


# ── _validate_and_build_spec 单元测试 ────────────────────────


def test_validate_rejects_empty_prompt():
    tool = AskUserChoiceTool()
    result = tool._validate_and_build_spec({"prompt": "", "options": [{"id": "A", "label": "a"}]})
    assert isinstance(result, str)
    assert "prompt" in result.lower()


def test_validate_rejects_too_few_options():
    tool = AskUserChoiceTool()
    result = tool._validate_and_build_spec({
        "prompt": "test",
        "options": [{"id": "A", "label": "a"}],  # 只有 1 个,要求 >= 2
    })
    assert isinstance(result, str)
    assert "options" in result.lower()


def test_validate_rejects_too_many_options():
    tool = AskUserChoiceTool()
    options = [{"id": chr(ord("A") + i), "label": f"opt{i}"} for i in range(_OPTIONS_MAX + 1)]
    result = tool._validate_and_build_spec({"prompt": "test", "options": options})
    assert isinstance(result, str)


def test_validate_rejects_duplicate_ids():
    tool = AskUserChoiceTool()
    result = tool._validate_and_build_spec({
        "prompt": "test",
        "options": [
            {"id": "A", "label": "a"},
            {"id": "A", "label": "b"},  # duplicate
        ],
    })
    assert isinstance(result, str)
    assert "duplicate" in result.lower()


def test_validate_returns_dict_on_valid_input():
    tool = AskUserChoiceTool()
    result = tool._validate_and_build_spec({
        "prompt": "test",
        "options": [
            {"id": "A", "label": "alpha"},
            {"id": "B", "label": "beta"},
        ],
    })
    assert isinstance(result, dict)
    assert result["prompt"] == "test"
    assert result["type"] == "interactive_choice"
    assert len(result["options"]) == 2


def test_validate_truncates_long_prompt():
    tool = AskUserChoiceTool()
    long_prompt = "x" * (_PROMPT_MAX + 50)
    result = tool._validate_and_build_spec({
        "prompt": long_prompt,
        "options": [{"id": "A", "label": "a"}, {"id": "B", "label": "b"}],
    })
    assert isinstance(result, dict)
    assert len(result["prompt"]) == _PROMPT_MAX


def test_validate_truncates_long_label():
    tool = AskUserChoiceTool()
    long_label = "y" * (_LABEL_MAX + 50)
    result = tool._validate_and_build_spec({
        "prompt": "test",
        "options": [{"id": "A", "label": long_label}, {"id": "B", "label": "b"}],
    })
    assert isinstance(result, dict)
    assert len(result["options"][0]["label"]) == _LABEL_MAX

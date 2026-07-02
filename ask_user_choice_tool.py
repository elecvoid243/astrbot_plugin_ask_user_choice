"""ask_user_choice 工具 (v1.0 真阻塞式)。

阻塞等待 dashboard 用户响应,完成后直接返回用户选择给 LLM。
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from astrbot.api import FunctionTool
from astrbot.core.utils.io import get_astrbot_data_path  # noqa: F401

from .interactive_choice_registry import registry

if TYPE_CHECKING:
    from astrbot.core.agent.run_context import ContextWrapper


# 字段长度上限
_PROMPT_MAX = 200
_TITLE_MAX = 30
_LABEL_MAX = 30
_DESCRIPTION_MAX = 200
_INPUT_PLACEHOLDER_MAX = 60
_OPTIONS_MIN = 2
_OPTIONS_MAX = 10


@dataclass
class AskUserChoiceTool(FunctionTool):
    """ask_user_choice 工具:阻塞式等待用户选择。"""

    name: str = "ask_user_choice"
    description: str = (
        "Present the user with a question and a set of options to choose from. "
        "Use this when you need the user to make a decision before you can proceed. "
        "This tool blocks until the user responds, then returns their choice. "
        "The user's response is returned directly as this tool's result."
    )
    parameters: dict = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Question displayed at the top of the option box",
            },
            "options": {
                "type": "array",
                "minItems": _OPTIONS_MIN,
                "maxItems": _OPTIONS_MAX,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "Unique option ID (e.g. A/B/C)",
                        },
                        "label": {
                            "type": "string",
                            "description": "Button text",
                        },
                        "description": {
                            "type": "string",
                            "description": "Optional detail",
                        },
                    },
                    "required": ["id", "label"],
                },
            },
            "title": {
                "type": "string",
                "description": "Optional dialog title",
            },
            "input_placeholder": {
                "type": "string",
                "description": "Free-text input placeholder",
            },
        },
        "required": ["prompt", "options"],
    })

    def _validate_and_build_spec(self, kwargs: dict) -> dict | str:
        """校验参数 + 截断 + 构造 spec dict。

        Args:
            kwargs: 工具调用参数。

        Returns:
            校验通过返回 spec dict,失败返回错误字符串(供 LLM 自助重试)。
        """
        prompt = (kwargs.get("prompt") or "").strip()
        if not prompt:
            return "Error: prompt cannot be empty"

        options = kwargs.get("options") or []
        if not isinstance(options, list) or not (
            _OPTIONS_MIN <= len(options) <= _OPTIONS_MAX
        ):
            return (
                f"Error: options must be an array with "
                f"{_OPTIONS_MIN}-{_OPTIONS_MAX} elements."
            )

        normalized = []
        seen = set()
        for idx, opt in enumerate(options):
            if not isinstance(opt, dict):
                return f"Error: options[{idx}] is not an object"
            oid = str(opt.get("id") or "").strip()
            label = str(opt.get("label") or "").strip()
            if not oid or not label:
                return f"Error: options[{idx}] needs id/label"
            if oid in seen:
                return f"Error: duplicate option id: {oid!r}"
            seen.add(oid)
            normalized.append({
                "id": oid,
                "label": label[:_LABEL_MAX],
                "description": (opt.get("description") or "")[:_DESCRIPTION_MAX] or None,
            })

        spec: dict = {
            "type": "interactive_choice",
            "prompt": prompt[:_PROMPT_MAX],
            "options": normalized,
        }
        title = kwargs.get("title")
        if title and title.strip():
            spec["title"] = title.strip()[:_TITLE_MAX]
        placeholder = kwargs.get("input_placeholder")
        if placeholder and placeholder.strip():
            spec["input_placeholder"] = placeholder.strip()[:_INPUT_PLACEHOLDER_MAX]
        return spec

    async def call(self, context: "ContextWrapper", **kwargs: Any) -> str:  # noqa: ARG002
        """阻塞式实现 — 见 Task 6。"""
        raise NotImplementedError("Implemented in Task 6")

    def _format_choice_for_llm(self, user_choice: dict, spec: dict) -> str:  # noqa: ARG002
        """格式化用户选择为 LLM 可见字符串 — 见 Task 7。"""
        raise NotImplementedError("Implemented in Task 7")

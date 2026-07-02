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

# lifted to module top per Plan Amendment B so tests can monkeypatch this binding
from astrbot.core.platform.sources.webchat.webchat_queue_mgr import webchat_queue_mgr

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
    parameters: dict = field(
        default_factory=lambda: {
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
        }
    )

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
            normalized.append(
                {
                    "id": oid,
                    "label": label[:_LABEL_MAX],
                    "description": (opt.get("description") or "")[:_DESCRIPTION_MAX]
                    or None,
                }
            )

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

    async def call(self, context: "ContextWrapper", **kwargs: Any) -> str:
        """阻塞等待用户响应,完成后返回用户选择给 LLM。

        Args:
            context: AstrBot 运行时上下文。
            **kwargs: 工具参数(prompt, options, title?, input_placeholder?)。

        Returns:
            成功: "User selected: <label> (id=<id>)[\\nAdditional note: <free_text>]"
            超时: 配置的 fallback message
            取消: "[User input was cancelled]"
            错误: "Error: ..."
        """
        # ── 1. 平台守卫 ──
        umo = context.context.event.unified_msg_origin
        if not umo.startswith("webchat:"):
            return (
                "Error: ask_user_choice is only supported in the webchat dashboard. "
                f"Current platform: {umo.split(':', 1)[0]}. "
                "Please open the dashboard to make your selection."
            )

        # ── 2. 参数校验 ──
        spec_or_error = self._validate_and_build_spec(kwargs)
        if isinstance(spec_or_error, str):
            return spec_or_error
        spec = spec_or_error

        # ── 3. 配置加载 ──
        config = self._load_tool_config(context)
        timeout_s = int(config.get("timeout_seconds", 300))
        fallback_msg = config.get(
            "timeout_fallback_message",
            "[User did not respond within {timeout} seconds. "
            "Please proceed with a reasonable default.]",
        ).format(timeout=timeout_s)
        max_concurrent = int(config.get("max_concurrent_pending", 32))

        # ── 4. 并发上限检查 ──
        if len(registry._pending) >= max_concurrent:
            return (
                f"Error: too many concurrent interactive choices "
                f"(max {max_concurrent}). "
                "Please wait for some to resolve."
            )

        # ── 5. 注册到 Registry ──
        request_id = str(uuid.uuid4())
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        expires_at = time.time() + timeout_s

        registry.add(
            request_id=request_id,
            umo=umo,
            future=future,
            spec=spec,
            created_at=time.time(),
            timeout_at=expires_at,
        )

        # ── 6. 推送 interactive_choice 事件给前端 ──
        try:
            await self._push_to_webchat_back_queue(
                request_id=request_id,
                umo=umo,
                spec=spec,
                expires_at=expires_at,
            )
        except Exception as exc:
            registry.remove(request_id)
            return f"Error: failed to push interactive choice to frontend: {exc}"

        # ── 7. 真阻塞 ──
        try:
            user_choice = await asyncio.wait_for(future, timeout=timeout_s)
        except asyncio.TimeoutError:
            return fallback_msg
        except asyncio.CancelledError:
            return "[User input was cancelled]"
        finally:
            registry.remove(request_id)

        # ── 8. 推 resolved 广播(失败不影响主流程) ──
        try:
            await self._push_resolved_to_back_queue(
                request_id=request_id,
                umo=umo,
                reason="submitted",
            )
        except Exception:
            pass

        # ── 9. 格式化为 LLM 可见字符串 ──
        return self._format_choice_for_llm(user_choice, spec)

    async def _push_to_webchat_back_queue(
        self,
        request_id: str,
        umo: str,
        spec: dict,
        expires_at: float,
    ) -> None:
        """推 interactive_choice 事件到 webchat SSE 流。

        Args:
            request_id: 本次交互请求的唯一 ID。
            umo: unified_msg_origin,例如 webchat:FriendMessage:webchat!alice!sess。
            spec: _validate_and_build_spec 输出的 spec dict。
            expires_at: Unix 时间戳,前端用来倒计时。
        """
        # uses module-level import (Plan Amendment B) so tests can monkeypatch
        parts = umo.split(":", 2)
        if len(parts) < 3:
            raise ValueError(f"Invalid umo: {umo}")
        session_key = parts[2]
        chunks = session_key.split("!")
        conversation_id = chunks[-1] if len(chunks) >= 3 else session_key

        back_queue = webchat_queue_mgr.get_or_create_back_queue(
            request_id=request_id,
            conversation_id=conversation_id,
        )
        await back_queue.put(
            {
                "type": "interactive_choice",
                "data": {
                    "request_id": request_id,
                    "spec": spec,
                    "expires_at": expires_at,
                    "umo": umo,
                },
                "message_id": request_id,
            }
        )

    async def _push_resolved_to_back_queue(
        self,
        request_id: str,
        umo: str,
        reason: str,
    ) -> None:
        """推 interactive_choice_resolved 事件给所有 SSE 订阅者。

        Args:
            request_id: 本次交互请求的唯一 ID。
            umo: unified_msg_origin,用于解析 conversation_id。
            reason: 解决原因(如 submitted / cancelled)。
        """
        parts = umo.split(":", 2)
        if len(parts) < 3:
            return
        session_key = parts[2]
        chunks = session_key.split("!")
        conversation_id = chunks[-1] if len(chunks) >= 3 else session_key

        back_queue = webchat_queue_mgr.get_or_create_back_queue(
            request_id=request_id,
            conversation_id=conversation_id,
        )
        await back_queue.put(
            {
                "type": "interactive_choice_resolved",
                "data": {"request_id": request_id, "reason": reason},
                "message_id": request_id,
            }
        )

    def _load_tool_config(self, context: "ContextWrapper") -> dict:
        """从插件 config 读配置。无法获取时返回空 dict(走默认值)。

        Args:
            context: AstrBot 运行时上下文。

        Returns:
            配置 dict;若读取失败或没有配置则返回 {}。
        """
        try:
            return context.context.get_config() or {}
        except Exception:
            return {}

    def _format_choice_for_llm(self, user_choice: dict, spec: dict) -> str:
        """格式化用户选择为 LLM 可见字符串。

        Minimal placeholder for Task 6: produces the
        ``"User selected: <label> (id=<id>)"`` string that ``call()`` needs
        to surface to the LLM. Task 7 will replace this with full
        free-text / unknown-id / validation handling.

        Args:
            user_choice: 用户响应,通常是 ``{choice_id, free_text}``。
            spec: _validate_and_build_spec 输出的 spec dict,用于查找 label。

        Returns:
            e.g. ``"User selected: alpha (id=A)"``。
        """
        choice_id = str((user_choice or {}).get("choice_id") or "").strip()
        label = choice_id
        for opt in spec.get("options") or []:
            if isinstance(opt, dict) and opt.get("id") == choice_id:
                label = str(opt.get("label") or choice_id)
                break
        return f"User selected: {label} (id={choice_id})"

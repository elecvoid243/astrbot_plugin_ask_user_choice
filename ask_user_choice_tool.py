"""astrbot_plugin_ask_user/ask_user_choice_tool.py

ask_user_choice 工具:让 LLM 在需要人类审批/选择时输出结构化选项框。

返回 JSON 字符串,由 WebChat 前端 ``useMessages.normalizePartsInternal``
(参考 spec §2.3) 解包为 ``InteractiveChoicePart`` 并渲染。

完整规范:
- 中间格式字段约束: spec §3.2
- 工具层校验/截断策略: spec §11.1
- 错误处理 (降级为 unknown-part): spec §7

Author: elecvoid243
Date: 2026-06-28
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from astrbot.api import FunctionTool, logger
from astrbot.api.message_components import Plain
from astrbot.core.message.message_event_result import MessageChain

from pending_registry import PendingRegistry, PendingRequest

if TYPE_CHECKING:
    from astrbot.core.agent.run_context import ContextWrapper


# ── 字段长度上限(spec §3.2 / §11.1 #4 双重截断) ────────────────
# 工具层先截,前端后截——两层不冲突,工具层截断用于节省 token。
_PROMPT_MAX = 200
_TITLE_MAX = 30
_LABEL_MAX = 30
_DESCRIPTION_MAX = 200
_INPUT_PLACEHOLDER_MAX = 60
_OPTIONS_MIN = 2
_OPTIONS_MAX = 10


@dataclass
class AskUserChoiceTool(FunctionTool):
    name: str = "ask_user_choice"
    timeout_seconds: int = 300
    """等待用户回复的超时秒数。-1 表示无限等待。"""

    registry: PendingRegistry = field(default_factory=PendingRegistry)
    """挂起态注册表;每个 tool 实例一个,跨调用复用。"""

    description: str = (
        "Present an interactive option box to the user, where they click on one of the options. The tool will return a formatted JSON, which will be displayed as option box in the frontend."
        "Use it when 1) Requires user authorization for sensitive/irreversible operations; 2) Let users make a decision among multiple candidate solutions."
        "After calling the tool, IMMEDIATELY PAUSE THE CURRENT TASK and wait for user's response."
    )

    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": (
                        "Question text, displayed at the top of the option box, e.g. 'Please select the plan to apply next:'"
                    ),
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
                                "description": (
                                    "The unique ID of the option. e.g. A/B/C or 1/2/3"
                                ),
                            },
                            "label": {
                                "type": "string",
                                "description": "Text displayed on the button for brief description.",
                            },
                            "description": {
                                "type": "string",
                                "description": "Detailed description of options.",
                            },
                        },
                        "required": ["id", "label"],
                    },
                    "description": "2-10 options.",
                },
                "title": {
                    "type": "string",
                    "description": "Optional option box titles, such as'Plan Selection'/'Operation Confirmation'",
                },
                "input_placeholder": {
                    "type": "string",
                    "description": (
                        "Placeholder for free input box, for example: 'or enter the model name you want to use ..'"
                    ),
                },
            },
            "required": ["prompt", "options"],
        }
    )

    async def call(
        self,
        context: ContextWrapper,  # noqa: ARG002  # v1 保留,未来基于 persona 决策(spec §11.2 #1)
        **kwargs: Any,
    ) -> str:
        """执行工具调用:校验 → 推 UI → 阻塞等用户 → 返回回执文本。

        Args:
            context: AstrBot 运行上下文(``ContextWrapper``)。v1 暂未使用,
                保留以备未来扩展(spec §11.2 #1)。
            **kwargs: LLM 传入的工具参数,期望包含 ``prompt`` / ``options``
                (必填) 与 ``title`` / ``input_placeholder`` (可选)。

        Returns:
            成功:用户回执文本(LLM 据此继续推理)。
            参数非法:`"Error: ..."` 纯文本以便 LLM 自助重试。
            并发拒绝:`"Error: There is already an unanswered ..."`。
            超时:`"Error: User did not respond within N seconds..."`。

        Spec: docs/superpowers/specs/2026-06-29-ask-user-choice-suspension-design.md §5.1
        """
        prompt: str = (kwargs.get("prompt") or "").strip()
        options: list[dict[str, Any]] = kwargs.get("options") or []
        title: str | None = kwargs.get("title")
        input_placeholder: str | None = kwargs.get("input_placeholder")

        # ① 软错误:参数不合法 → 返 Error 文本,LLM 自助重试
        if not prompt:
            return "Error: prompt cannot be empty"
        if not isinstance(options, list) or not (
            _OPTIONS_MIN <= len(options) <= _OPTIONS_MAX
        ):
            return (
                f"Error: options must be an array with {_OPTIONS_MIN}-{_OPTIONS_MAX} elements."
            )

        # ② 逐项校验 option
        normalized_options: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for idx, opt in enumerate(options):
            if not isinstance(opt, dict):
                return f"Error: options[{idx}] is not an object."
            oid = str(opt.get("id") or "").strip()
            label = str(opt.get("label") or "").strip()
            if not oid or not label:
                return f"Error: options[{idx}] needs id/label"
            if oid in seen_ids:
                return f"Error: Duplicate option id: {oid!r}."
            seen_ids.add(oid)
            normalized_options.append(
                {
                    "id": oid,
                    "label": label[:_LABEL_MAX],
                    "description": (
                        (opt.get("description") or "")[:_DESCRIPTION_MAX] or None
                    ),
                }
            )

        # ③ 构造 InteractiveChoicePart
        payload: dict[str, Any] = {
            "type": "interactive_choice",
            "prompt": prompt[:_PROMPT_MAX],
            "options": normalized_options,
        }
        if title and title.strip():
            payload["title"] = title.strip()[:_TITLE_MAX]
        if input_placeholder and input_placeholder.strip():
            payload["input_placeholder"] = input_placeholder.strip()[
                :_INPUT_PLACEHOLDER_MAX
            ]
        json_str = json.dumps(payload, ensure_ascii=False)

        # ④ 推 UI 给用户(走 event.send,不入 LLM 上下文)
        #    前端 unwrapInteractiveChoice 走"plain 内嵌 JSON"路径自动解包
        #    spec §5.1 / §12 决策 7
        event = context.context.event
        await event.send(MessageChain([Plain(json_str)]))

        # ⑤ 并发拒绝:同 sender 已有 pending → 返错误,不阻塞
        #    spec 决策 6
        #    注:has_pending + register 之间不能有 await(spec §4.3 注释)
        key = (event.unified_msg_origin, event.get_sender_id())
        if self.registry.has_pending(key):
            return (
                "Error: There is already an unanswered ask_user_choice "
                "for this sender. Please wait for the user to respond "
                "before asking again."
            )

        # ⑥ 注册 pending + 阻塞
        fut: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        req = PendingRequest(
            key=key,
            future=fut,
            prompt=prompt,
            timeout_seconds=self.timeout_seconds,
        )
        self.registry.register(req)
        logger.info(
            f"ask_user_choice: pending registered "
            f"(umo={event.unified_msg_origin}, sender={event.get_sender_id()}, "
            f"pending_id={req.pending_id})"
        )

        try:
            if self.timeout_seconds < 0:
                # 永久等待;只有用户回复 / 插件 terminate / LLM abort 才会结束
                return await fut
            return await asyncio.wait_for(fut, timeout=self.timeout_seconds)
        except asyncio.TimeoutError:
            logger.warning(
                f"ask_user_choice: timeout after {self.timeout_seconds}s "
                f"(pending_id={req.pending_id})"
            )
            return (
                f"Error: User did not respond within {self.timeout_seconds} seconds. "
                f"Please decide how to proceed (e.g., make a default choice, "
                f"ask again, or skip)."
            )
        finally:
            # try_resolve 时已 pop;此处防御 finally 路径(CancelledError 等)
            self.registry._pending.pop(key, None)


__all__ = ["AskUserChoiceTool"]

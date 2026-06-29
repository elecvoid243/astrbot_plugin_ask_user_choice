"""astrbot_plugin_ask_user/ask_user_choice_tool.py

ask_user_choice 工具:让 LLM 在需要人类审批/选择时输出结构化选项框。

返回 JSON 字符串,由 WebChat 前端 ``useMessages.normalizePartsInternal``
(参考 spec §2.3) 解包为 ``InteractiveChoicePart`` 并渲染。

完整规范:
- 中间格式字段约束: spec §3.2
- 工具层校验/截断策略: spec §11.1
- 错误处理 (降级为 unknown-part): spec §7
- v0.3.0 软阻塞增强(P1+P2):AGENTS.md §4.3.1
  - P1:本文件 ``description`` 字段改为硬话术(英文)
  - P2:策略文本 + marker + build_injection_policy() 函数
    由 ``main.py`` 通过 ``@filter.on_llm_request()`` 钩子注入 system_prompt

Author: elecvoid243
Date: 2026-06-28 (v0.1) / 2026-06-30 (v0.3)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from astrbot.api import FunctionTool

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


INJECTION_MARKER = "# ask_user_choice tool policy"

_SYSTEM_PROMPT_POLICY = (
    "After calling `ask_user_choice`, your turn is OVER: "
    "output no text, call no other tools, and wait for the user's response "
    "(it arrives as a regular user message in the next turn). "
    "The tool's return value is a frontend rendering protocol and carries no "
    "information about the user's choice."
)


def build_injection_policy() -> str:
    """构造待追加到 ``req.system_prompt`` 末尾的策略文本。

    格式::

        \\n\\n# ask_user_choice tool policy\\n\\n
        <policy>

    Returns:
        含前导换行的完整注入块。``main.py`` 在空 system_prompt 时
        用 ``.lstrip("\\n")`` 去掉前导换行,避免空 prompt 出现裸 \\n。
    """
    return f"\n\n{INJECTION_MARKER}\n\n{_SYSTEM_PROMPT_POLICY}"


@dataclass
class AskUserChoiceTool(FunctionTool):
    name: str = "ask_user_choice"
    description: str = (
        "Present an interactive option box so the user can pick one option "
        "(or type a custom answer). Use it ONLY for: (1) authorizing "
        "sensitive/irreversible actions, or (2) choosing among multiple "
        "candidate solutions. "
        "After calling this tool your turn is OVER: no more text, no more reasoning, no more tool calls."
        "Do not infer anything from the return value (it is just a frontend rendering protocol). "
        "Wait for the user's choice to arrive as a regular user message in the next turn."
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
        """执行工具调用:校验参数 → 截断 → 拼装 InteractiveChoicePart JSON。

        Args:
            context: AstrBot 运行上下文(``ContextWrapper``)。v1 暂未使用,
                保留以备未来扩展(spec §11.2 #1)。
            **kwargs: LLM 传入的工具参数,期望包含 ``prompt`` / ``options``
                (必填) 与 ``title`` / ``input_placeholder`` (可选)。

        Returns:
            spec §3.1 描述的 ``InteractiveChoicePart`` JSON 字符串;
            参数非法时返回 ``"错误:..."`` 纯文本以便 LLM 自助重试
            (spec §11.2 #2, 不抛异常以保留错误现场)。
        """
        prompt: str = (kwargs.get("prompt") or "").strip()
        options: list[dict[str, Any]] = kwargs.get("options") or []
        title: str | None = kwargs.get("title")
        input_placeholder: str | None = kwargs.get("input_placeholder")

        # ① 软错误:参数不合法 → 返回"错误:..."纯文本,
        #    让 LLM 看到错误信息并自行重试,避免工具异常打断整条链路
        if not prompt:
            return "Error: prompt cannot be empty"
        if not isinstance(options, list) or not (
            _OPTIONS_MIN <= len(options) <= _OPTIONS_MAX
        ):
            return (
                f"Error :options must be an array with {_OPTIONS_MIN}-{_OPTIONS_MAX} elements."
            )

        # ② 逐项校验 option;遇到不合法项直接报错误(整体拒绝,不走部分)
        normalized_options: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for idx, opt in enumerate(options):
            if not isinstance(opt, dict):
                return f"Error: options[{idx}] is not an object。"
            oid = str(opt.get("id") or "").strip()
            label = str(opt.get("label") or "").strip()
            if not oid or not label:
                return f"Error: options[{idx}] needs id/label"
            if oid in seen_ids:
                return f"Error: There are duplicate IDs in the options: {oid!r}。"
            seen_ids.add(oid)
            normalized_options.append(
                {
                    "id": oid,
                    "label": label[:_LABEL_MAX],  # 截断,见 §3.2
                    # 修正:`opt.get(key, default)` 只在 key 缺失时用 default;
                    # 当 LLM 显式传 `null` 时会回 None,然后 str(None)="None"。
                    # 这里改用 `or ""` 让 None/空字符串都归一为 ""。
                    "description": (
                        (opt.get("description") or "")[:_DESCRIPTION_MAX] or None
                    )
                }
            )

        # ③ 构造 InteractiveChoicePart;None 字段清理掉(spec §11.2 #5)
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

        # ④ 返回 JSON 字符串 — framework 走默认 Plain 包装,
        #    前端 normalizePartsInternal 检测 "{" 开头 + type 字段后展平
        return json.dumps(payload, ensure_ascii=False)


__all__ = [
    "AskUserChoiceTool",
    "INJECTION_MARKER",
    "build_injection_policy",
]

"""astrbot_plugin_ask_user 插件入口。

注册 :class:`AskUserChoiceTool` 到 AstrBot LLM 工具列表,使 LLM 能够在
需要人类审批/选择时调用 ``ask_user_choice`` 工具输出结构化选项框。

完整规范:
- 中间格式与字段约束: spec §3.1 / §3.2
- 数据流与回传路径: spec §6
- 工具定义: spec §11
- 启停配置: docs/superpowers/specs/2026-06-28-toggle-config-design.md

Author: elecvoid243
Date: 2026-06-28
"""

from __future__ import annotations

from astrbot.api import logger, star
from astrbot.api.star import Star
from astrbot.core.config import AstrBotConfig

from .ask_user_choice_tool import AskUserChoiceTool


class AskUserChoicePlugin(Star):
    """astrbot_plugin_ask_user 主类。

    加载时把 :class:`AskUserChoiceTool` 注册为全局 LLM 工具。
    若插件配置 ``enabled=false`` 则跳过注册,实现"功能开关"效果。

    运行时配置:见 ``_conf_schema.json``,当前仅含 ``enabled`` 字段。

    注:
        ``__init__`` 的 ``config`` 参数由 AstrBot 的
        :class:`StarManager` 在实例化时通过 ``plugin_cls(context, config)``
        传入(``astrbot/core/star/star_manager.py``)。不是所有 AstrBot
        插件都接受 config——只有声明了 ``_conf_schema.json`` 的才有。
    """

    def __init__(self, context: star.Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        # AstrBotConfig 是 dict 子类,直接走标准 .get API
        self.config = config

    async def initialize(self) -> None:
        """AstrBot 在插件加载完成后回调此方法。

        行为:
            - 读 ``self.config.get("enabled", True)``,关闭则 log + return。
            - 启用则调 ``self.context.add_llm_tools``(复数)注册工具。

        注:
            - 使用 ``add_llm_tools``(复数) 是当前 AstrBot 的正确 API,
              计划文档中拼写为单数形式 ``add_llm_tool``,但运行时仅
              存在复数版本(``astrbot/core/star/context.py``)。
        """
        # 启停开关:bool() 防御性包裹,容忍配置写成 0/1 或 "true"/"false"
        enabled = bool(self.config.get("enabled", True))
        if not enabled:
            logger.info(
                "ask_user_choice 工具已禁用(配置 enabled=false),跳过注册",
            )
            return

        self.context.add_llm_tools(AskUserChoiceTool())


__all__ = ["AskUserChoicePlugin"]

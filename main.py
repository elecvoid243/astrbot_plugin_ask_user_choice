"""astrbot_plugin_ask_user 插件入口。

注册 :class:`AskUserChoiceTool` 到 AstrBot LLM 工具列表,使 LLM 能够在
需要人类审批/选择时调用 ``ask_user_choice`` 工具输出结构化选项框。

完整规范:
- 中间格式与字段约束: spec §3.1 / §3.2
- 数据流与回传路径: spec §6
- 工具定义: spec §11
- 启停配置: docs/superpowers/specs/2026-06-28-toggle-config-design.md

v0.3.0 新增(vs v0.2.0):
- 硬话术 tool description:P1
- 通过 ``@filter.on_llm_request()`` 钩子向 ``req.system_prompt``
  末尾注入 ``ask_user_choice`` 使用规范:P2
- 两者配合,放大 LLM "调完即停" 的概率。
  不做真阻塞(p0 已由用户否决),所以是 "软阻塞" 方案。

Author: elecvoid243
Date: 2026-06-28 (v0.1) / 2026-06-30 (v0.3)
"""

from __future__ import annotations

from astrbot.api import logger, star
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Star
from astrbot.core.config import AstrBotConfig

from .ask_user_choice_tool import (
    INJECTION_MARKER,
    AskUserChoiceTool,
    build_injection_policy,
)


class AskUserChoicePlugin(Star):
    """astrbot_plugin_ask_user 主类。

    加载时:
    - 把 :class:`AskUserChoiceTool` 注册为全局 LLM 工具;
    - 通过 ``@filter.on_llm_request()`` 钩子在每次 LLM 请求前,
      向 ``req.system_prompt`` 末尾注入 ask_user_choice 使用规范。

    两者配合提高 LLM 在调用 ``ask_user_choice`` 后"自觉停下"的概率。

    运行时配置:见 ``_conf_schema.json``,当前仅含 ``enabled`` 字段。
    ``enabled=false`` 时:
    - 不注册工具(LLM 看不到 ask_user_choice);
    - 不注入策略(不污染系统提示词)。

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

    @filter.on_llm_request()
    async def _inject_ask_user_choice_policy(
        self, event: AstrMessageEvent, req: ProviderRequest
    ) -> None:
        """每次 LLM 请求前,把 ask_user_choice 使用规范追加到 system_prompt。

        行为:
            1. ``enabled=false`` → 直接 return,不污染 system_prompt。
            2. ``req.system_prompt`` 已包含 ``INJECTION_MARKER`` → 跳过,
               防止多 hook 链式触发时重复注入。
            3. ``req.system_prompt`` 为 None/空 → 直接赋值(去前导换行)。
            4. 否则 → 追加到末尾。

        参考实现:``astrbot_plugin_spcode_toolkit`` 的
        ``tools/agentsmd/_handlers.py:AgentsmdHandlers.on_llm_request``。
        同样采用 "marker 防重复 + 空字符串特判" 的范式。
        """
        # 1) 启停开关
        if not bool(self.config.get("enabled", True)):
            return

        system_prompt = req.system_prompt or ""

        # 2) marker 检测:已经注入过(例如上游 hook 替我们注入了)就跳过
        if INJECTION_MARKER in system_prompt:
            return

        # 3) + 4) 追加或新建
        if not system_prompt:
            # 空 system_prompt:去掉前导换行,避免裸 \n 开头
            req.system_prompt = build_injection_policy().lstrip("\n")
        else:
            req.system_prompt = system_prompt + build_injection_policy()

        logger.debug(
            "ask_user_choice: 已向 system_prompt 注入工具使用规范 "
            "(注入后长度 %d 字符)",
            len(req.system_prompt),
        )


__all__ = ["AskUserChoicePlugin"]

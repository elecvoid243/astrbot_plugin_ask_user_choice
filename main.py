"""astrbot_plugin_ask_user_choice 插件入口 (v1.0 真阻塞式)。

加载时:
- 注册 :class:`AskUserChoiceTool` 到 AstrBot LLM 工具列表;
- 把 :data:`interactive_choice_api.router` 挂到 dashboard FastAPI app。

v1.0 相比 v0.3:完全删除软阻塞(system_prompt 注入 + 硬话术),改用真阻塞
``await Future`` + 后端 REST 端点 resolve。

完整规范:
- 中间格式与字段约束:spec §3.1 / §5.1
- 数据流:spec §3 / §4
- 工具定义:spec §4.1

Author: elecvoid243
Date: 2026-07-03 (v1.0 重构)
"""

from __future__ import annotations

from astrbot.api import logger, star
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Star
from astrbot.core.config import AstrBotConfig

from .api_mount import _mount_api_router, _push_resolved_event_to_back_queue
from .ask_user_choice_tool import AskUserChoiceTool
from .interactive_choice_registry import registry


class AskUserChoicePlugin(Star):
    """astrbot_plugin_ask_user_choice 主类。

    加载时:
    - 把 :class:`AskUserChoiceTool` 注册为全局 LLM 工具;
    - 把交互端点 router 挂载到 dashboard app。
    """

    def __init__(self, context: star.Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        # AstrBotConfig 是 dict 子类,直接走标准 .get API
        self.config = config

    async def initialize(self) -> None:
        """AstrBot 在插件加载完成后回调此方法。

        行为:
            - 读 ``self.config.get("enabled", True)``,关闭则 log + return。
            - 启用则:
                1. 注册 ``AskUserChoiceTool``(复数 API,见
                   ``astrbot/core/star/context.py``);
                2. 挂载 ``api_router`` 到 dashboard app。

        失败策略 (Plan Amendment E):
            单一 try/except 包住整段挂载逻辑;挂载失败不回滚已注册的
            工具——LLM 仍可调用 ``ask_user_choice``,仅前端无法手动提交
            选择,降级为 warn 而非 raise。
        """
        enabled = bool(self.config.get("enabled", True))
        if not enabled:
            logger.info(
                "ask_user_choice 工具已禁用(配置 enabled=false),跳过注册",
            )
            return

        self.context.add_llm_tools(AskUserChoiceTool())
        _mount_api_router()

    async def terminate(self) -> None:
        """插件关闭:清空 Registry 中的所有 pending future。"""
        await registry.shutdown()
        logger.info("ask_user_choice: Registry 已关闭")

    @filter.platform_adapter_type(filter.PlatformAdapterType.ALL, priority=10)
    async def on_message(self, event: AstrMessageEvent) -> None:
        """拦截消息事件:若 UMO 有 pending interactive choice,消费消息作为 free text。

        场景:用户没有点击选项框,而是直接输入文字消息。该消息应作为
        ``ask_user_choice`` 工具的结果而不是触发新的 LLM 请求。

        优先级设为 10 以确保在 builtin handler 之前执行。
        """
        umo = event.unified_msg_origin
        if not umo.startswith("webchat:"):
            return

        pending = registry.find_pending_by_umo(umo)
        if pending is None:
            return

        message_text = (event.message_str or "").strip()
        if not message_text:
            return

        logger.info(
            f"ask_user_choice: 消费消息 '{message_text[:60]}' "
            f"作为会话 {umo[:80]} 的 pending choice 响应"
        )

        registry.resolve(
            pending.request_id,
            {"choice_id": "__free_text__", "free_text": message_text},
        )

        # 推 SSE resolved 事件,让前端关闭选项框
        try:
            await _push_resolved_event_to_back_queue(
                request_id=pending.request_id,
                umo=umo,
                reason="submitted",
                sse_message_id=pending.sse_message_id,
            )
        except Exception:
            pass

        # 阻止默认 LLM 请求 + 终止事件传播(消息已被消费)
        event.should_call_llm(False)
        event.stop_event()


__all__ = ["AskUserChoicePlugin"]

"""astrbot_plugin_ask_user 插件入口。"""

from __future__ import annotations

from astrbot.api import logger, star
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Star
from astrbot.core.config import AstrBotConfig

from .ask_user_choice_tool import AskUserChoiceTool


class AskUserChoicePlugin(Star):
    """astrbot_plugin_ask_user 主类。

    加载时把 :class:`AskUserChoiceTool` 注册为全局 LLM 工具。
    若插件配置 ``enabled=false`` 则跳过注册,实现"功能开关"效果。

    v0.3.0 新增:
        - ``timeout_seconds`` 配置项,控制用户回执超时(``-1`` = 永久等待)
        - ``on_user_message`` 钩子:拦截同 sender 的下一条消息作为工具回执
        - ``terminate`` 钩子:插件卸载时清理所有 pending,避免孤儿 Future

    运行时配置:见 ``_conf_schema.json``,含 ``enabled`` 与 ``timeout_seconds``
    两个字段。
    """

    def __init__(self, context: star.Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        # AstrBotConfig 是 dict 子类,直接走标准 .get API
        self.config = config
        # AskUserChoiceTool 实例,由 initialize 创建;terminate 时清理
        self._tool: AskUserChoiceTool | None = None

    async def initialize(self) -> None:
        """AstrBot 在插件加载完成后回调此方法。

        行为:
            - 读 ``self.config.get("enabled", True)``,关闭则 log + return。
            - 读 ``self.config.get("timeout_seconds", 300)``,校验后传给工具。
            - 实例化 ``AskUserChoiceTool(timeout_seconds=...)`` 并注册为 LLM 工具。

        Spec: docs/superpowers/specs/2026-06-29-ask-user-choice-suspension-design.md §5.4
        """
        # 启停开关
        if not bool(self.config.get("enabled", True)):
            logger.info(
                "ask_user_choice 工具已禁用(配置 enabled=false),跳过注册",
            )
            return

        # 读 timeout_seconds,做防御性校验
        timeout_seconds = int(self.config.get("timeout_seconds", 300))
        if timeout_seconds < -1 or timeout_seconds == 0:
            logger.warning(
                f"ask_user_choice: timeout_seconds={timeout_seconds} 非法,回退到默认 300",
            )
            timeout_seconds = 300

        # 实例化 + 注册
        self._tool = AskUserChoiceTool(timeout_seconds=timeout_seconds)
        self.context.add_llm_tools(self._tool)

    @filter.platform_adapter_type(filter.PlatformAdapterType.ALL)
    async def on_user_message(self, event: AstrMessageEvent) -> None:
        """拦截同 sender 的下一条消息,作为 ask_user_choice 的回执。

        仅在 ``self._tool.registry`` 中有同 (unified_msg_origin, sender_id)
        的 pending 时触发;否则放行原消息(走 AstrBot 正常 LLM 流程)。

        行为:
            - 命中 pending → ``future.set_result(user_text)`` + ``event.stop_event()``
              → 阻止该消息触发新 LLM 轮,挂起的工具协程醒来并把 user_text
              作为 tool result 返回。
            - 未命中 → 不做任何处理,AstrBot 继续走正常流程。

        Spec: docs/superpowers/specs/2026-06-29-ask-user-choice-suspension-design.md §5.2
        """
        if self._tool is None:
            return  # 工具未注册(enabled=false),放行

        key = (event.unified_msg_origin, event.get_sender_id())
        user_text = event.message_str.strip()

        # 提前检查:无 pending 走普通 LLM 路径
        pending = self._tool.registry._pending.get(key)
        if pending is None or pending.future.done():
            return

        # 空消息(纯表情/图片)不消费,留给 AstrBot 自己处理
        if not user_text:
            return

        # resolve + 阻止 LLM 轮
        if self._tool.registry.try_resolve(key, user_text):
            event.stop_event()
            # 注:event.stop_event() 在 process_stage 的 star_request_sub_stage 阶段调用,
            # 之后 agent_sub_stage(LLM 调用)会被跳过(见 process_stage/stage.py)。
            logger.info(
                f"ask_user_choice: user reply resolved "
                f"(umo={event.unified_msg_origin}, sender={event.get_sender_id()}, "
                f"len={len(user_text)})"
            )

    async def terminate(self) -> None:
        """AstrBot 在插件卸载时回调此方法。

        清理所有 pending request,触发它们的 CancelledError,使正在
        ``await Future`` 的工具协程抛出并被 LLM 框架吞掉。

        Spec: docs/superpowers/specs/2026-06-29-ask-user-choice-suspension-design.md §4.3
        """
        if self._tool is not None:
            self._tool.registry.cleanup_all()


__all__ = ["AskUserChoicePlugin"]

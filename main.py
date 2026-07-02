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
from astrbot.api.star import Star
from astrbot.core.config import AstrBotConfig

from .ask_user_choice_tool import AskUserChoiceTool
from .interactive_choice_api import router as api_router
from .interactive_choice_registry import registry


def _mount_api_router() -> bool:
    """把 :data:`api_router` 挂载到 dashboard FastAPI app。

    Returns:
        True if mount succeeded; False if dashboard 尚未初始化或挂载失败
        (退化模式:工具仍可工作,只是前端无法手动提交选择)。

    Implementation notes (Plan Amendment A):
        AstrBot 的 :class:`FastAPIAppAdapter` 只暴露 Flask 风格的
        ``add_url_rule``;本插件调用 ``include_router`` 时必须穿透到底层
        FastAPI 实例(``APP._app``,私有 API)。这是 dashboard 内部挂载
        ``build_api_router()`` 时用的同款手法,目前 AstrBot 没有公开的
        ``add_api_router`` 等价方法。
    """
    try:
        from astrbot.dashboard.server import APP

        if APP is None:
            logger.warning(
                "ask_user_choice: dashboard APP 尚未初始化,REST 端点未挂载",
            )
            return False
        underlying = getattr(APP, "_app", None)
        if underlying is None:
            logger.warning(
                "ask_user_choice: dashboard APP 缺少 _app 属性,REST 端点未挂载",
            )
            return False
        underlying.include_router(api_router)
    except Exception as exc:  # noqa: BLE001 - 任何挂载异常都降级为 warn
        logger.warning(f"ask_user_choice: REST 端点挂载失败 ({exc})")
        return False
    else:
        logger.info("ask_user_choice: REST 端点已挂载到 dashboard app")
        return True


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


__all__ = ["AskUserChoicePlugin"]

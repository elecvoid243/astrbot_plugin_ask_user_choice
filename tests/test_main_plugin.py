"""main.py 单元测试: 插件加载 + dashboard router 挂载。

Task 11:验证 AskUserChoicePlugin.initialize() 同时
  (1) 注册 AskUserChoiceTool 到 context.add_llm_tools
  (2) 把 interactive_choice_api.router 挂到 dashboard app

真实环境无 dashboard (AstrBot 进程外运行),所以 mock ``APP`` 全局。
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from astrbot_plugin_ask_user_choice.ask_user_choice_tool import AskUserChoiceTool
from astrbot_plugin_ask_user_choice.interactive_choice_api import (
    router as api_router,
)
from astrbot_plugin_ask_user_choice.main import AskUserChoicePlugin


def _make_context() -> MagicMock:
    """Mocked AstrBot Context,只关心 add_llm_tools。"""
    ctx = MagicMock()
    ctx.add_llm_tools = MagicMock()
    return ctx


def _make_config(enabled: bool = True) -> MagicMock:
    """Mocked AstrBotConfig。.get('enabled', True) 返回指定值。"""
    cfg = MagicMock()
    cfg.get = MagicMock(return_value=enabled)
    return cfg


def _run(coro):
    """简化:把 async coro 跑完。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


# ── initialize() 行为 ────────────────────────────────────────────


def test_initialize_registers_llm_tool():
    """enabled=True 时,initialize() 把 AskUserChoiceTool 注册到 context。"""
    ctx = _make_context()
    cfg = _make_config(enabled=True)

    # dashboard APP 设为 None(模拟 dashboard 还没起来),不应影响工具注册
    with patch("astrbot.dashboard.server.APP", None):
        plugin = AskUserChoicePlugin(ctx, cfg)
        _run(plugin.initialize())

    ctx.add_llm_tools.assert_called_once()
    tool = ctx.add_llm_tools.call_args[0][0]
    assert isinstance(tool, AskUserChoiceTool)


def test_initialize_mounts_dashboard_router():
    """enabled=True 时,initialize() 把 api_router 挂到 dashboard FastAPI app。"""
    ctx = _make_context()
    cfg = _make_config(enabled=True)

    # mock FastAPIAppAdapter + 底层 FastAPI
    fake_fastapi = MagicMock()
    fake_adapter = MagicMock()
    fake_adapter._app = fake_fastapi

    with patch("astrbot.dashboard.server.APP", fake_adapter):
        plugin = AskUserChoicePlugin(ctx, cfg)
        _run(plugin.initialize())

    # 验证 FastAPI 的 include_router 被调用,且传入的就是我们的 api_router
    fake_fastapi.include_router.assert_called_once_with(api_router)

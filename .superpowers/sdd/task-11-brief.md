## Task 11: 插件 main.py 挂载 router

**Files:**
- Modify: `astrbot_plugin_ask_user_choice/main.py` (完全重写)

- [ ] **Step 1: 备份旧 main.py 了解旧结构**

```bash
cd astrbot_plugin_ask_user_choice && cat main.py
```

> 旧 main.py 内容已在 brainstorming 阶段看过,含 `_inject_ask_user_choice_policy` 钩子等。

- [ ] **Step 2: Write the new main.py (完全重写)**

`astrbot_plugin_ask_user_choice/main.py`:

```python
"""astrbot_plugin_ask_user_choice 插件入口 (v1.0 真阻塞式)。

注册 :class:`AskUserChoiceTool` 到 AstrBot LLM 工具列表 + 挂载 REST 端点。
v1.0 相比 v0.3:完全删除软阻塞(system_prompt 注入 + 硬话术),改用真阻塞
await Future + 后端 REST 端点 resolve。

完整规范:
- 中间格式与字段约束:spec §3.1 / §5.1
- 数据流:spec §3 / §4
- 工具定义:spec §4.1

Author: elecvoid243
Date: 2026-07-02 (v1.0 重构)
"""
from __future__ import annotations

import logging

from astrbot.api import star
from astrbot.api.star import Star
from astrbot.core.config import AstrBotConfig

from .ask_user_choice_tool import AskUserChoiceTool
from .interactive_choice_api import router as api_router
from .interactive_choice_registry import registry

logger = logging.getLogger(__name__)


class AskUserChoicePlugin(Star):
    """astrbot_plugin_ask_user_choice 主类。

    加载时:
    - 把 :class:`AskUserChoiceTool` 注册为全局 LLM 工具;
    - 把交互端点 router 挂载到 dashboard app。
    """

    def __init__(self, context: star.Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.config = config

    async def initialize(self) -> None:
        """AstrBot 在插件加载完成后回调此方法。"""
        enabled = bool(self.config.get("enabled", True))
        if not enabled:
            logger.info("ask_user_choice 工具已禁用 (enabled=false)")
            return

        # 1. 注册工具
        self.context.add_llm_tools(AskUserChoiceTool())

        # 2. 挂载 REST 端点到 dashboard app
        # 尝试两种已知的 dashboard app 访问方式,任一成功即可
        mounted = False
        try:
            from astrbot.core.dashboard.server import APP  # type: ignore
            if APP is not None:
                APP.include_router(api_router)
                logger.info("ask_user_choice: REST 端点已挂载到 dashboard app")
                mounted = True
        except Exception as e:
            logger.debug(f"ask_user_choice: APP 方式挂载失败 ({e}),尝试备选")

        if not mounted:
            # 备选:通过 FastAPIAppAdapter 全局实例(若 AstrBot 暴露)
            try:
                from astrbot.dashboard.server import APP as ADAPTER  # type: ignore
                if ADAPTER is not None and hasattr(ADAPTER, "_app"):
                    ADAPTER._app.include_router(api_router)
                    logger.info("ask_user_choice: REST 端点已通过 FastAPIAppAdapter 挂载")
                    mounted = True
            except Exception as e:
                logger.warning(f"ask_user_choice: 备选挂载方式也失败 ({e})")

        if not mounted:
            logger.warning(
                "ask_user_choice: REST 端点未挂载,工具仍可工作但前端无法提交选择"
            )

    async def terminate(self) -> None:
        """插件关闭:清空 Registry。"""
        await registry.shutdown()
        logger.info("ask_user_choice: Registry 已关闭")


__all__ = ["AskUserChoicePlugin"]
```

- [ ] **Step 3: Verify import works**

```bash
cd astrbot_plugin_ask_user_choice && python -c "from .main import AskUserChoicePlugin; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Verify grep 0 命中(清理验证)**

```bash
cd astrbot_plugin_ask_user_choice
grep -rn "unwrapInteractiveChoice\|extractAskUserChoiceFromToolCall\|_SYSTEM_PROMPT_POLICY\|INJECTION_MARKER\|build_injection_policy\|_inject_ask_user_choice_policy" . --include="*.py"
```

Expected: no output

- [ ] **Step 5: Run all tests**

```bash
cd astrbot_plugin_ask_user_choice && python -m pytest tests/ -v
```

Expected: 33 passed (13 registry + 14 tool + 6 api,但实际数字以累计为准)

- [ ] **Step 6: Commit**

```bash
cd astrbot_plugin_ask_user_choice
git add main.py
git commit -m "refactor(plugin): rewrite main.py for v1.0, remove soft-block injection"
```

---

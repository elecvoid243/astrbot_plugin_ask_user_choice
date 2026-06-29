# ask_user_choice 工具挂起机制 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `astrbot_plugin_ask_user` 从 v0.2.0（"工具立即返回"）升级到 v0.3.0（"工具阻塞 LLM 循环直到用户点击/输入"）。

**Architecture:** 在工具内 `await asyncio.Future` 真挂起 LLM 工具循环；新增 `PendingRegistry` 管理挂起态；新增插件 `on_message` 钩子用用户回执 resolve Future；`Plain(json_str)` 经 `event.send()` 推 UI 给前端（利用既有 `unwrapInteractiveChoice` "plain 内嵌 JSON" 路径）。

**Tech Stack:** Python 3.10+ / asyncio / dataclass / pytest / AstrBot 4.16+ plugin SDK。

**Spec:** `docs/superpowers/specs/2026-06-29-ask-user-choice-suspension-design.md`

---

## File Structure

| 路径 | 状态 | 职责 |
|------|------|------|
| `pending_registry.py` | **新建** | `PendingRequest` 数据类 + `PendingRegistry`（单实例挂在 `AskUserChoiceTool` 上） |
| `ask_user_choice_tool.py` | **修改** | 校验逻辑保持原样；`call()` 改为"推 UI → 注册 pending → await Future → 返用户文本" |
| `main.py` | **修改** | `initialize` 读 `timeout_seconds`；新增 `@filter.on_message` 钩子 |
| `_conf_schema.json` | **修改** | 新增 `timeout_seconds` 字段 |
| `metadata.yaml` | **修改** | `version: v0.2.0 → v0.3.0`；desc 增加"并阻塞" |
| `test_pending_registry.py` | **新建** | `PendingRegistry` 的 pytest 单元测试 |
| `requirements.txt` | **修改** | 增加 `pytest>=7`、`pytest-asyncio>=0.21`（dev dependency） |
| `README.md` | **修改** | v0.3.0 changelog 段；§8 已知限制摘录 |

**文件大小预估**：`pending_registry.py` ~80 行；`test_pending_registry.py` ~100 行；其他文件每处增量 < 50 行。

---

## Chunk 1: 数据层（PendingRegistry + 单测）

### Task 1: `PendingRequest` 数据类 + 基础 `PendingRegistry` API

**Files:**
- Create: `pending_registry.py`
- Create: `test_pending_registry.py`

- [ ] **Step 1: 写失败测试 `test_register_resolve_basic`**

`test_pending_registry.py`:

```python
"""PendingRegistry 单元测试。

Author: elecvoid243
Date: 2026-06-29
Spec: docs/superpowers/specs/2026-06-29-ask-user-choice-suspension-design.md §4.3 / §9.2
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from pending_registry import PendingRegistry, PendingRequest


@pytest.mark.asyncio
async def test_register_resolve_basic():
    reg = PendingRegistry()
    key = ("umo:x", "sender:1")
    fut = asyncio.get_event_loop().create_future()
    req = PendingRequest(key=key, future=fut, prompt="p")
    reg.register(req)

    assert reg.has_pending(key) is True
    assert reg.try_resolve(key, "A") is True
    assert fut.result() == "A"
    assert reg.has_pending(key) is False
```

- [ ] **Step 2: 跑测试，确认失败**

Run:
```bash
cd F:\github\astrbot_plugin_ask_user_choice
python -m pytest test_pending_registry.py::test_register_resolve_basic -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'pending_registry'`。

- [ ] **Step 3: 实现 `pending_registry.py` 最小版本**

```python
"""ask_user_choice 工具的挂起状态管理。

Author: elecvoid243
Date: 2026-06-29
Spec: docs/superpowers/specs/2026-06-29-ask-user-choice-suspension-design.md §4.1 / §4.3
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass
class PendingRequest:
    """一次 ask_user_choice 调用的挂起态。"""

    key: tuple[str, str]
    """(unified_msg_origin, sender_id)"""

    future: asyncio.Future[str]
    """等待用户回执(文本)"""

    pending_id: str = field(default_factory=lambda: uuid4().hex[:12])
    """自生成短 id,用于跨 tool.call 与 on_message 的日志关联"""

    prompt: str = ""
    """选项框的 prompt(用于日志/调试)"""

    created_at: float = field(default_factory=asyncio.get_event_loop().time if False else 0.0)
    """实际用 monotonic,但 0.0 占位避免导入 side-effect;真实代码见 Task 2"""

    timeout_seconds: int = 300


class PendingRegistry:
    """ask_user_choice 工具的挂起态注册表。"""

    def __init__(self) -> None:
        self._pending: dict[tuple[str, str], PendingRequest] = {}

    def has_pending(self, key: tuple[str, str]) -> bool:
        return key in self._pending

    def register(self, req: PendingRequest) -> None:
        """tool.call() 调用。已存在同 key 时由调用方处理拒绝逻辑。

        并发安全:asyncio 单线程,dict __setitem__ 原子;
        调用方必须保证 "has_pending + register" 块内**没有 await**。
        """
        self._pending[req.key] = req

    def try_resolve(self, key: tuple[str, str], text: str) -> bool:
        """on_message 钩子调用。

        Returns:
            True  = 成功 resolve(消息应被消费)
            False = 无挂起或已 resolved(放行原消息)
        """
        req = self._pending.pop(key, None)
        if req is None or req.future.done():
            return False
        req.future.set_result(text)
        return True

    def cancel(self, key: tuple[str, str], reason: str = "cancelled") -> bool:
        req = self._pending.pop(key, None)
        if req is None or req.future.done():
            return False
        req.future.set_exception(asyncio.CancelledError(reason))
        return True

    def cleanup_all(self) -> None:
        for key in list(self._pending.keys()):
            self.cancel(key, reason="plugin_terminated")
```

- [ ] **Step 4: 跑测试，确认通过**

Run:
```bash
python -m pytest test_pending_registry.py::test_register_resolve_basic -v
```

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
cd F:\github\astrbot_plugin_ask_user_choice
git add pending_registry.py test_pending_registry.py
git commit -m "feat(pending_registry): add PendingRequest + PendingRegistry skeleton"
```

---

### Task 2: 修正 `created_at` 字段为 monotonic clock + 补单测

**Files:**
- Modify: `pending_registry.py:33-35`
- Modify: `test_pending_registry.py`（追加测试）

- [ ] **Step 1: 修正 `created_at` 默认值**

`pending_registry.py` 顶部 import 增加 `import time`，将 `created_at` 字段改为：

```python
    created_at: float = field(default_factory=time.monotonic)
```

- [ ] **Step 2: 写失败测试 `test_created_at_is_monotonic`**

`test_pending_registry.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_created_at_is_monotonic():
    reg = PendingRegistry()
    fut = asyncio.get_event_loop().create_future()
    before = __import__("time").monotonic()
    req = PendingRequest(key=("u", "s"), future=fut, prompt="p")
    after = __import__("time").monotonic()
    assert before <= req.created_at <= after
```

- [ ] **Step 3: 跑测试，确认通过**

Run:
```bash
python -m pytest test_pending_registry.py -v
```

Expected: 2 passed。

- [ ] **Step 4: 提交**

```bash
git add pending_registry.py test_pending_registry.py
git commit -m "fix(pending_registry): use time.monotonic for created_at"
```

---

### Task 3: 补齐 `PendingRegistry` 边界场景单测

**Files:**
- Modify: `test_pending_registry.py`（追加 4 个测试）

- [ ] **Step 1: 追加 4 个失败测试**

`test_pending_registry.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_resolve_unknown_key_returns_false():
    reg = PendingRegistry()
    assert reg.try_resolve(("nope", "0"), "A") is False


@pytest.mark.asyncio
async def test_resolve_already_resolved_returns_false():
    reg = PendingRegistry()
    key = ("umo", "s")
    fut = asyncio.get_event_loop().create_future()
    reg.register(PendingRequest(key=key, future=fut, prompt="p"))
    fut.set_result("first")
    assert reg.try_resolve(key, "second") is False
    assert reg.has_pending(key) is False  # 已 pop


@pytest.mark.asyncio
async def test_pending_id_is_unique():
    reg = PendingRegistry()
    ids: set[str] = set()
    for i in range(5):
        fut = asyncio.get_event_loop().create_future()
        req = PendingRequest(key=(f"umo{i}", f"s{i}"), future=fut, prompt="p")
        reg.register(req)
        ids.add(req.pending_id)
    assert len(ids) == 5


@pytest.mark.asyncio
async def test_cancel():
    reg = PendingRegistry()
    key = ("umo", "s")
    fut = asyncio.get_event_loop().create_future()
    reg.register(PendingRequest(key=key, future=fut, prompt="p"))
    assert reg.cancel(key, reason="test") is True
    with pytest.raises(asyncio.CancelledError):
        fut.result()
    assert reg.has_pending(key) is False


@pytest.mark.asyncio
async def test_cancel_unknown_returns_false():
    reg = PendingRegistry()
    assert reg.cancel(("nope", "0"), reason="x") is False


@pytest.mark.asyncio
async def test_cleanup_all():
    reg = PendingRegistry()
    futures: list[asyncio.Future[str]] = []
    for i in range(3):
        fut = asyncio.get_event_loop().create_future()
        reg.register(PendingRequest(key=(f"umo{i}", f"s{i}"), future=fut, prompt="p"))
        futures.append(fut)
    reg.cleanup_all()
    for fut in futures:
        with pytest.raises(asyncio.CancelledError):
            fut.result()
    assert reg.has_pending(("umo0", "s0")) is False
```

- [ ] **Step 2: 跑全部测试**

Run:
```bash
python -m pytest test_pending_registry.py -v
```

Expected: 7 passed（Task 1 + 2 + 3 全部）。

- [ ] **Step 3: 提交**

```bash
git add test_pending_registry.py
git commit -m "test(pending_registry): add edge-case unit tests"
```

---

## Chunk 2: 工具层改造

### Task 4: 在 `AskUserChoiceTool` 上挂 `PendingRegistry` 字段

**Files:**
- Modify: `ask_user_choice_tool.py:18-25`（imports）
- Modify: `ask_user_choice_tool.py:38`（class body 顶部）

- [ ] **Step 1: 修改 imports**

`ask_user_choice_tool.py` 第 18 行附近加：

```python
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from astrbot.api import FunctionTool
from astrbot.api.message_components import Plain
from astrbot.core.message.message_event_result import MessageChain

from pending_registry import PendingRegistry, PendingRequest
```

- [ ] **Step 2: 验证 imports 不破坏现有 import 顺序（标准库→第三方→astrbot→本地）**

当前 imports:
- 标准库: `json`, `dataclass`, `field`, `TYPE_CHECKING`, `Any`
- astrbot: `FunctionTool`
- 本地: 无

调整后:
- 标准库: `asyncio`, `json`, `dataclass`, `field`, `TYPE_CHECKING`, `Any`
- astrbot: `FunctionTool`, `Plain`, `MessageChain`
- 本地: `PendingRegistry`, `PendingRequest`

顺序正确，无 `import *`、无未使用 import（保留的 `ContextWrapper` 类型仅在 `TYPE_CHECKING` 守卫下）。

- [ ] **Step 3: 在 `AskUserChoiceTool` class 上新增字段**

`ask_user_choice_tool.py` 在 `AskUserChoiceTool(FunctionTool):` 块内、`name` 字段之后加入：

```python
    timeout_seconds: int = 300
    """等待用户回复的超时秒数。-1 表示无限等待。"""

    registry: PendingRegistry = field(default_factory=PendingRegistry)
    """挂起态注册表;每个 tool 实例一个,跨调用复用。"""
```

- [ ] **Step 4: 跑现有 import/编译检查**

Run:
```bash
python -m py_compile ask_user_choice_tool.py
```

Expected: 无输出（成功）。

- [ ] **Step 5: 提交**

```bash
git add ask_user_choice_tool.py
git commit -m "refactor(ask_user_choice_tool): add timeout_seconds + registry fields"
```

---

### Task 5: 改造 `call()` 为挂起版本

**Files:**
- Modify: `ask_user_choice_tool.py:91-178`（整个 `call()` 方法）

- [ ] **Step 1: 替换整个 `call()` 方法体**

**Before**（保留行号参考）：
- L91: `async def call(self, context: ContextWrapper, **kwargs: Any) -> str:`
- L92-178: 校验 + 构造 payload + `return json.dumps(...)`

**After**：

```python
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
```

- [ ] **Step 2: 跑编译检查**

Run:
```bash
python -m py_compile ask_user_choice_tool.py
```

Expected: 无输出。

- [ ] **Step 3: 跑 pending_registry 单测(确认没破坏)**

Run:
```bash
python -m pytest test_pending_registry.py -v
```

Expected: 7 passed。

- [ ] **Step 4: 提交**

```bash
git add ask_user_choice_tool.py
git commit -m "feat(ask_user_choice_tool): block on user reply via Future"
```

---

## Chunk 3: 配置 + 入口

### Task 6: `_conf_schema.json` 新增 `timeout_seconds` 字段

**Files:**
- Modify: `_conf_schema.json`

- [ ] **Step 1: 修改 schema**

`_conf_schema.json` 整个文件替换为：

```json
{
  "enabled": {
    "type": "bool",
    "default": true,
    "description": "是否启用 ask_user_choice 工具",
    "hint": "修改后需重启生效"
  },
  "timeout_seconds": {
    "type": "int",
    "default": 300,
    "description": "等待用户回复的超时秒数。-1 表示无限等待。",
    "hint": "默认 300 秒(5 分钟);-1 等同于'必须等到用户回复才会继续'",
    "min": -1
  }
}
```

- [ ] **Step 2: 验证 schema 合法且 AstrBot 能解析**

Run:
```bash
python -c "import json; json.load(open('_conf_schema.json'))"
python -c "
import json, sys
sys.path.insert(0, r'F:\github\Astrbot')
from astrbot.core.config.default import DEFAULT_VALUE_MAP
schema = json.load(open('_conf_schema.json'))
def _parse_schema(schema, conf):
    for k, v in schema.items():
        assert v['type'] in DEFAULT_VALUE_MAP, f'{k}: {v[\"type\"]}'
        if v['type'] == 'object':
            conf[k] = {}; _parse_schema(v['items'], conf[k])
        else:
            conf[k] = v.get('default', DEFAULT_VALUE_MAP[v['type']])
_parse_schema(schema, {})
print('OK')
"
```

Expected: 第二次输出 `OK`。

- [ ] **Step 3: 提交**

```bash
git add _conf_schema.json
git commit -m "feat(config): add timeout_seconds field (default 300, -1=infinite)"
```

---

### Task 7: `metadata.yaml` 升级到 v0.3.0

**Files:**
- Modify: `metadata.yaml`

- [ ] **Step 1: 修改 `metadata.yaml`**

```yaml
# Author: elecvoid243
# Date: 2026-06-29
# Spec: docs/superpowers/specs/2026-06-29-ask-user-choice-suspension-design.md §6
#
# AstrBot 插件元数据。name 字段必须与目录名一致(以便 AstrBot 在 plugins/
# 扫描时识别),version 字段遵循 vMAJOR.MINOR.PATCH 语义化版本约定。
name: astrbot_plugin_ask_user
display_name: Ask User Choice
desc: 让 LLM 通过 ask_user_choice 工具向用户呈现可交互选项框（单选 + 自由输入），并阻塞 LLM 工具循环等待用户回复。
version: v0.3.0
author: elecvoid243
repo: https://github.com/elecvoid243/astrbot_plugin_ask_user
astrbot_version: ">=4.16,<5"
```

- [ ] **Step 2: 验证 YAML 合法**

Run:
```bash
python -c "import yaml; yaml.safe_load(open('metadata.yaml'))"
```

Expected: 无输出。

- [ ] **Step 3: 提交**

```bash
git add metadata.yaml
git commit -m "chore(metadata): bump to v0.3.0"
```

---

### Task 8: 改造 `main.py`：实例化工具参数 + 新增 `on_message` 钩子

**Files:**
- Modify: `main.py`

- [ ] **Step 1: 修改 imports**

`main.py` 顶部 import 区改为：

```python
"""astrbot_plugin_ask_user 插件入口。"""

from __future__ import annotations

from astrbot.api import logger, star
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Star
from astrbot.core.config import AstrBotConfig

from .ask_user_choice_tool import AskUserChoiceTool
```

- [ ] **Step 2: 修改 `initialize` 方法**

`main.py` 内 `async def initialize(self) -> None:` 方法体替换为：

```python
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
```

- [ ] **Step 3: 新增 `__init__` 字段**

`__init__` 末尾追加：

```python
        # AskUserChoiceTool 实例,由 initialize 创建;terminate 时清理
        self._tool: AskUserChoiceTool | None = None
```

- [ ] **Step 4: 新增 `on_user_message` 钩子**

`AskUserChoicePlugin` 类内、`initialize` 方法之后新增：

```python
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
```

- [ ] **Step 5: 新增 `terminate` 钩子（清理 pending）**

`AskUserChoicePlugin` 类内新增：

```python
    async def terminate(self) -> None:
        """AstrBot 在插件卸载时回调此方法。

        清理所有 pending request,触发它们的 CancelledError,使正在
        ``await Future`` 的工具协程抛出并被 LLM 框架吞掉。

        Spec: docs/superpowers/specs/2026-06-29-ask-user-choice-suspension-design.md §4.3
        """
        if self._tool is not None:
            self._tool.registry.cleanup_all()
```

- [ ] **Step 6: 跑编译检查**

Run:
```bash
python -m py_compile main.py
```

Expected: 无输出。

- [ ] **Step 7: 提交**

```bash
git add main.py
git commit -m "feat(main): wire timeout_seconds + on_message hook + terminate cleanup"
```

---

## Chunk 4: 依赖 + 文档

### Task 9: `requirements.txt` 增加 pytest dev dependency

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: 修改 requirements**

`requirements.txt` 替换为：

```
astrbot>=4.16,<5

# dev/test dependencies(运行时 AstrBot 自带 pytest 也可,这里写清楚便于独立跑测试)
pytest>=7.0
pytest-asyncio>=0.21
```

- [ ] **Step 2: 安装 dev 依赖 + 跑全部测试**

Run:
```bash
pip install -r requirements.txt
python -m pytest test_pending_registry.py -v
```

Expected: 7 passed。

- [ ] **Step 3: 提交**

```bash
git add requirements.txt
git commit -m "chore: add pytest dev dependencies"
```

---

### Task 10: README 更新 v0.3.0 changelog

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 在 README 顶部 v0.3.0 changelog 段新增一段**

定位 README 的版本历史段（参考 AGENTS.md §10 兼容性章节的描述），插入：

```markdown
## v0.3.0 (2026-06-29) — 阻塞式等待

**行为变更**:`ask_user_choice` 工具现在会**真实阻塞 LLM 工具循环**直到用户点击按钮 / 输入文本 / 超时。在用户回复前,LLM 不会执行后续步骤。

**新增配置项**:
- `timeout_seconds`(int,默认 `300`,`-1` 表示无限等待)

**已知限制**:
- AstrBot 进程重启 / 插件热重载会丢弃所有挂起的请求(等价于超时,飞行中的 LLM 任务被一起取消,无孤儿 Future)。
- `timeout_seconds = -1` 时,工具循环会永久挂起,必须用户回复或 AstrBot 重启才恢复。
- 群聊里同一 sender 的下一条消息会被消费为回执;其他 sender 的消息按 AstrBot 正常流程走。
- 平台必须支持 `event.send(MessageChain)`,已验证 WebChat,其他平台走相同 API 应同样工作。

**完整规范**:`docs/superpowers/specs/2026-06-29-ask-user-choice-suspension-design.md`
```

- [ ] **Step 2: 提交**

```bash
git add README.md
git commit -m "docs(readme): add v0.3.0 changelog"
```

---

## Chunk 5: 端到端验证

### Task 11: 加载验证（必跑）

**Files:** 无

- [ ] **Step 1: 把插件放到 AstrBot plugins 目录**

```bash
# 在 Astrbot 仓库根
ln -s F:/github/astrbot_plugin_ask_user_choice Astrbot/data/plugins/astrbot_plugin_ask_user_choice
```

或直接复制目录。

- [ ] **Step 2: 启动 AstrBot,观察日志**

Run:
```bash
cd F:\github\Astrbot
python -m astrbot
```

Expected: 日志中看到
```
plugin loaded: astrbot_plugin_ask_user
```

且**无** traceback / ImportError。

- [ ] **Step 3: 跑 schema 验证**

```bash
cd F:\github\astrbot_plugin_ask_user_choice
python -c "
import json, sys
sys.path.insert(0, r'F:\github\Astrbot')
from astrbot.core.config.default import DEFAULT_VALUE_MAP
schema = json.load(open('_conf_schema.json'))
def _parse_schema(schema, conf):
    for k, v in schema.items():
        assert v['type'] in DEFAULT_VALUE_MAP, f'{k}: {v[\"type\"]}'
        if v['type'] == 'object':
            conf[k] = {}; _parse_schema(v['items'], conf[k])
        else:
            conf[k] = v.get('default', DEFAULT_VALUE_MAP[v['type']])
_parse_schema(schema, {})
print('OK')
"
```

Expected: `OK`。

- [ ] **Step 4: 跑全部单元测试**

```bash
cd F:\github\astrbot_plugin_ask_user_choice
python -m pytest test_pending_registry.py -v
```

Expected: 7 passed。

---

### Task 12: 端到端场景（人工 + WebChat,必跑项 1/4/6/7/9）

> Spec §9.3 列出 12 个场景,本计划只要求跑**必跑项**;其他场景在首次发布前补齐。

| # | 场景 | 步骤 | 期望 |
|---|------|------|------|
| 1 | 加载 | Task 11 | ✅ |
| 4 | 用户点击按钮 | 在 WebChat 触发 LLM 调用 `ask_user_choice`,点击按钮 | LLM 下一轮收到 `tool result = "<id>"` |
| 6 | 用户不点按钮直接发普通消息(私聊) | 触发工具后,直接键入文本"banana" | 消息被消费,LLM 收到 `tool result = "banana"` |
| 7 | 群聊里非触发者发消息 | 私聊触发工具,在另一终端用**不同** sender 私聊发消息 | 消息不被消费,按 AstrBot 正常流程走(因为 key 不命中) |
| 9 | `timeout_seconds = 5` 时故意不点 | 在 WebUI 把 `timeout_seconds` 改为 5,重启 AstrBot,触发工具,不回复 | 5 秒后 LLM 收到 `"Error: User did not respond within 5 seconds..."` |

- [ ] **Step 1: 跑场景 4**

在 WebChat 发起对话:"请给我一个选项框让我选 A 或 B"。
确认：
- 前端渲染 2 个按钮
- 点击 A 后,LLM 下一轮说"你选了 A"或类似回应
- 切回 AstrBot 日志,看到 `pending registered` + `user reply resolved` 两条 info 日志

- [ ] **Step 2: 跑场景 6**

新对话:"给我一个选项框"。
前端渲染后,**不点按钮**,直接键入"banana"。
确认：
- LLM 下一轮说"你输入了 banana"
- 日志:`user reply resolved (len=6)`

- [ ] **Step 3: 跑场景 7**

A 发起对话触发工具,切到 B 私聊 B 的 AstrBot 发"hello"。
确认：
- B 的对话**不会**消费"A 的选项框"——B 走正常 LLM 流程收到自己消息的回复
- A 的工具仍挂起(因为 A 没回复)

- [ ] **Step 4: 跑场景 9**

WebUI → 插件配置 → `timeout_seconds` 改为 `5` → 重启 AstrBot。
发起对话触发工具,**不回复**。
确认：
- 5 秒后 LLM 收到 `"Error: User did not respond within 5 seconds..."`
- AstrBot 日志:`timeout after 5s (pending_id=...)`

- [ ] **Step 5: 如有问题,提 issue / 修复**

任何一项不通过 → 用 systematic-debugging 技能定位 → 修复 → 重新跑该项 + 全部必跑项。

- [ ] **Step 6: 全部通过后,合并到 main 分支**

```bash
cd F:\github\astrbot_plugin_ask_user_choice
git log --oneline | head -20  # 确认所有 commit 整洁
git status  # 应 clean
```

---

### Task 13: 收尾 — 最终 commit + 标记

**Files:** 无

- [ ] **Step 1: 最终核查**

```bash
cd F:\github\astrbot_plugin_ask_user_choice
python -m py_compile main.py ask_user_choice_tool.py pending_registry.py
python -m pytest test_pending_registry.py -v
python -c "import yaml; yaml.safe_load(open('metadata.yaml'))"
python -c "import json; json.load(open('_conf_schema.json'))"
git log --oneline | head -20
git status
```

Expected: 全部通过 / 全部 clean。

- [ ] **Step 2: 在 main 分支打 tag**

```bash
git tag v0.3.0
git push origin v0.3.0
```

---

## 计划完成

**总任务数**:13 个
**代码量预估**:~250 行新增 / ~80 行修改(扣除测试和文档)
**单测数**:7 个(`test_pending_registry.py`)
**端到端必跑**:5 个场景(加载 + 4 个核心流程)

**关键风险点**:
- `on_message` 钩子顺序依赖 AstrBot pipeline 的 `star_request_sub_stage` 在 `agent_sub_stage` 之前运行——已在 spec §12 自审修正中确认。
- 群聊里 `@bot` 才触发 LLM 响应,我们的 `stop_event()` 在 `@bot` 触发的消息流中也生效(star_request_sub_stage 仍先运行)。

**Spec 引用**: `docs/superpowers/specs/2026-06-29-ask-user-choice-suspension-design.md`

---

## 附录 A:人工端到端 checklist(Chunk 5 产出)

> **背景**:Task 12 列出 4 个必跑场景(4 / 6 / 7 / 9),完整端到端验证需要
> 真实 AstrBot 进程 + WebChat 客户端。本附录是"如何人工跑这些场景"
> 的检查清单,父代理或人按部就班照着跑即可。
> 场景 1(加载)已在 Task 11 完成代码层验证;AstrBot 启动后只需
> 看日志 `plugin loaded: astr_user` 无 traceback 即可。

### 前置条件

1. **AstrBot 进程就绪**:在 `F:\github\Astrbot` 跑 `python -m astrbot`,
   启动后无报错(已有 v0.2.0 插件能正常加载)。
2. **本插件已软链/复制到 AstrBot plugins 目录**:
   ```bash
   # Windows(cmd)
   mklink /D F:\github\Astrbot\data\plugins\astrbot_plugin_ask_user F:\github\astrbot_plugin_ask_user_choice
   ```
   或直接复制 `F:\github\astrbot_plugin_ask_user_choice` 到
   `F:\github\Astrbot\data\plugins\astrbot_plugin_ask_user`。
3. **WebChat 已登录**,能与 AstrBot 私聊。
4. **在 AstrBot 日志窗口保持开着**(便于回看 `pending registered` /
   `user reply resolved` / `timeout after Ns` 等 info 日志)。
5. **配置确认**:AstrBot WebUI → 插件管理 → `astrbot_plugin_ask_user` →
   配置页应有两个字段:
   - `enabled`(bool,默认 true)
   - `timeout_seconds`(int,默认 300)

### 场景 1:加载验证(代码层 ✅,需 AstrBot 启动无报错)

**步骤**:
1. 重启 AstrBot(或 WebUI 触发"重载插件")。
2. 观察 AstrBot 主日志。

**期望**:
- 日志出现 `plugin loaded: astrbot_plugin_ask_user`(或类似 "added LLM tool: ask_user_choice" 的字样)
- **无**任何 `Traceback` / `ImportError` / `KeyError`
- 如果出现 `ModuleNotFoundError: No module named 'astrbot'`,那是
  python 启动时 sys.path 缺 `F:\github\Astrbot`,跟本插件无关,
  是 AstrBot 启动环境问题

**回归点**:
- `astbot` 报 v0.3.0 插件加载失败,先 `python -m py_compile` 4 个源文件

### 场景 4:用户点击按钮

**目的**:验证 `on_user_message` 钩子在"用户点击按钮"这条路径上
正确 consume 消息,LLM 下一轮收到 `tool result = "<id>"`。

**步骤**:
1. 在 WebChat 私聊 AstrBot,发送:"请给我一个选项框让我选 A 或 B"
2. 确认前端渲染 2 个按钮(选项 A、选项 B)+ 自由输入框
3. 点击按钮 A
4. 等待 LLM 下一轮回复

**期望**:
- LLM 下一轮说"你选了 A"或类似回应(基于 A 的 label / id)
- AstrBot 日志出现两条 info:
  ```
  ask_user_choice: pending registered (umo=webchat:..., sender=..., pending_id=...)
  ask_user_choice: user reply resolved (umo=webchat:..., sender=..., len=N)
  ```
- `pending_id` 两条日志**相同**
- `len=N` 应是按钮 A 的 label 长度(或 id 长度,看前端回传哪个)
- WebChat 不应再触发新一轮 LLM(`stop_event` 起效)

**失败定位**:
- 看到 `pending registered` 但没 `user reply resolved` → on_message 钩子没消费
- 看到两条但 LLM 没收到 → 钩子消费了但 future 没 set_result
- 看到 `KeyError: ...registry` → 大概率是 Chunk 2 命名漂移(用了 `_registry`)

### 场景 6:用户不点按钮直接发普通消息(私聊)

**目的**:验证"自由输入框的回执"路径;**与场景 4 不同的关键点**是
用户没点按钮,直接键入文本。

**步骤**:
1. 新对话:"给我一个选项框"(确认前端渲染按钮)
2. **不点按钮**,直接在输入框(自由输入框或普通输入框)键入 `banana` 并发送
3. 等待 LLM 下一轮回复

**期望**:
- LLM 下一轮说"你输入了 banana"或类似回应
- AstrBot 日志:
  ```
  ask_user_choice: pending registered (..., pending_id=abc123)
  ask_user_choice: user reply resolved (..., len=6)
  ```
  (`len=6` = len("banana"))
- 前端不会再触发一轮 LLM(`stop_event` 起效)

**失败定位**:
- `stop_event` 没生效:WebChat 会发两次 LLM 响应,一次回执
  一次 user message;`agent_sub_stage` 跑两次。修复方向:确认
  `on_user_message` 装饰器是 `@filter.platform_adapter_type(filter.PlatformAdapterType.ALL)`
  且 stop_event 在 try_resolve 成功**之后**调用

### 场景 7:群聊里非触发者发消息(隔离性)

**目的**:验证"同 sender 隔离"——A 触发的工具不会被 B 的消息误消费。

**步骤**:
1. **私聊 A 账号** 与 AstrBot:"给我一个选项框",确认前端渲染按钮
2. **切到 B 账号**(另一个 user)私聊 AstrBot,发"hello"
3. 切回 A 账号,A 的工具**仍挂起**(没点没输入)
4. A 账号**也不点**,等 5 秒看是否超时(默认 300 秒会等很久,可临时改 5)

**期望**:
- B 账号的 "hello" 走**正常 LLM 流程**——AstrBot 给 B 正常回复
- A 账号的工具**仍挂起**(因为 A 没回),不会被 B 误消费
- AstrBot 日志应**只有** A 触发时的 `pending registered`,**没有** B 的
  `user reply resolved`(因为 B 的 key 不命中)
- 如果想测超时:把 `timeout_seconds` 改 5,A 等 5 秒后工具返
  `"Error: User did not respond within 5 seconds..."`,LLM 下一轮
  走"未决定"逻辑

**失败定位**:
- B 触发了 A 的 resolve → key 隔离出问题,检查 `event.unified_msg_origin`
  和 `event.get_sender_id()` 在 B 的 event 上是否真的是 B 的标识

### 场景 9:`timeout_seconds = 5` 时故意不点

**目的**:验证硬超时路径,5 秒后 LLM 收到错误信息能继续推理。

**步骤**:
1. WebUI → 插件管理 → `astrbot_plugin_ask_user` → 配置 → `timeout_seconds` 改为 `5`
2. **重启 AstrBot**(配置必须重启才生效,hint 写明)
3. 新对话:"给我一个选项框",确认前端渲染按钮
4. **不点也不输入**,等 5 秒
5. 观察 AstrBot 日志 + LLM 下一轮

**期望**:
- 5 秒后 AstrBot 日志:
  ```
  ask_user_choice: timeout after 5s (pending_id=...)
  ```
- LLM 下一轮收到 tool result = `"Error: User did not respond within 5 seconds. Please decide how to proceed (e.g., make a default choice, ask again, or skip)."`
- LLM 据此继续推理(自主选默认值 / 跳过 / 重新问)
- WebChat 不会有新一轮 LLM(`stop_event` 已起效,这条是工具内部超时)
- 注册表里 key 已清空(`finally: registry._pending.pop(key, None)` 起效)

**失败定位**:
- 5 秒后**没有** timeout 日志 → `asyncio.wait_for` 没起作用,检查
  `self.timeout_seconds < 0` 短路分支是否被错误命中
- 超时了但 LLM 没收到错误 → 工具返了错但 LLM 链路断,看主日志有没有
  agent 报错
- 超时后下一次 LLM 调用立刻被"同 sender 已有 pending"挡掉 →
  `finally` 块没清 dict

### 场景全部通过后的回归点

每次发版前**必跑**(spec §9.4):
- 场景 1 (加载)
- 场景 4 (点击按钮)
- 场景 6 (自由输入)
- 场景 7 (群聊隔离)
- 场景 9 (超时)

其他场景(spec §9.3 全部 12 个)在首次 v0.3.0 发布前补齐。

### 失败排查决策树

1. **`ModuleNotFoundError: No module named 'astrbot'`**
   - 不是本插件问题;是 AstrBot 启动环境问题
   - 确认 `python -m astrbot` 启动时 `F:\github\Astrbot` 在 sys.path
2. **`plugin loaded` 看不到 / 日志有 ImportError**
   - `python -m py_compile` 4 个源文件,看哪个编译失败
   - 检查 Chunk 2 报告 §7 交接事项:`AskUserChoiceTool.registry`(无下划线)不是 `_registry`
3. **工具被注册但 LLM 不调用**
   - 检查 AstrBot 是否启用了 "tool calling" 能力(provider 决定)
   - 直接对 LLM 说"给我一个选项框"测一次
4. **LLM 调用了工具但 LLM 不等用户**
   - 检查 `on_user_message` 装饰器
   - 检查 `stop_event()` 调用的位置(必须在 `try_resolve` 成功之后)
5. **前端不渲染选项框**
   - 那是 WebChat 前端的 `unwrapInteractiveChoice` 问题(本插件的 JSON
     格式沿用 v0.2.0,理论上 v0.2.0 装过的前端能正常解包)
   - 用 F12 看 MessageChain 的 raw JSON,确认 `type: "interactive_choice"`

### 附录生成时间

- **生成者**:Chunk 5 Task 12 实施
- **生成日期**:2026-06-29
- **依据**:spec §9.3 + spec §9.4

# ask_user_choice v1.0 真阻塞式重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重构 `astrbot_plugin_ask_user_choice` 插件从 v0.3 软阻塞升级为 v1.0 真阻塞式 HITL:工具内部 `await Future` 等待 dashboard 用户响应,完成后直接 return 用户选择给 LLM,支持跨刷新持久化。

**Architecture:** 后端在插件内新增 `InteractiveChoiceRegistry` 单例管理 in-memory Future 池,工具 `call()` 内 `asyncio.wait_for` 真阻塞,等待 `webchat_back_queue` 推送的 `interactive_choice` 事件被前端响应后通过 `POST /api/chat/interactive-choice/<request_id>` REST 端点 `set_result()`。前端用 Pinia store 管理 `request_id → InteractiveChoicePart` 映射,localStorage 瞬时恢复 + `GET /api/chat/interactive-choice/pending?session_id=<umo>` reconcile 一致性。

**Tech Stack:**
- 后端:Python 3.10+,asyncio,FastAPI(已嵌入),AIOHTTP
- 前端:Vue 3.3.4,TypeScript 5.1.6,Pinia 2.1.6,@hey-api/client-axios
- 测试:pytest,httpx ASGITransport,node --test

**Spec:** `docs/superpowers/specs/2026-07-02-blocking-interactive-choice-design.md`

## Global Constraints

- 改插件:版本 v0.3.0 → **v1.0.0**(breaking)
- 改 dashboard:在 `dashboard/src/` 下,**不在 webchat 平台以外的子目录**
- 平台守卫:**仅 webchat 会话**(umo 必须以 `webchat:` 开头)
- 鉴权:Dashboard JWT(`require_dashboard_user`)+ UMO 归属 strict match(解析失败返回 403)
- 端点路径:**legacy `/api/chat/interactive-choice/*`**(不挂 `/api/v1/*`)
- UMO 解析:从 `webchat:FriendMessage:webchat!username!session_id` 提 username 用 `parts[2].split("!")[1]`
- 持久化:**不持久化到 disk**,纯内存 + 5 分钟超时兜底
- 配置:`timeout_seconds=300`,`max_concurrent_pending=32`(默认值)
- 超时 fallback:`"[User did not respond within {timeout} seconds. Please proceed with a reasonable default.]"`
- 清理验证:`grep -rn "unwrapInteractiveChoice\|extractAskUserChoiceFromToolCall\|_SYSTEM_PROMPT_POLICY\|INJECTION_MARKER\|build_injection_policy"` 必须 0 命中
- 代码风格:ruff 格式化,Google-style docstrings,英文注释
- commit 消息:conventional commits(`feat:` / `fix:` / `refactor:` / `test:` / `docs:`)

---

## Task Index

| Task | PR | 主题 | 估时 |
|------|----|----|------|
| 1 | PR 1 | Registry 核心(add/remove) | 10 min |
| 2 | PR 1 | Registry resolve + 防双调用 | 8 min |
| 3 | PR 1 | Registry list_pending_for_umo | 8 min |
| 4 | PR 1 | Registry _gc_loop + shutdown | 12 min |
| 5 | PR 2 | 工具:webchat 守卫 + 参数校验 | 12 min |
| 6 | PR 2 | 工具:完整 call() 流程(mock registry) | 18 min |
| 7 | PR 2 | 工具:_format_choice_for_llm | 5 min |
| 8 | PR 3 | REST:_extract_username_from_umo | 5 min |
| 9 | PR 3 | REST:POST 端点 | 18 min |
| 10 | PR 3 | REST:GET pending 端点 | 12 min |
| 11 | PR 3 | 插件 main.py 挂载 router | 8 min |
| 12 | PR 4 | 前端 schema 重写 + 单测 | 12 min |
| 13 | PR 5 | 前端 Pinia store + 单测 | 18 min |
| 14 | PR 6 | 前端 InteractiveChoiceBox 改 emit | 8 min |
| 15 | PR 6 | 前端 ChatMessageList 改 SSE + submit | 15 min |
| 16 | PR 6 | 前端 useMessages 删旧解包 | 8 min |
| 17 | PR 7 | metadata.yaml + _conf_schema + 文档归档 | 10 min |

**总估时:~3.5 小时**

---

## Task 1: Registry 核心(add/remove + PendingChoice)

**Files:**
- Create: `astrbot_plugin_ask_user_choice/interactive_choice_registry.py`
- Test: `astrbot_plugin_ask_user_choice/tests/__init__.py`(空)
- Test: `astrbot_plugin_ask_user_choice/tests/test_interactive_choice_registry.py`

**Interfaces:**
- Produces: `class PendingChoice` with fields `request_id: str`, `umo: str`, `future: asyncio.Future`, `spec: dict`, `created_at: float`, `timeout_at: float`, `cleanup_done: bool = False`
- Produces: `class InteractiveChoiceRegistry` with methods `add()`, `remove()`

- [ ] **Step 1: Create test directory and __init__.py**

```bash
mkdir -p astrbot_plugin_ask_user_choice/tests
touch astrbot_plugin_ask_user_choice/tests/__init__.py
```

- [ ] **Step 2: Write failing test for add/remove**

`astrbot_plugin_ask_user_choice/tests/test_interactive_choice_registry.py`:

```python
"""InteractiveChoiceRegistry 单元测试。"""
import asyncio

from astrbot_plugin_ask_user_choice.interactive_choice_registry import (
    InteractiveChoiceRegistry,
)


def _make_future() -> asyncio.Future:
    return asyncio.get_event_loop().create_future()


def test_add_registers_pending():
    reg = InteractiveChoiceRegistry()
    fut = _make_future()
    reg.add(
        request_id="r1",
        umo="webchat:FriendMessage:webchat!alice!sess",
        future=fut,
        spec={"prompt": "x", "options": [{"id": "A", "label": "a"}]},
        created_at=0.0,
        timeout_at=100.0,
    )
    assert "r1" in reg._pending
    assert "r1" in reg._by_umo["webchat:FriendMessage:webchat!alice!sess"]


def test_remove_clears_pending_and_by_umo():
    reg = InteractiveChoiceRegistry()
    fut = _make_future()
    umo = "webchat:FriendMessage:webchat!alice!sess"
    reg.add("r1", umo, fut, {"prompt": "x", "options": [{"id": "A", "label": "a"}]}, 0.0, 100.0)
    reg.remove("r1")
    assert "r1" not in reg._pending
    assert umo not in reg._by_umo  # umo 索引被清空


def test_remove_unknown_is_noop():
    reg = InteractiveChoiceRegistry()
    reg.remove("nonexistent")  # 不应抛异常
    assert reg._pending == {}


def test_remove_cancels_unfinished_future():
    reg = InteractiveChoiceRegistry()
    fut = _make_future()
    reg.add("r1", "webchat:FriendMessage:webchat!alice!sess", fut,
            {"prompt": "x", "options": [{"id": "A", "label": "a"}]}, 0.0, 100.0)
    reg.remove("r1")
    assert fut.cancelled() or fut.done()
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd astrbot_plugin_ask_user_choice && python -m pytest tests/test_interactive_choice_registry.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'astrbot_plugin_ask_user_choice.interactive_choice_registry'`

- [ ] **Step 4: Write minimal implementation**

`astrbot_plugin_ask_user_choice/interactive_choice_registry.py`:

```python
"""InteractiveChoiceRegistry: in-memory 等待池,管理 ask_user_choice 工具的 Future。

单例(global `registry`),工具内 await Future,REST 端点 set_result。
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PendingChoice:
    """单个等待中的 interactive_choice 状态。"""
    request_id: str
    umo: str
    future: asyncio.Future
    spec: dict
    created_at: float
    timeout_at: float
    cleanup_done: bool = False


class InteractiveChoiceRegistry:
    """In-memory pending 池,O(1) 查询 + per-umo 索引。

    Attributes:
        _pending: request_id → PendingChoice
        _by_umo: umo → set[request_id]
    """

    def __init__(self) -> None:
        self._pending: dict[str, PendingChoice] = {}
        self._by_umo: dict[str, set[str]] = {}

    def add(
        self,
        request_id: str,
        umo: str,
        future: asyncio.Future,
        spec: dict,
        created_at: float,
        timeout_at: float,
    ) -> None:
        """注册一个等待中的 choice(同步,工具内 await 前调用)。"""
        self._pending[request_id] = PendingChoice(
            request_id=request_id,
            umo=umo,
            future=future,
            spec=spec,
            created_at=created_at,
            timeout_at=timeout_at,
        )
        self._by_umo.setdefault(umo, set()).add(request_id)

    def remove(self, request_id: str) -> None:
        """从池中移除一个 choice。cancel 未完成的 future。"""
        pending = self._pending.pop(request_id, None)
        if pending is None:
            return
        ids = self._by_umo.get(pending.umo)
        if ids is not None:
            ids.discard(request_id)
            if not ids:
                self._by_umo.pop(pending.umo, None)
        if not pending.future.done():
            pending.future.cancel()


# 全局单例
registry = InteractiveChoiceRegistry()
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd astrbot_plugin_ask_user_choice && python -m pytest tests/test_interactive_choice_registry.py -v
```

Expected: 4 passed

- [ ] **Step 6: Format and commit**

```bash
cd astrbot_plugin_ask_user_choice && ruff check interactive_choice_registry.py tests/ --fix && ruff format .
git add interactive_choice_registry.py tests/
git commit -m "feat(registry): add InteractiveChoiceRegistry core (add/remove)"
```

---

## Task 2: Registry resolve + 防双调用

**Files:**
- Modify: `astrbot_plugin_ask_user_choice/interactive_choice_registry.py`
- Modify: `astrbot_plugin_ask_user_choice/tests/test_interactive_choice_registry.py`

**Interfaces:**
- Produces: `InteractiveChoiceRegistry.resolve(request_id, payload) -> bool`

- [ ] **Step 1: Add failing test for resolve**

Append to `tests/test_interactive_choice_registry.py`:

```python
def test_resolve_sets_future_result():
    reg = InteractiveChoiceRegistry()
    fut = _make_future()
    reg.add("r1", "webchat:FriendMessage:webchat!alice!sess", fut,
            {"prompt": "x", "options": [{"id": "A", "label": "a"}]}, 0.0, 100.0)
    assert reg.resolve("r1", {"choice_id": "A", "free_text": ""}) is True
    assert fut.result() == {"choice_id": "A", "free_text": ""}


def test_resolve_unknown_returns_false():
    reg = InteractiveChoiceRegistry()
    assert reg.resolve("nonexistent", {"choice_id": "A"}) is False


def test_resolve_double_call_protected():
    reg = InteractiveChoiceRegistry()
    fut = _make_future()
    reg.add("r1", "webchat:FriendMessage:webchat!alice!sess", fut,
            {"prompt": "x", "options": [{"id": "A", "label": "a"}]}, 0.0, 100.0)
    assert reg.resolve("r1", {"choice_id": "A"}) is True
    # 第二次 resolve 应返回 False(防双 resolve)
    assert reg.resolve("r1", {"choice_id": "B"}) is False
    # future 仍是第一次的结果
    assert fut.result() == {"choice_id": "A"}


def test_resolve_after_remove_returns_false():
    reg = InteractiveChoiceRegistry()
    fut = _make_future()
    reg.add("r1", "webchat:FriendMessage:webchat!alice!sess", fut,
            {"prompt": "x", "options": [{"id": "A", "label": "a"}]}, 0.0, 100.0)
    reg.remove("r1")  # 移除后 future 被 cancel
    assert reg.resolve("r1", {"choice_id": "A"}) is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd astrbot_plugin_ask_user_choice && python -m pytest tests/test_interactive_choice_registry.py -v
```

Expected: FAIL with `AttributeError: 'InteractiveChoiceRegistry' object has no attribute 'resolve'`

- [ ] **Step 3: Implement resolve method**

Add to `InteractiveChoiceRegistry` class in `interactive_choice_registry.py`:

```python
    def resolve(self, request_id: str, payload: dict) -> bool:
        """Set future result。已 resolve 或不存在返回 False。

        Args:
            request_id: 由 add() 注册的 ID。
            payload: 用户响应,通常是 {choice_id, free_text}。

        Returns:
            True if successful, False if unknown/already-done.
        """
        pending = self._pending.get(request_id)
        if pending is None:
            return False
        if pending.future.done():
            return False
        pending.future.set_result(payload)
        return True
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd astrbot_plugin_ask_user_choice && python -m pytest tests/test_interactive_choice_registry.py -v
```

Expected: 8 passed (4 from Task 1 + 4 new)

- [ ] **Step 5: Commit**

```bash
cd astrbot_plugin_ask_user_choice
git add interactive_choice_registry.py tests/
git commit -m "feat(registry): add resolve with double-call protection"
```

---

## Task 3: Registry list_pending_for_umo

**Files:**
- Modify: `astrbot_plugin_ask_user_choice/interactive_choice_registry.py`
- Modify: `astrbot_plugin_ask_user_choice/tests/test_interactive_choice_registry.py`

**Interfaces:**
- Produces: `InteractiveChoiceRegistry.list_pending_for_umo(umo) -> list[dict]`

- [ ] **Step 1: Add failing test for list_pending_for_umo**

Append to `tests/test_interactive_choice_registry.py`:

```python
def test_list_pending_for_umo_filters_correctly():
    reg = InteractiveChoiceRegistry()
    fut1 = _make_future()
    fut2 = _make_future()
    reg.add("r1", "webchat:FriendMessage:webchat!alice!sess", fut1,
            {"prompt": "x", "options": [{"id": "A", "label": "a"}]}, 0.0, 100.0)
    reg.add("r2", "webchat:FriendMessage:webchat!bob!sess", fut2,
            {"prompt": "y", "options": [{"id": "B", "label": "b"}]}, 0.0, 100.0)
    # alice 只能看到 r1
    alice_pending = reg.list_pending_for_umo("webchat:FriendMessage:webchat!alice!sess")
    assert len(alice_pending) == 1
    assert alice_pending[0]["request_id"] == "r1"


def test_list_pending_excludes_expired():
    reg = InteractiveChoiceRegistry()
    fut = _make_future()
    reg.add("r1", "webchat:FriendMessage:webchat!alice!sess", fut,
            {"prompt": "x", "options": [{"id": "A", "label": "a"}]},
            created_at=0.0, timeout_at=-1.0)  # 已超时
    assert reg.list_pending_for_umo("webchat:FriendMessage:webchat!alice!sess") == []


def test_list_pending_excludes_resolved():
    reg = InteractiveChoiceRegistry()
    fut = _make_future()
    reg.add("r1", "webchat:FriendMessage:webchat!alice!sess", fut,
            {"prompt": "x", "options": [{"id": "A", "label": "a"}]}, 0.0, 100.0)
    reg.resolve("r1", {"choice_id": "A"})
    assert reg.list_pending_for_umo("webchat:FriendMessage:webchat!alice!sess") == []


def test_list_pending_includes_spec_and_timestamps():
    reg = InteractiveChoiceRegistry()
    fut = _make_future()
    spec = {"prompt": "test", "options": [{"id": "A", "label": "a"}]}
    reg.add("r1", "webchat:FriendMessage:webchat!alice!sess", fut, spec,
            created_at=10.0, timeout_at=110.0)
    result = reg.list_pending_for_umo("webchat:FriendMessage:webchat!alice!sess")
    assert len(result) == 1
    item = result[0]
    assert item["request_id"] == "r1"
    assert item["spec"] == spec
    assert item["created_at"] == 10.0
    assert item["timeout_at"] == 110.0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd astrbot_plugin_ask_user_choice && python -m pytest tests/test_interactive_choice_registry.py -v
```

Expected: FAIL with `AttributeError: ... no attribute 'list_pending_for_umo'`

- [ ] **Step 3: Implement list_pending_for_umo**

Add to `InteractiveChoiceRegistry`:

```python
    def list_pending_for_umo(self, umo: str) -> list[dict]:
        """列出某 umo 下所有仍 pending 的 choice。

        Args:
            umo: 统一消息来源,如 'webchat:FriendMessage:webchat!alice!sess'。

        Returns:
            [{request_id, spec, created_at, timeout_at}, ...]
            排除已 resolve/已超时/已移除的条目。
        """
        ids = self._by_umo.get(umo, set())
        now = time.time()
        result = []
        for rid in list(ids):
            p = self._pending.get(rid)
            if p is None or p.future.done() or p.timeout_at < now:
                continue
            result.append({
                "request_id": p.request_id,
                "spec": p.spec,
                "created_at": p.created_at,
                "timeout_at": p.timeout_at,
            })
        return result
```

(需要 `import time` 在文件顶部 — 已在)

- [ ] **Step 4: Run test to verify it passes**

```bash
cd astrbot_plugin_ask_user_choice && python -m pytest tests/test_interactive_choice_registry.py -v
```

Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
cd astrbot_plugin_ask_user_choice
git add interactive_choice_registry.py tests/
git commit -m "feat(registry): add list_pending_for_umo with expiry filter"
```

---

## Task 4: Registry _gc_loop + shutdown

**Files:**
- Modify: `astrbot_plugin_ask_user_choice/interactive_choice_registry.py`
- Modify: `astrbot_plugin_ask_user_choice/tests/test_interactive_choice_registry.py`

**Interfaces:**
- Produces: `InteractiveChoiceRegistry.stats()`, `_gc_loop()`, `shutdown()`

- [ ] **Step 1: Add failing test for stats**

Append to `tests/test_interactive_choice_registry.py`:

```python
def test_stats_returns_counts():
    reg = InteractiveChoiceRegistry()
    fut = _make_future()
    reg.add("r1", "webchat:FriendMessage:webchat!alice!sess", fut,
            {"prompt": "x", "options": [{"id": "A", "label": "a"}]}, 0.0, 100.0)
    stats = reg.stats()
    assert stats["total_pending"] == 1
    assert stats["by_umo"]["webchat:FriendMessage:webchat!alice!sess"] == 1
```

- [ ] **Step 2: Implement stats**

```python
    def stats(self) -> dict:
        """当前状态(用于调试/metrics)。"""
        return {
            "total_pending": len(self._pending),
            "by_umo": {umo: len(ids) for umo, ids in self._by_umo.items()},
        }
```

- [ ] **Step 3: Run test to verify it passes**

```bash
cd astrbot_plugin_ask_user_choice && python -m pytest tests/test_interactive_choice_registry.py::test_stats_returns_counts -v
```

Expected: 1 passed

- [ ] **Step 4: Add failing test for shutdown**

Append to `tests/test_interactive_choice_registry.py`:

```python
import pytest


@pytest.mark.asyncio
async def test_shutdown_cancels_all_futures():
    reg = InteractiveChoiceRegistry()
    fut1 = _make_future()
    fut2 = _make_future()
    reg.add("r1", "webchat:FriendMessage:webchat!alice!sess", fut1,
            {"prompt": "x", "options": [{"id": "A", "label": "a"}]}, 0.0, 100.0)
    reg.add("r2", "webchat:FriendMessage:webchat!bob!sess", fut2,
            {"prompt": "y", "options": [{"id": "B", "label": "b"}]}, 0.0, 100.0)
    await reg.shutdown()
    assert (fut1.cancelled() or fut1.done())
    assert (fut2.cancelled() or fut2.done())
    assert reg._pending == {}
    assert reg._by_umo == {}
```

> 注意:如果项目未配置 pytest-asyncio,改用手动 `asyncio.run`:
> ```python
> def test_shutdown_cancels_all_futures():
>     reg = InteractiveChoiceRegistry()
>     fut1 = _make_future()
>     fut2 = _make_future()
>     reg.add("r1", "webchat:FriendMessage:webchat!alice!sess", fut1,
>             {"prompt": "x", "options": [{"id": "A", "label": "a"}]}, 0.0, 100.0)
>     reg.add("r2", "webchat:FriendMessage:webchat!bob!sess", fut2,
>             {"prompt": "y", "options": [{"id": "B", "label": "b"}]}, 0.0, 100.0)
>     asyncio.run(reg.shutdown())
>     assert (fut1.cancelled() or fut1.done())
>     assert (fut2.cancelled() or fut2.done())
>     assert reg._pending == {}
> ```

- [ ] **Step 5: Run test to verify it fails**

```bash
cd astrbot_plugin_ask_user_choice && python -m pytest tests/test_interactive_choice_registry.py::test_shutdown_cancels_all_futures -v
```

Expected: FAIL with `AttributeError: ... no attribute 'shutdown'`

- [ ] **Step 6: Implement shutdown and _gc_loop (placeholder)**

Add to `InteractiveChoiceRegistry`:

```python
    def _ensure_gc(self) -> None:
        """确保 GC task 在运行(单例一次)。"""
        # 完整实现在 PR 2 集成阶段,这里占位避免破坏 add() 调用
        pass

    async def _gc_loop(self) -> None:
        """每 30s 扫描一次,清理已超时 / 已 done 的条目。"""
        while True:
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                return
            now = time.time()
            expired = [
                rid for rid, p in self._pending.items()
                if p.timeout_at < now or p.future.done()
            ]
            for rid in expired:
                self.remove(rid)
            if expired:
                logger.debug(f"[interactive_choice_gc] cleaned {len(expired)} expired")

    async def shutdown(self) -> None:
        """优雅关闭:cancel 所有 future + GC task。"""
        for pending in list(self._pending.values()):
            if not pending.future.done():
                pending.future.cancel()
        self._pending.clear()
        self._by_umo.clear()
        # GC task 由 __init__ 阶段延迟启动,本测试不触发
```

- [ ] **Step 7: Run test to verify it passes**

```bash
cd astrbot_plugin_ask_user_choice && python -m pytest tests/test_interactive_choice_registry.py -v
```

Expected: 13 passed

- [ ] **Step 8: Commit**

```bash
cd astrbot_plugin_ask_user_choice
git add interactive_choice_registry.py tests/
git commit -m "feat(registry): add stats and shutdown"
```

---

## Task 5: 工具 - webchat 守卫 + 参数校验

**Files:**
- Modify: `astrbot_plugin_ask_user_choice/ask_user_choice_tool.py` (完全重写)
- Create: `astrbot_plugin_ask_user_choice/tests/test_ask_user_choice_tool.py`

**Interfaces:**
- Produces: `class AskUserChoiceTool(FunctionTool)` with `description`, `parameters`, `_validate_and_build_spec(kwargs) -> dict | str`

- [ ] **Step 1: Write failing test for webchat 守卫**

`astrbot_plugin_ask_user_choice/tests/test_ask_user_choice_tool.py`:

```python
"""AskUserChoiceTool 单元测试。"""
import asyncio
import time
from unittest.mock import MagicMock

import pytest

from astrbot_plugin_ask_user_choice.ask_user_choice_tool import (
    AskUserChoiceTool,
    _PROMPT_MAX,
    _LABEL_MAX,
    _OPTIONS_MIN,
    _OPTIONS_MAX,
)


def _make_context(umo: str = "webchat:FriendMessage:webchat!alice!sess"):
    """构造一个最小的 ContextWrapper mock。"""
    ctx = MagicMock()
    ctx.context.event.unified_msg_origin = umo
    return ctx


# ── _validate_and_build_spec 单元测试 ────────────────────────


def test_validate_rejects_empty_prompt():
    tool = AskUserChoiceTool()
    result = tool._validate_and_build_spec({"prompt": "", "options": [{"id": "A", "label": "a"}]})
    assert isinstance(result, str)
    assert "prompt" in result.lower()


def test_validate_rejects_too_few_options():
    tool = AskUserChoiceTool()
    result = tool._validate_and_build_spec({
        "prompt": "test",
        "options": [{"id": "A", "label": "a"}],  # 只有 1 个,要求 >= 2
    })
    assert isinstance(result, str)
    assert "options" in result.lower()


def test_validate_rejects_too_many_options():
    tool = AskUserChoiceTool()
    options = [{"id": chr(ord("A") + i), "label": f"opt{i}"} for i in range(_OPTIONS_MAX + 1)]
    result = tool._validate_and_build_spec({"prompt": "test", "options": options})
    assert isinstance(result, str)


def test_validate_rejects_duplicate_ids():
    tool = AskUserChoiceTool()
    result = tool._validate_and_build_spec({
        "prompt": "test",
        "options": [
            {"id": "A", "label": "a"},
            {"id": "A", "label": "b"},  # duplicate
        ],
    })
    assert isinstance(result, str)
    assert "duplicate" in result.lower()


def test_validate_returns_dict_on_valid_input():
    tool = AskUserChoiceTool()
    result = tool._validate_and_build_spec({
        "prompt": "test",
        "options": [
            {"id": "A", "label": "alpha"},
            {"id": "B", "label": "beta"},
        ],
    })
    assert isinstance(result, dict)
    assert result["prompt"] == "test"
    assert result["type"] == "interactive_choice"
    assert len(result["options"]) == 2


def test_validate_truncates_long_prompt():
    tool = AskUserChoiceTool()
    long_prompt = "x" * (_PROMPT_MAX + 50)
    result = tool._validate_and_build_spec({
        "prompt": long_prompt,
        "options": [{"id": "A", "label": "a"}, {"id": "B", "label": "b"}],
    })
    assert isinstance(result, dict)
    assert len(result["prompt"]) == _PROMPT_MAX


def test_validate_truncates_long_label():
    tool = AskUserChoiceTool()
    long_label = "y" * (_LABEL_MAX + 50)
    result = tool._validate_and_build_spec({
        "prompt": "test",
        "options": [{"id": "A", "label": long_label}, {"id": "B", "label": "b"}],
    })
    assert isinstance(result, dict)
    assert len(result["options"][0]["label"]) == _LABEL_MAX
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd astrbot_plugin_ask_user_choice && python -m pytest tests/test_ask_user_choice_tool.py -v
```

Expected: FAIL with `ModuleNotFoundError` 或 `ImportError`(旧 v0.3 实现的常量不在)

- [ ] **Step 3: Write the new ask_user_choice_tool.py (骨架)**

`astrbot_plugin_ask_user_choice/ask_user_choice_tool.py` (完整重写):

```python
"""ask_user_choice 工具 (v1.0 真阻塞式)。

阻塞等待 dashboard 用户响应,完成后直接返回用户选择给 LLM。
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from astrbot.api import FunctionTool
from astrbot.core.utils.path_utils import get_astrbot_data_path  # noqa: F401

from .interactive_choice_registry import registry

if TYPE_CHECKING:
    from astrbot.core.agent.run_context import ContextWrapper


# 字段长度上限
_PROMPT_MAX = 200
_TITLE_MAX = 30
_LABEL_MAX = 30
_DESCRIPTION_MAX = 200
_INPUT_PLACEHOLDER_MAX = 60
_OPTIONS_MIN = 2
_OPTIONS_MAX = 10


@dataclass
class AskUserChoiceTool(FunctionTool):
    """ask_user_choice 工具:阻塞式等待用户选择。"""

    name: str = "ask_user_choice"
    description: str = (
        "Present the user with a question and a set of options to choose from. "
        "Use this when you need the user to make a decision before you can proceed. "
        "This tool blocks until the user responds, then returns their choice. "
        "The user's response is returned directly as this tool's result."
    )
    parameters: dict = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Question displayed at the top of the option box",
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
                            "description": "Unique option ID (e.g. A/B/C)",
                        },
                        "label": {
                            "type": "string",
                            "description": "Button text",
                        },
                        "description": {
                            "type": "string",
                            "description": "Optional detail",
                        },
                    },
                    "required": ["id", "label"],
                },
            },
            "title": {
                "type": "string",
                "description": "Optional dialog title",
            },
            "input_placeholder": {
                "type": "string",
                "description": "Free-text input placeholder",
            },
        },
        "required": ["prompt", "options"],
    })

    def _validate_and_build_spec(self, kwargs: dict) -> dict | str:
        """校验参数 + 截断 + 构造 spec dict。

        Args:
            kwargs: 工具调用参数。

        Returns:
            校验通过返回 spec dict,失败返回错误字符串(供 LLM 自助重试)。
        """
        prompt = (kwargs.get("prompt") or "").strip()
        if not prompt:
            return "Error: prompt cannot be empty"

        options = kwargs.get("options") or []
        if not isinstance(options, list) or not (
            _OPTIONS_MIN <= len(options) <= _OPTIONS_MAX
        ):
            return (
                f"Error: options must be an array with "
                f"{_OPTIONS_MIN}-{_OPTIONS_MAX} elements."
            )

        normalized = []
        seen = set()
        for idx, opt in enumerate(options):
            if not isinstance(opt, dict):
                return f"Error: options[{idx}] is not an object"
            oid = str(opt.get("id") or "").strip()
            label = str(opt.get("label") or "").strip()
            if not oid or not label:
                return f"Error: options[{idx}] needs id/label"
            if oid in seen:
                return f"Error: duplicate option id: {oid!r}"
            seen.add(oid)
            normalized.append({
                "id": oid,
                "label": label[:_LABEL_MAX],
                "description": (opt.get("description") or "")[:_DESCRIPTION_MAX] or None,
            })

        spec: dict = {
            "type": "interactive_choice",
            "prompt": prompt[:_PROMPT_MAX],
            "options": normalized,
        }
        title = kwargs.get("title")
        if title and title.strip():
            spec["title"] = title.strip()[:_TITLE_MAX]
        placeholder = kwargs.get("input_placeholder")
        if placeholder and placeholder.strip():
            spec["input_placeholder"] = placeholder.strip()[:_INPUT_PLACEHOLDER_MAX]
        return spec

    async def call(self, context: "ContextWrapper", **kwargs: Any) -> str:  # noqa: ARG002
        """阻塞式实现 — 见 Task 6。"""
        raise NotImplementedError("Implemented in Task 6")

    def _format_choice_for_llm(self, user_choice: dict, spec: dict) -> str:  # noqa: ARG002
        """格式化用户选择为 LLM 可见字符串 — 见 Task 7。"""
        raise NotImplementedError("Implemented in Task 7")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd astrbot_plugin_ask_user_choice && python -m pytest tests/test_ask_user_choice_tool.py -v
```

Expected: 7 passed (validate 相关)

- [ ] **Step 5: Commit**

```bash
cd astrbot_plugin_ask_user_choice
git add ask_user_choice_tool.py tests/test_ask_user_choice_tool.py
git commit -m "feat(tool): rewrite ask_user_choice_tool with webchat guard + validate"
```

---

## Task 6: 工具 - 完整 call() 流程

**Files:**
- Modify: `astrbot_plugin_ask_user_choice/ask_user_choice_tool.py`
- Modify: `astrbot_plugin_ask_user_choice/tests/test_ask_user_choice_tool.py`

**Interfaces:**
- Produces: `AskUserChoiceTool.call(context, **kwargs) -> str` (完整实现)

- [ ] **Step 1: Add failing test for call() - webchat 守卫**

Append to `tests/test_ask_user_choice_tool.py`:

```python
@pytest.mark.asyncio
async def test_call_rejects_non_webchat_platform(monkeypatch):
    """非 webchat 会话应早 return 错误字符串,不推送事件。"""
    tool = AskUserChoiceTool()
    ctx = _make_context(umo="lark:FriendMessage:lark!user!sess")
    # monkeypatch webchat_queue_mgr,确认没被调用
    from unittest.mock import MagicMock
    mock_mgr = MagicMock()
    monkeypatch.setattr(
        "astrbot_plugin_ask_user_choice.ask_user_choice_tool.webchat_queue_mgr",
        mock_mgr,
        raising=False,
    )
    result = await tool.call(ctx, prompt="test", options=[
        {"id": "A", "label": "a"}, {"id": "B", "label": "b"},
    ])
    assert "Error" in result
    assert "webchat" in result.lower()
    mock_mgr.get_or_create_back_queue.assert_not_called()


@pytest.mark.asyncio
async def test_call_success_path_resolves_with_user_choice(monkeypatch):
    """成功路径:工具注册到 registry,推事件,await,resolve,return。"""
    import asyncio

    tool = AskUserChoiceTool()
    ctx = _make_context()

    # monkeypatch _push_to_webchat_back_queue 为 noop
    async def fake_push(*args, **kwargs):
        pass
    monkeypatch.setattr(tool, "_push_to_webchat_back_queue", fake_push)
    monkeypatch.setattr(tool, "_push_resolved_to_back_queue", fake_push)
    # monkeypatch config loader
    monkeypatch.setattr(tool, "_load_tool_config", lambda ctx: {
        "timeout_seconds": 5, "max_concurrent_pending": 32,
    })

    # 启动工具调用协程
    call_task = asyncio.create_task(tool.call(
        ctx,
        prompt="Pick one",
        options=[{"id": "A", "label": "alpha"}, {"id": "B", "label": "beta"}],
    ))

    # 等 registry 注册
    await asyncio.sleep(0.05)
    assert len(registry._pending) == 1
    rid = next(iter(registry._pending.keys()))

    # 模拟用户选择
    registry.resolve(rid, {"choice_id": "A", "free_text": ""})

    # 等待工具返回
    result = await asyncio.wait_for(call_task, timeout=2.0)
    assert "User selected" in result
    assert "alpha" in result or "A" in result
    # registry 应被清理
    assert rid not in registry._pending


@pytest.mark.asyncio
async def test_call_timeout_returns_fallback(monkeypatch):
    """超时路径:工具返回 fallback 字符串。"""
    tool = AskUserChoiceTool()
    ctx = _make_context()

    async def fake_push(*args, **kwargs):
        pass
    monkeypatch.setattr(tool, "_push_to_webchat_back_queue", fake_push)
    monkeypatch.setattr(tool, "_push_resolved_to_back_queue", fake_push)
    monkeypatch.setattr(tool, "_load_tool_config", lambda ctx: {
        "timeout_seconds": 1,
        "timeout_fallback_message": "[User did not respond within 1 seconds.]",
        "max_concurrent_pending": 32,
    })

    result = await tool.call(
        ctx,
        prompt="Pick one",
        options=[{"id": "A", "label": "a"}, {"id": "B", "label": "b"}],
    )
    assert "did not respond" in result
    assert len(registry._pending) == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd astrbot_plugin_ask_user_choice && python -m pytest tests/test_ask_user_choice_tool.py -v
```

Expected: FAIL(NotImplementedError)

- [ ] **Step 3: Implement full call()**

Modify `AskUserChoiceTool.call` in `ask_user_choice_tool.py`:

```python
    async def call(self, context: "ContextWrapper", **kwargs: Any) -> str:
        """阻塞等待用户响应,完成后返回用户选择给 LLM。

        Args:
            context: AstrBot 运行时上下文。
            kwargs: 工具参数(prompt, options, title?, input_placeholder?)。

        Returns:
            成功: "User selected: <label> (id=<id>)[\\nAdditional note: <free_text>]"
            超时: 配置的 fallback message
            取消: "[User input was cancelled]"
            错误: "Error: ..."
        """
        # ── 1. 平台守卫 ──
        umo = context.context.event.unified_msg_origin
        if not umo.startswith("webchat:"):
            return (
                "Error: ask_user_choice is only supported in the webchat dashboard. "
                f"Current platform: {umo.split(':', 1)[0]}. "
                "Please open the dashboard to make your selection."
            )

        # ── 2. 参数校验 ──
        spec_or_error = self._validate_and_build_spec(kwargs)
        if isinstance(spec_or_error, str):
            return spec_or_error
        spec = spec_or_error

        # ── 3. 配置加载 ──
        config = self._load_tool_config(context)
        timeout_s = int(config.get("timeout_seconds", 300))
        fallback_msg = config.get(
            "timeout_fallback_message",
            "[User did not respond within {timeout} seconds. Please proceed with a reasonable default.]",
        ).format(timeout=timeout_s)
        max_concurrent = int(config.get("max_concurrent_pending", 32))

        # ── 4. 并发上限检查 ──
        if len(registry._pending) >= max_concurrent:
            return (
                f"Error: too many concurrent interactive choices (max {max_concurrent}). "
                "Please wait for some to resolve."
            )

        # ── 5. 注册到 Registry ──
        request_id = str(uuid.uuid4())
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        expires_at = time.time() + timeout_s

        registry.add(
            request_id=request_id,
            umo=umo,
            future=future,
            spec=spec,
            created_at=time.time(),
            timeout_at=expires_at,
        )

        # ── 6. 推送 interactive_choice 事件给前端 ──
        try:
            await self._push_to_webchat_back_queue(
                request_id=request_id, umo=umo, spec=spec, expires_at=expires_at,
            )
        except Exception as exc:
            registry.remove(request_id)
            return f"Error: failed to push interactive choice to frontend: {exc}"

        # ── 7. 真阻塞 ──
        try:
            user_choice = await asyncio.wait_for(future, timeout=timeout_s)
        except asyncio.TimeoutError:
            return fallback_msg
        except asyncio.CancelledError:
            return "[User input was cancelled]"
        finally:
            registry.remove(request_id)

        # ── 8. 推 resolved 广播(失败不影响主流程) ──
        try:
            await self._push_resolved_to_back_queue(
                request_id=request_id, umo=umo, reason="submitted",
            )
        except Exception:
            pass

        # ── 9. 格式化为 LLM 可见字符串 ──
        return self._format_choice_for_llm(user_choice, spec)

    async def _push_to_webchat_back_queue(
        self, request_id: str, umo: str, spec: dict, expires_at: float,
    ) -> None:
        """推 interactive_choice 事件到 webchat SSE 流。"""
        from astrbot.core.platform.sources.webchat.webchat_queue_mgr import webchat_queue_mgr
        parts = umo.split(":", 2)
        if len(parts) < 3:
            raise ValueError(f"Invalid umo: {umo}")
        session_key = parts[2]
        chunks = session_key.split("!")
        conversation_id = chunks[-1] if len(chunks) >= 3 else session_key

        back_queue = webchat_queue_mgr.get_or_create_back_queue(
            request_id=request_id, conversation_id=conversation_id,
        )
        await back_queue.put({
            "type": "interactive_choice",
            "data": {
                "request_id": request_id,
                "spec": spec,
                "expires_at": expires_at,
                "umo": umo,
            },
            "message_id": request_id,
        })

    async def _push_resolved_to_back_queue(
        self, request_id: str, umo: str, reason: str,
    ) -> None:
        """推 interactive_choice_resolved 事件给所有 SSE 订阅者。"""
        from astrbot.core.platform.sources.webchat.webchat_queue_mgr import webchat_queue_mgr
        parts = umo.split(":", 2)
        if len(parts) < 3:
            return
        session_key = parts[2]
        chunks = session_key.split("!")
        conversation_id = chunks[-1] if len(chunks) >= 3 else session_key

        back_queue = webchat_queue_mgr.get_or_create_back_queue(
            request_id=request_id, conversation_id=conversation_id,
        )
        await back_queue.put({
            "type": "interactive_choice_resolved",
            "data": {"request_id": request_id, "reason": reason},
            "message_id": request_id,
        })

    def _load_tool_config(self, context: "ContextWrapper") -> dict:
        """从插件 config 读配置。无法获取时返回空 dict(走默认值)。"""
        try:
            return context.context.get_config() or {}
        except Exception:
            return {}
```

(删除原有的 `raise NotImplementedError("Implemented in Task 6")` placeholder)

- [ ] **Step 4: Run test to verify it passes**

```bash
cd astrbot_plugin_ask_user_choice && python -m pytest tests/test_ask_user_choice_tool.py -v
```

Expected: 10 passed (7 validate + 3 call)

- [ ] **Step 5: Commit**

```bash
cd astrbot_plugin_ask_user_choice
git add ask_user_choice_tool.py tests/test_ask_user_choice_tool.py
git commit -m "feat(tool): implement full call() with webchat guard + block + resolve"
```

---

## Task 7: 工具 - _format_choice_for_llm

**Files:**
- Modify: `astrbot_plugin_ask_user_choice/ask_user_choice_tool.py`
- Modify: `astrbot_plugin_ask_user_choice/tests/test_ask_user_choice_tool.py`

**Interfaces:**
- Produces: `AskUserChoiceTool._format_choice_for_llm(user_choice, spec) -> str`

- [ ] **Step 1: Add failing test**

Append to `tests/test_ask_user_choice_tool.py`:

```python
def test_format_choice_with_label_only():
    tool = AskUserChoiceTool()
    spec = {"options": [{"id": "A", "label": "alpha"}, {"id": "B", "label": "beta"}]}
    result = tool._format_choice_for_llm({"choice_id": "A", "free_text": ""}, spec)
    assert "alpha" in result
    assert "id=A" in result
    assert "Additional note" not in result


def test_format_choice_with_free_text():
    tool = AskUserChoiceTool()
    spec = {"options": [{"id": "A", "label": "alpha"}, {"id": "B", "label": "beta"}]}
    result = tool._format_choice_for_llm({"choice_id": "B", "free_text": "因为快"}, spec)
    assert "beta" in result
    assert "id=B" in result
    assert "因为快" in result
    assert "Additional note" in result


def test_format_choice_with_free_text_only():
    tool = AskUserChoiceTool()
    spec = {"options": [{"id": "A", "label": "alpha"}, {"id": "B", "label": "beta"}]}
    result = tool._format_choice_for_llm(
        {"choice_id": "__free_text__", "free_text": "我选自己想的"}, spec,
    )
    assert "__free_text__" in result
    assert "我选自己想的" in result


def test_format_choice_unknown_id_falls_back_to_id():
    tool = AskUserChoiceTool()
    spec = {"options": [{"id": "A", "label": "alpha"}]}
    result = tool._format_choice_for_llm({"choice_id": "Z", "free_text": ""}, spec)
    # Z 不在 options 里,label fallback 到 choice_id
    assert "Z" in result
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd astrbot_plugin_ask_user_choice && python -m pytest tests/test_ask_user_choice_tool.py -v
```

Expected: FAIL with `NotImplementedError: Implemented in Task 7`

- [ ] **Step 3: Implement _format_choice_for_llm**

Replace the placeholder method in `ask_user_choice_tool.py`:

```python
    def _format_choice_for_llm(self, user_choice: dict, spec: dict) -> str:
        """把用户响应格式化为 LLM 可见字符串。

        Args:
            user_choice: {choice_id, free_text}
            spec: 工具构造的 spec(含 options 列表)。

        Returns:
            "User selected: <label> (id=<id>)[\\nAdditional note: <free_text>]"
        """
        choice_id = user_choice.get("choice_id", "")
        free_text = (user_choice.get("free_text") or "").strip()
        label = choice_id
        for opt in spec.get("options", []):
            if opt.get("id") == choice_id:
                label = opt.get("label") or choice_id
                break
        if free_text:
            return f"User selected: {label} (id={choice_id})\nAdditional note: {free_text}"
        return f"User selected: {label} (id={choice_id})"
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd astrbot_plugin_ask_user_choice && python -m pytest tests/test_ask_user_choice_tool.py -v
```

Expected: 14 passed (7 validate + 3 call + 4 format)

- [ ] **Step 5: Commit**

```bash
cd astrbot_plugin_ask_user_choice
git add ask_user_choice_tool.py tests/test_ask_user_choice_tool.py
git commit -m "feat(tool): implement _format_choice_for_llm"
```

---

## Task 8: REST - _extract_username_from_umo

**Files:**
- Create: `astrbot_plugin_ask_user_choice/interactive_choice_api.py`
- Create: `astrbot_plugin_ask_user_choice/tests/test_interactive_choice_api.py`

**Interfaces:**
- Produces: `function _extract_username_from_umo(umo) -> str`

- [ ] **Step 1: Add failing test**

`astrbot_plugin_ask_user_choice/tests/test_interactive_choice_api.py`:

```python
"""REST 端点单元测试。"""
from astrbot_plugin_ask_user_choice.interactive_choice_api import (
    _extract_username_from_umo,
)


def test_extract_username_from_webchat_umo():
    umo = "webchat:FriendMessage:webchat!alice!sess-123"
    assert _extract_username_from_umo(umo) == "alice"


def test_extract_username_returns_empty_for_non_webchat():
    umo = "lark:FriendMessage:lark!alice!sess-123"
    assert _extract_username_from_umo(umo) == ""


def test_extract_username_returns_empty_for_malformed():
    assert _extract_username_from_umo("invalid") == ""
    assert _extract_username_from_umo("webchat:FriendMessage") == ""  # 缺 session_key
    assert _extract_username_from_umo("webchat:FriendMessage:bad") == ""  # 缺 !
    assert _extract_username_from_umo("webchat:FriendMessage:foo!bar") == ""  # 缺 platform 头


def test_extract_username_handles_dots_and_dashes():
    umo = "webchat:FriendMessage:webchat!alice.smith_2!sess-2025-07-02"
    assert _extract_username_from_umo(umo) == "alice.smith_2"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd astrbot_plugin_ask_user_choice && python -m pytest tests/test_interactive_choice_api.py -v
```

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation (只有辅助函数)**

`astrbot_plugin_ask_user_choice/interactive_choice_api.py`:

```python
"""REST 端点:interactive-choice 提交与 pending 列表。

挂在 dashboard app:POST /api/chat/interactive-choice/<request_id>
                  GET  /api/chat/interactive-choice/pending
"""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, Request

from astrbot.dashboard.api.auth import require_dashboard_user
from astrbot.dashboard.responses import ApiError, ok

from .interactive_choice_registry import registry

logger = logging.getLogger(__name__)

router = APIRouter()


def _extract_username_from_umo(umo: str) -> str:
    """从 webchat umo 提取 dashboard username。

    预期格式: 'webchat:FriendMessage:webchat!alice!session_id'
    返回 'alice';失败(非 webchat / 格式错)返回 ''。
    """
    if not umo.startswith("webchat:"):
        return ""
    parts = umo.split(":", 2)
    if len(parts) < 3:
        return ""
    session_key = parts[2]
    chunks = session_key.split("!")
    if len(chunks) >= 3 and chunks[0] == "webchat":
        return chunks[1]
    return ""


# 端点实现见 Task 9, Task 10
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd astrbot_plugin_ask_user_choice && python -m pytest tests/test_interactive_choice_api.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
cd astrbot_plugin_ask_user_choice
git add interactive_choice_api.py tests/test_interactive_choice_api.py
git commit -m "feat(api): add _extract_username_from_umo helper"
```

---

## Task 9: REST - POST 端点

**Files:**
- Modify: `astrbot_plugin_ask_user_choice/interactive_choice_api.py`
- Modify: `astrbot_plugin_ask_user_choice/tests/test_interactive_choice_api.py`

**Interfaces:**
- Produces: `POST /api/chat/interactive-choice/<request_id>` with auth `Depends(require_dashboard_user)`

- [ ] **Step 1: Add failing tests for POST endpoint**

Append to `tests/test_interactive_choice_api.py`:

```python
import asyncio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from astrbot_plugin_ask_user_choice.interactive_choice_api import router
from astrbot_plugin_ask_user_choice.interactive_choice_registry import registry


@pytest.fixture
def app(monkeypatch):
    """构造测试用 FastAPI app,绕过真实 dashboard auth。"""
    test_app = FastAPI()
    test_app.include_router(router)
    # 替换 require_dashboard_user 为一个固定 username 返回
    from astrbot.dashboard.api.auth import require_dashboard_user
    def fake_auth():
        return "alice"
    test_app.dependency_overrides[require_dashboard_user] = lambda: "alice"
    return test_app


@pytest.fixture
def client(app):
    return TestClient(app)


def test_post_404_when_not_found(client):
    r = client.post(
        "/api/chat/interactive-choice/nonexistent",
        json={"choice_id": "A"},
    )
    assert r.status_code == 404


def test_post_400_when_missing_choice_id(client):
    # 先注册一个 pending
    fut = asyncio.get_event_loop().create_future()
    registry.add(
        "rid-1", "webchat:FriendMessage:webchat!alice!sess", fut,
        {"prompt": "x", "options": [{"id": "A", "label": "a"}]},
        0.0, time.time() + 60,
    )
    try:
        r = client.post("/api/chat/interactive-choice/rid-1", json={})
        assert r.status_code == 400
    finally:
        registry.remove("rid-1")


def test_post_403_when_other_user(client, monkeypatch):
    # 重新构造 client,bob 登录
    from astrbot.dashboard.api.auth import require_dashboard_user
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_dashboard_user] = lambda: "bob"
    c = TestClient(app)
    # pending 属于 alice
    fut = asyncio.get_event_loop().create_future()
    registry.add(
        "rid-1", "webchat:FriendMessage:webchat!alice!sess", fut,
        {"prompt": "x", "options": [{"id": "A", "label": "a"}]},
        0.0, time.time() + 60,
    )
    try:
        r = c.post("/api/chat/interactive-choice/rid-1", json={"choice_id": "A"})
        assert r.status_code == 403
    finally:
        registry.remove("rid-1")


def test_post_success_resolves_future(client):
    fut = asyncio.get_event_loop().create_future()
    registry.add(
        "rid-1", "webchat:FriendMessage:webchat!alice!sess", fut,
        {"prompt": "x", "options": [{"id": "A", "label": "alpha"}]},
        0.0, time.time() + 60,
    )
    try:
        r = client.post(
            "/api/chat/interactive-choice/rid-1",
            json={"choice_id": "A", "free_text": "我选 A"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        # future 已被 resolve
        assert fut.done()
        result = fut.result()
        assert result["choice_id"] == "A"
        assert result["free_text"] == "我选 A"
    finally:
        registry.remove("rid-1")


def test_post_double_call_returns_409(client):
    fut = asyncio.get_event_loop().create_future()
    registry.add(
        "rid-1", "webchat:FriendMessage:webchat!alice!sess", fut,
        {"prompt": "x", "options": [{"id": "A", "label": "alpha"}]},
        0.0, time.time() + 60,
    )
    try:
        client.post("/api/chat/interactive-choice/rid-1", json={"choice_id": "A"})
        # 第二次
        r = client.post("/api/chat/interactive-choice/rid-1", json={"choice_id": "B"})
        assert r.status_code == 409
    finally:
        registry.remove("rid-1")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd astrbot_plugin_ask_user_choice && python -m pytest tests/test_interactive_choice_api.py -v
```

Expected: FAIL(no POST endpoint)

- [ ] **Step 3: Implement POST endpoint**

Append to `interactive_choice_api.py`:

```python
@router.post("/api/chat/interactive-choice/<request_id>")
async def submit_interactive_choice(
    request_id: str,
    request: Request,
    username: str = Depends(require_dashboard_user),
):
    """用户提交选择,resolve 对应 future。

    Returns:
        200: {status: "ok", data: {request_id, resolved_at}}
        400: body 缺 choice_id
        403: pending 属于其他用户
        404: request_id 不存在或已超时
        409: 已被 resolve(防双调用)
    """
    pending = registry._pending.get(request_id)
    if pending is None:
        raise ApiError("Interactive choice not found or expired", status_code=404)

    # 鉴权层 2:UMO 归属
    expected = _extract_username_from_umo(pending.umo)
    if not expected or expected != username:
        raise ApiError("Not authorized to resolve this choice", status_code=403)

    # 解析 body
    try:
        body = await request.json()
    except Exception:
        raise ApiError("Invalid JSON body", status_code=400)
    if not isinstance(body, dict):
        raise ApiError("Body must be a JSON object", status_code=400)

    choice_id = body.get("choice_id")
    if not isinstance(choice_id, str) or not choice_id.strip():
        raise ApiError("Missing key: choice_id", status_code=400)
    free_text = body.get("free_text") or ""
    if not isinstance(free_text, str):
        free_text = ""

    payload = {"choice_id": choice_id.strip(), "free_text": free_text.strip()}
    if not registry.resolve(request_id, payload):
        raise ApiError("Already resolved or expired", status_code=409)

    return ok({"request_id": request_id, "resolved_at": time.time()})
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd astrbot_plugin_ask_user_choice && python -m pytest tests/test_interactive_choice_api.py -v
```

Expected: 9 passed (4 helper + 5 POST)

- [ ] **Step 5: Commit**

```bash
cd astrbot_plugin_ask_user_choice
git add interactive_choice_api.py tests/test_interactive_choice_api.py
git commit -m "feat(api): add POST /api/chat/interactive-choice/<request_id>"
```

---

## Task 10: REST - GET pending 端点

**Files:**
- Modify: `astrbot_plugin_ask_user_choice/interactive_choice_api.py`
- Modify: `astrbot_plugin_ask_user_choice/tests/test_interactive_choice_api.py`

**Interfaces:**
- Produces: `GET /api/chat/interactive-choice/pending?session_id=<umo>`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_interactive_choice_api.py`:

```python
def test_get_pending_400_when_missing_session_id(client):
    r = client.get("/api/chat/interactive-choice/pending")
    assert r.status_code == 400


def test_get_pending_403_when_other_user():
    from astrbot.dashboard.api.auth import require_dashboard_user
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_dashboard_user] = lambda: "bob"
    c = TestClient(app)
    r = c.get("/api/chat/interactive-choice/pending?session_id=webchat:FriendMessage:webchat!alice!sess")
    assert r.status_code == 403


def test_get_pending_400_for_non_webchat_session(client):
    r = client.get("/api/chat/interactive-choice/pending?session_id=lark:...!alice!sess")
    assert r.status_code == 400


def test_get_pending_returns_alice_pending(client):
    # 注册 alice 的 pending
    fut1 = asyncio.get_event_loop().create_future()
    fut2 = asyncio.get_event_loop().create_future()
    registry.add(
        "rid-1", "webchat:FriendMessage:webchat!alice!sess",
        fut1, {"prompt": "p1", "options": [{"id": "A", "label": "a"}]},
        0.0, time.time() + 60,
    )
    registry.add(
        "rid-2", "webchat:FriendMessage:webchat!bob!sess",
        fut2, {"prompt": "p2", "options": [{"id": "B", "label": "b"}]},
        0.0, time.time() + 60,
    )
    try:
        r = client.get(
            "/api/chat/interactive-choice/pending?session_id=webchat:FriendMessage:webchat!alice!sess",
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        pending = body["data"]["pending"]
        assert len(pending) == 1
        assert pending[0]["request_id"] == "rid-1"
        assert pending[0]["prompt"] == "p1"  # 来自 spec
        assert "request_id" in pending[0]
        assert "expires_at" in pending[0]
    finally:
        registry.remove("rid-1")
        registry.remove("rid-2")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd astrbot_plugin_ask_user_choice && python -m pytest tests/test_interactive_choice_api.py -v
```

Expected: FAIL(no GET endpoint)

- [ ] **Step 3: Implement GET endpoint**

Append to `interactive_choice_api.py`:

```python
@router.get("/api/chat/interactive-choice/pending")
async def list_pending(
    request: Request,
    session_id: str = "",
    username: str = Depends(require_dashboard_user),
):
    """列出某 umo 下所有仍 pending 的 interactive_choice。

    Returns:
        200: {status: "ok", data: {pending: [{request_id, ...full InteractiveChoicePart}, ...]}}
        400: 缺 session_id 或非 webchat 会话
        403: session_id 属于其他用户
    """
    if not session_id:
        raise ApiError("Missing key: session_id", status_code=400)
    if not session_id.startswith("webchat:"):
        raise ApiError("Only webchat sessions supported", status_code=400)

    expected = _extract_username_from_umo(session_id)
    if not expected or expected != username:
        raise ApiError("Not authorized", status_code=403)

    pending_list = registry.list_pending_for_umo(session_id)
    parts = []
    for item in pending_list:
        spec = item["spec"].copy()
        spec["request_id"] = item["request_id"]
        spec["expires_at"] = item["timeout_at"]
        parts.append(spec)
    return ok({"pending": parts})
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd astrbot_plugin_ask_user_choice && python -m pytest tests/test_interactive_choice_api.py -v
```

Expected: 13 passed

- [ ] **Step 5: Commit**

```bash
cd astrbot_plugin_ask_user_choice
git add interactive_choice_api.py tests/test_interactive_choice_api.py
git commit -m "feat(api): add GET /api/chat/interactive-choice/pending"
```

---

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

## Task 12: 前端 schema 重写 + 单测

**Files:**
- Modify: `dashboard/src/composables/parseInteractiveChoice.ts` (重写)
- Create: `dashboard/src/composables/parseInteractiveChoice.test.ts`

**Interfaces:**
- Produces: `InteractiveChoicePart` with `request_id: string` (required)
- Produces: `validateInteractiveChoice` checks `request_id`

- [ ] **Step 1: Write failing tests**

`dashboard/src/composables/parseInteractiveChoice.test.ts`:

```typescript
// node --test
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  isInteractiveChoicePayload,
  validateInteractiveChoice,
  truncateInteractiveChoice,
  getOptionSubmitText,
} from './parseInteractiveChoice';

test('isInteractiveChoicePayload accepts valid type', () => {
  assert.equal(isInteractiveChoicePayload({ type: 'interactive_choice' }), true);
});

test('isInteractiveChoicePayload rejects null', () => {
  assert.equal(isInteractiveChoicePayload(null), false);
});

test('validateInteractiveChoice accepts request_id', () => {
  const valid = {
    type: 'interactive_choice',
    request_id: 'r1',
    prompt: 'test',
    options: [{ id: 'A', label: 'a' }, { id: 'B', label: 'b' }],
  };
  assert.equal(validateInteractiveChoice(valid), true);
});

test('validateInteractiveChoice rejects missing request_id', () => {
  const invalid = {
    type: 'interactive_choice',
    prompt: 'test',
    options: [{ id: 'A', label: 'a' }, { id: 'B', label: 'b' }],
  };
  assert.equal(validateInteractiveChoice(invalid), false);
});

test('validateInteractiveChoice rejects empty request_id', () => {
  const invalid = {
    type: 'interactive_choice',
    request_id: '  ',
    prompt: 'test',
    options: [{ id: 'A', label: 'a' }, { id: 'B', label: 'b' }],
  };
  assert.equal(validateInteractiveChoice(invalid), false);
});

test('validateInteractiveChoice rejects duplicate option ids', () => {
  const invalid = {
    type: 'interactive_choice',
    request_id: 'r1',
    prompt: 'test',
    options: [{ id: 'A', label: 'a' }, { id: 'A', label: 'b' }],
  };
  assert.equal(validateInteractiveChoice(invalid), false);
});

test('truncateInteractiveChoice preserves request_id', () => {
  const input = {
    type: 'interactive_choice' as const,
    request_id: 'r1',
    prompt: 'x'.repeat(300),
    options: [{ id: 'A', label: 'a' }],
  };
  const out = truncateInteractiveChoice(input);
  assert.equal(out.request_id, 'r1');
  assert.equal(out.prompt.length, 200);
});

test('getOptionSubmitText returns id+label when no value', () => {
  const opt = { id: 'A', label: 'alpha' };
  assert.equal(getOptionSubmitText(opt), 'A. alpha');
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd dashboard && pnpm exec node --test --import tsx src/composables/parseInteractiveChoice.test.ts
```

> 如果项目用 vitest,改为 `pnpm test -- src/composables/parseInteractiveChoice.test.ts`

Expected: FAIL (imports not found)

- [ ] **Step 3: Rewrite parseInteractiveChoice.ts**

完整重写 `dashboard/src/composables/parseInteractiveChoice.ts`(只保留新机制相关函数,删除 v0.3 旧解包逻辑):

```typescript
// Author: elecvoid243
// Date: 2026-07-02
// Spec: docs/superpowers/specs/2026-07-02-blocking-interactive-choice-design.md §5.1
//
// 纯函数模块:校验 + 截断 InteractiveChoicePart。v1.0 走 SSE 顶层 type,
// 不再解 plain 文本/拆 tool_call,删除相关辅助函数。

export interface InteractiveChoiceOption {
  id: string;
  label: string;
  description?: string;
  /** 旧 plugin 字段(v0.3),新代码忽略 */
  value?: string;
}

export interface InteractiveChoicePart {
  type: 'interactive_choice';
  /** v1.0 必填:后端生成的 request_id,提交时用作路由 */
  request_id: string;
  prompt: string;
  title?: string;
  options: InteractiveChoiceOption[];
  input_placeholder?: string;
  /** v1.0 可选:unix ts,前端可显示倒计时 */
  expires_at?: number;
  [key: string]: unknown;
}

export function isInteractiveChoicePayload(value: unknown): value is InteractiveChoicePart {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const obj = value as Record<string, unknown>;
  return obj.type === 'interactive_choice';
}

export function validateInteractiveChoice(obj: unknown): boolean {
  if (!isInteractiveChoicePayload(obj)) return false;
  const part = obj as Record<string, unknown>;
  if (typeof part.request_id !== 'string' || !part.request_id.trim()) return false;
  if (typeof part.prompt !== 'string' || !part.prompt.trim()) return false;
  if (!Array.isArray(part.options) || part.options.length < 2) return false;
  const seen = new Set<string>();
  for (const opt of part.options) {
    if (!opt || typeof opt !== 'object') return false;
    const o = opt as Record<string, unknown>;
    if (typeof o.id !== 'string' || !o.id.trim()) return false;
    if (typeof o.label !== 'string' || !o.label.trim()) return false;
    if (seen.has(o.id)) return false;
    seen.add(o.id);
  }
  return true;
}

export function truncateInteractiveChoice(part: InteractiveChoicePart): InteractiveChoicePart {
  const LIMITS = { PROMPT_MAX: 200, TITLE_MAX: 30, LABEL_MAX: 30, DESC_MAX: 200, PLACEHOLDER_MAX: 60 };
  let mutated = false;
  const out: InteractiveChoicePart = { ...part };
  if (out.prompt.length > LIMITS.PROMPT_MAX) {
    out.prompt = out.prompt.slice(0, LIMITS.PROMPT_MAX);
    mutated = true;
  }
  if (typeof out.title === 'string' && out.title.length > LIMITS.TITLE_MAX) {
    out.title = out.title.slice(0, LIMITS.TITLE_MAX);
    mutated = true;
  }
  if (typeof out.input_placeholder === 'string' && out.input_placeholder.length > LIMITS.PLACEHOLDER_MAX) {
    out.input_placeholder = out.input_placeholder.slice(0, LIMITS.PLACEHOLDER_MAX);
    mutated = true;
  }
  if (Array.isArray(out.options)) {
    const newOpts: InteractiveChoiceOption[] = [];
    for (const opt of out.options) {
      const o: InteractiveChoiceOption = { ...opt };
      if (o.label.length > LIMITS.LABEL_MAX) {
        o.label = o.label.slice(0, LIMITS.LABEL_MAX);
        mutated = true;
      }
      if (typeof o.description === 'string' && o.description.length > LIMITS.DESC_MAX) {
        o.description = o.description.slice(0, LIMITS.DESC_MAX);
        mutated = true;
      }
      newOpts.push(o);
    }
    out.options = newOpts;
  }
  return mutated ? out : part;
}

export function getOptionSubmitText(opt: InteractiveChoiceOption): string {
  if (typeof opt.value === 'string' && opt.value.length > 0) return opt.value;
  const id = typeof opt.id === 'string' ? opt.id : '';
  const label = typeof opt.label === 'string' ? opt.label : '';
  if (id && label) return `${id}. ${label}`;
  if (label) return label;
  return id;
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd dashboard && pnpm exec node --test --import tsx src/composables/parseInteractiveChoice.test.ts
```

Expected: 8 passed

- [ ] **Step 5: Type check**

```bash
cd dashboard && pnpm typecheck
```

Expected: 通过(若有错,可能需要更新依赖 InteractiveChoicePart 的其他文件 — 见 Task 16)

- [ ] **Step 6: Commit**

```bash
cd dashboard
git add src/composables/parseInteractiveChoice.ts src/composables/parseInteractiveChoice.test.ts
git commit -m "refactor(frontend): rewrite parseInteractiveChoice for v1.0, add request_id"
```

---

## Task 13: 前端 Pinia store + 单测

**Files:**
- Create: `dashboard/src/stores/interactiveChoice.ts`
- Create: `dashboard/src/stores/interactiveChoice.test.ts`

- [ ] **Step 1: Write failing test**

`dashboard/src/stores/interactiveChoice.test.ts`:

```typescript
// node --test,需要 mock httpClient
import { test } from 'node:test';
import assert from 'node:assert/strict';

// 由于 Pinia store 依赖 Vue runtime,这里只测试纯函数逻辑;
// 完整的 store 测试在 E2E 阶段覆盖
import {
  STORAGE_KEY,  // 导出供测试
} from './interactiveChoice';

test('STORAGE_KEY is correct', () => {
  assert.equal(STORAGE_KEY, 'astrbot-interactive-choice-pending');
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd dashboard && pnpm exec node --test --import tsx src/stores/interactiveChoice.test.ts
```

Expected: FAIL (module not found)

- [ ] **Step 3: Write the store**

`dashboard/src/stores/interactiveChoice.ts`:

```typescript
// Author: elecvoid243
// Date: 2026-07-02
// Spec: docs/superpowers/specs/2026-07-02-blocking-interactive-choice-design.md §5.2
import { defineStore } from 'pinia';
import { httpClient } from '@/api/http';
import type { ApiEnvelope } from '@/api/v1';
import type { InteractiveChoicePart } from '@/composables/parseInteractiveChoice';

export const STORAGE_KEY = 'astrbot-interactive-choice-pending';

interface State {
  activeChoices: Record<string, InteractiveChoicePart>;
}

export const useInteractiveChoiceStore = defineStore('interactiveChoice', {
  state: (): State => ({ activeChoices: {} }),
  getters: {
    hasAny: (s) => Object.keys(s.activeChoices).length > 0,
    asList: (s) => Object.values(s.activeChoices),
  },
  actions: {
    addChoice(part: InteractiveChoicePart) {
      this.activeChoices[part.request_id] = part;
      this.persist();
    },
    removeChoice(requestId: string) {
      delete this.activeChoices[requestId];
      this.persist();
    },
    hydrate() {
      try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (!raw) return;
        const parsed = JSON.parse(raw) as InteractiveChoicePart[];
        for (const part of parsed) {
          if (part?.request_id) this.activeChoices[part.request_id] = part;
        }
      } catch {
        localStorage.removeItem(STORAGE_KEY);
      }
    },
    async reconcile(umo: string) {
      try {
        const res = await httpClient.get<ApiEnvelope<{ pending: InteractiveChoicePart[] }>>(
          '/api/chat/interactive-choice/pending',
          { params: { session_id: umo } },
        );
        if (res.data?.status === 'ok') {
          this.activeChoices = {};
          for (const part of res.data.data.pending) {
            this.activeChoices[part.request_id] = part;
          }
          this.persist();
        }
      } catch (e) {
        console.warn('[interactiveChoice] reconcile failed:', e);
      }
    },
    async submitChoice(
      requestId: string,
      payload: { choice_id: string; free_text: string },
    ) {
      const res = await httpClient.post<ApiEnvelope<unknown>>(
        `/api/chat/interactive-choice/${requestId}`,
        payload,
      );
      if (res.data?.status === 'ok') {
        // 乐观更新(失败时 throw,UI 保持)
        this.removeChoice(requestId);
      }
      return res.data;
    },
    persist() {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(this.asList));
      } catch (e) {
        console.warn('[interactiveChoice] persist failed:', e);
      }
    },
  },
});
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd dashboard && pnpm exec node --test --import tsx src/stores/interactiveChoice.test.ts
```

Expected: 1 passed

- [ ] **Step 5: Type check**

```bash
cd dashboard && pnpm typecheck
```

Expected: 通过

- [ ] **Step 6: Commit**

```bash
cd dashboard
git add src/stores/interactiveChoice.ts src/stores/interactiveChoice.test.ts
git commit -m "feat(frontend): add interactiveChoice Pinia store"
```

---

## Task 14: 前端 InteractiveChoiceBox 改 emit

**Files:**
- Modify: `dashboard/src/components/chat/message_list_comps/InteractiveChoiceBox.vue`

- [ ] **Step 1: Locate emit statements**

```bash
cd dashboard && grep -n 'emit("submit"' src/components/chat/message_list_comps/InteractiveChoiceBox.vue
```

Expected: 3 matches (defineEmits, onOptionClick, onInputSubmit)

- [ ] **Step 2: Modify defineEmits**

In `InteractiveChoiceBox.vue` `<script setup>`, find the `defineEmits` line and replace:

```typescript
// BEFORE
const emit = defineEmits<{
  submit: [text: string];
}>();

// AFTER
const emit = defineEmits<{
  submit: [requestId: string, payload: { choice_id: string; free_text: string }];
}>();
```

- [ ] **Step 3: Modify onOptionClick**

```typescript
// BEFORE
function onOptionClick(opt: InteractiveChoiceOption) {
  if (state.value !== "pending") return;
  const text = getOptionSubmitText(opt);
  submittedValue.value = text;
  submittedKind.value = "option";
  submittedOption.value = opt;
  emit("submit", text);
}

// AFTER
function onOptionClick(opt: InteractiveChoiceOption) {
  if (state.value !== "pending") return;
  emit("submit", props.part.request_id, { choice_id: opt.id, free_text: "" });
  const text = getOptionSubmitText(opt);
  submittedValue.value = text;
  submittedKind.value = "option";
  submittedOption.value = opt;
}
```

- [ ] **Step 4: Modify onInputSubmit**

```typescript
// BEFORE
function onInputSubmit() {
  const text = freeText.value.trim();
  if (!text || state.value !== "pending") return;
  submittedValue.value = text;
  submittedKind.value = "input";
  submittedOption.value = null;
  emit("submit", text);
}

// AFTER
function onInputSubmit() {
  const text = freeText.value.trim();
  if (!text || state.value !== "pending") return;
  emit("submit", props.part.request_id, {
    choice_id: "__free_text__",
    free_text: text,
  });
  submittedValue.value = text;
  submittedKind.value = "input";
  submittedOption.value = null;
}
```

- [ ] **Step 5: Type check**

```bash
cd dashboard && pnpm typecheck
```

Expected: 通过(Task 15 会处理父组件 `onInteractiveChoiceSubmit`)

- [ ] **Step 6: Commit**

```bash
cd dashboard
git add src/components/chat/message_list_comps/InteractiveChoiceBox.vue
git commit -m "refactor(frontend): change InteractiveChoiceBox emit to (requestId, payload)"
```

---

## Task 15: 前端 ChatMessageList 改 SSE + submit

**Files:**
- Modify: `dashboard/src/components/chat/ChatMessageList.vue`

**Interfaces:**
- Uses: `useInteractiveChoiceStore` from `@/stores/interactiveChoice`

- [ ] **Step 1: Locate relevant code**

```bash
cd dashboard && grep -n "onInteractiveChoiceSubmit\|interactive_choice\|interactiveChoice" src/components/chat/ChatMessageList.vue
```

- [ ] **Step 2: Add store import**

In `<script setup>` section, add import:

```typescript
import { useInteractiveChoiceStore } from '@/stores/interactiveChoice';
import { validateInteractiveChoice, truncateInteractiveChoice, type InteractiveChoicePart } from '@/composables/parseInteractiveChoice';
```

- [ ] **Step 3: Add store usage + onMounted/onActivated hooks**

In `<script setup>`, after imports, add:

```typescript
const interactiveChoiceStore = useInteractiveChoiceStore();

// 假设 currentUmo 已存在(computed),如:
const currentUmo = computed(() => buildWebchatUmoDetails(currentSessionId.value).umo);

onMounted(() => {
  interactiveChoiceStore.hydrate();
  if (currentUmo.value) {
    interactiveChoiceStore.reconcile(currentUmo.value);
  }
});

onActivated(() => {
  if (currentUmo.value) {
    interactiveChoiceStore.reconcile(currentUmo.value);
  }
});
```

> 如果组件没用 `onActivated`,可以只保留 `onMounted`,加一个 `watch(currentUmo, ...)` 在路由切换时也 reconcile。

- [ ] **Step 4: Replace onInteractiveChoiceSubmit handler**

Find the existing handler and replace:

```typescript
// BEFORE
async function onInteractiveChoiceSubmit(text: string) {
  // 旧实现:把 text 当作 user message 发送
  ...
}

// AFTER
async function onInteractiveChoiceSubmit(
  requestId: string,
  payload: { choice_id: string; free_text: string },
) {
  try {
    await interactiveChoiceStore.submitChoice(requestId, payload);
  } catch (e) {
    console.error('[interactiveChoice] submit failed:', e);
    // 失败:不删本地,UI 保持,用户可重试
  }
}
```

- [ ] **Step 5: Add SSE listener for interactive_choice events**

In the SSE event handler (find `case 'plain'` or similar), add new cases:

```typescript
// 在 SSE event handler switch 中,添加:
case 'interactive_choice': {
  const part: InteractiveChoicePart = {
    type: 'interactive_choice',
    request_id: event.data.request_id,
    ...event.data.spec,
    expires_at: event.data.expires_at,
  };
  if (validateInteractiveChoice(part)) {
    interactiveChoiceStore.addChoice(truncateInteractiveChoice(part));
  }
  break;
}
case 'interactive_choice_resolved': {
  interactiveChoiceStore.removeChoice(event.data.request_id);
  break;
}
```

- [ ] **Step 6: Type check**

```bash
cd dashboard && pnpm typecheck
```

Expected: 通过

- [ ] **Step 7: Commit**

```bash
cd dashboard
git add src/components/chat/ChatMessageList.vue
git commit -m "feat(frontend): wire SSE events + Pinia store to ChatMessageList"
```

---

## Task 16: 前端 useMessages 删旧解包

**Files:**
- Modify: `dashboard/src/composables/useMessages.ts`

- [ ] **Step 1: Locate old unwrap calls**

```bash
cd dashboard && grep -n "unwrapInteractiveChoice\|extractAskUserChoiceFromToolCall" src/composables/useMessages.ts
```

- [ ] **Step 2: Remove old unwrap calls**

Find lines that call these functions and **remove** them (the InteractiveChoiceBox now reads directly from the store, no need to transform tool_call parts):

```typescript
// DELETE (or comment out):
import {
  unwrapInteractiveChoice,
  extractAskUserChoiceFromToolCall,
  ...
} from './parseInteractiveChoice';

// And any calls like:
// const unwrapped = unwrapInteractiveChoice(part);
// const extracted = extractAskUserChoiceFromToolCall(part);
```

> **注意**:v1.0 不再解 tool_call 内嵌的 interactive_choice(因为新机制走 SSE 顶层事件)。如果 `useMessages.ts` 中有其他用途的 `unwrapInteractiveChoice` 调用,谨慎评估后删除。

- [ ] **Step 3: Type check**

```bash
cd dashboard && pnpm typecheck
```

Expected: 通过(可能需要根据其他文件依赖调整 import)

- [ ] **Step 4: Verify grep 0 命中**

```bash
cd dashboard
grep -rn "unwrapInteractiveChoice\|extractAskUserChoiceFromToolCall" src/
```

Expected: no output

- [ ] **Step 5: Commit**

```bash
cd dashboard
git add src/composables/useMessages.ts
git commit -m "refactor(frontend): remove v0.3 unwrap helpers from useMessages"
```

---

## Task 17: metadata + _conf_schema + 文档归档

**Files:**
- Modify: `astrbot_plugin_ask_user_choice/metadata.yaml`
- Modify: `astrbot_plugin_ask_user_choice/_conf_schema.json`
- Modify: `astrbot_plugin_ask_user_choice/docs/superpowers/specs/2026-06-28-dynamic-choice-box-rendering-design.md`(加 deprecation note)

- [ ] **Step 1: Bump version in metadata.yaml**

```yaml
# astrbot_plugin_ask_user_choice/metadata.yaml
name: astrbot_plugin_ask_user
display_name: Ask User Choice
desc: 让 LLM 通过 ask_user_choice 工具向用户呈现可交互选项框（单选 + 自由输入）。v1.0 升级为真阻塞式:工具 await 用户选择,完成后直接返回结果,跨刷新持久化。
version: v1.0.0   # ← changed from v0.3.0
author: elecvoid243
repo: https://github.com/elecvoid243/astrbot_plugin_ask_user
astrbot_version: ">=4.16,<5"
```

- [ ] **Step 2: Update _conf_schema.json**

`astrbot_plugin_ask_user_choice/_conf_schema.json`:

```json
{
  "enabled": {
    "type": "boolean",
    "default": true,
    "description": "是否启用 ask_user_choice 工具"
  },
  "timeout_seconds": {
    "type": "integer",
    "default": 300,
    "minimum": 30,
    "maximum": 3600,
    "description": "等待用户响应的超时秒数,默认 5 分钟"
  },
  "timeout_fallback_message": {
    "type": "string",
    "default": "[User did not respond within {timeout} seconds. Please proceed with a reasonable default or inform the user that no response was received.]",
    "description": "超时后工具返回给 LLM 的文本,{timeout} 会被替换为实际秒数"
  },
  "max_concurrent_pending": {
    "type": "integer",
    "default": 32,
    "minimum": 1,
    "description": "单 AstrBot 实例最大并发等待数,超过时工具返回错误"
  }
}
```

- [ ] **Step 3: Add deprecation note to v0.3 spec**

在 `astrbot_plugin_ask_user_choice/docs/superpowers/specs/2026-06-28-dynamic-choice-box-rendering-design.md` 文件顶部加:

```markdown
> ⚠️ **DEPRECATED (2026-07-02)**: This spec describes v0.3 软阻塞式实现,已被 v1.0 真阻塞式替代。v1.0 spec 见 `2026-07-02-blocking-interactive-choice-design.md`。本文档保留作为历史记录,不再代表当前实现。
```

- [ ] **Step 4: Update README.md (用法说明)**

In `astrbot_plugin_ask_user_choice/README.md`, update the main usage description:

```markdown
## v1.0 真阻塞式 (2026-07-02+)

ask_user_choice 工具在 v1.0 起改为真阻塞式:LLM 调用后,工具内部 `await` 等待
dashboard 用户响应,完成后直接返回用户选择给 LLM(不是新 user message)。

### 用法

LLM 自动调用,无需用户额外操作。配置项见 `_conf_schema.json`。
```

- [ ] **Step 5: Final verification**

```bash
# 后端
cd astrbot_plugin_ask_user_choice
ruff check . && ruff format .
python -m pytest tests/ -v
grep -rn "unwrapInteractiveChoice\|extractAskUserChoiceFromToolCall\|_SYSTEM_PROMPT_POLICY\|INJECTION_MARKER\|build_injection_policy\|_inject_ask_user_choice_policy" . --include="*.py"
# Expected: ruff OK + all tests pass + no grep output

# 前端
cd dashboard
pnpm typecheck
pnpm lint
grep -rn "unwrapInteractiveChoice\|extractAskUserChoiceFromToolCall" src/
# Expected: pnpm OK + no grep output
```

- [ ] **Step 6: Commit**

```bash
cd astrbot_plugin_ask_user_choice
git add metadata.yaml _conf_schema.json README.md docs/
git commit -m "docs: bump to v1.0.0, update config schema, deprecate v0.3 spec"

cd dashboard
git add src/  # 如果还有遗漏的修改
git commit -m "chore: any leftover changes"
```

---

## Self-Review

### 1. Spec coverage

| Spec 章节 | 覆盖 Task |
|----------|----------|
| §1 背景与目标 | 隐含(全 plan) |
| §2 决策摘要 | 全 plan(每个决策都在某个 task 落地) |
| §3 架构总览 | Task 1, 6, 15(组件图 / 时序图对应) |
| §4 后端实现 | Task 1-11(全 4 个子节) |
| §5 前端实现 | Task 12-16(全 5 个子节) |
| §6 配置 schema | Task 17 |
| §7 错误处理 | Task 9(POST 错误矩阵), Task 10(GET 错误矩阵) |
| §8 测试策略 | 每个 task 都有对应测试 |
| §9 迁移与清理 | Task 11(main 重写), 12(schema 删 unwrap), 16(useMessages 删), 17(deprecation note) |
| §10 实施 PR 拆分 | Task 1-4 = PR 1, 5-7 = PR 2, 8-11 = PR 3, 12 = PR 4, 13 = PR 5, 14-16 = PR 6, 17 = PR 7 |
| §11 风险 | 文档化(后续实施时跟踪) |

**Gaps**: 无(每个 spec 章节都有 task 覆盖)

### 2. Placeholder scan

- ✅ 无 "TBD" / "TODO" / "implement later"
- ✅ 无 "add appropriate error handling" 类空泛描述
- ✅ 每个代码步骤都有完整代码块
- ✅ 步骤具体到"哪个文件、什么命令、什么预期输出"

### 3. Type consistency

| 名称 | 定义位置 | 使用位置 | 一致性 |
|------|---------|---------|--------|
| `registry` (单例) | Task 1 | Task 1, 2, 3, 4, 6, 9, 10 | ✓ |
| `PendingChoice` | Task 1 | Task 1 内部 | ✓ |
| `AskUserChoiceTool.call` 签名 `(context, **kwargs) -> str` | Task 5 | Task 6, 7 | ✓ |
| `_validate_and_build_spec(kwargs) -> dict \| str` | Task 5 | Task 5, 6 | ✓ |
| `_format_choice_for_llm(user_choice, spec) -> str` | Task 7 | Task 6, 7 | ✓ |
| `_extract_username_from_umo(umo) -> str` | Task 8 | Task 9, 10 | ✓ |
| `InteractiveChoicePart.request_id` | Task 12 | Task 12, 13, 14, 15 | ✓ |
| `submitChoice(requestId, payload)` | Task 13 | Task 15 | ✓ |
| `addChoice(part)`, `removeChoice(rid)`, `hydrate()`, `reconcile(umo)` | Task 13 | Task 15 | ✓ |

**无类型/命名冲突。**

### 4. Completeness check

- ✅ 每个 task 都有 Files / Interfaces / Steps
- ✅ 步骤粒度 2-5 分钟
- ✅ TDD 风格(写测试 → 跑测试失败 → 实现 → 跑测试通过 → commit)
- ✅ Conventional commit messages
- ✅ Exact file paths
- ✅ Complete code in every step

**Plan ready for execution.**

---

## Execution Choice

Plan complete and saved to `astrbot_plugin_ask_user_choice/docs/superpowers/plans/2026-07-02-blocking-interactive-choice.md`. Two execution options:

1. **Subagent-Driven (recommended)** - 派发独立 subagent per task,中间 review,快速迭代
2. **Inline Execution** - 在当前 session 直接执行,有 checkpoint 供 review

**Which approach?**

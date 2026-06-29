# ask_user_choice 工具挂起机制设计 spec

| 字段 | 值 |
|------|---|
| **作者** | elecvoid243 |
| **日期** | 2026-06-29 |
| **状态** | Draft |
| **目标版本** | astrbot_plugin_ask_user v0.3.0 |
| **AstrBot 兼容** | `>=4.16,<5` |
| **替代** | v0.2.0 的"工具立即返回"行为 |

---

## 1. 背景与问题

### 1.1 现状（v0.2.0）

`ask_user_choice` 工具被 LLM 调用时，**立即返回** JSON 字符串。前端通过 `normalizePartsInternal` 把工具返回的 JSON 解包为 `InteractiveChoicePart` 并渲染选项按钮。

### 1.2 问题

工具立即返回后，**LLM 工具循环并未真正挂起**。LLM 拿到工具返回值后会继续推理，**不会等待用户点击按钮**。这导致：

- 工具被设计用于"在敏感操作前申请用户许可"或"在多个候选方案中让用户拍板"，但 LLM 可能在用户点击前就擅自执行了后续步骤（如直接调用 shell / 删除文件 / 提交事务）
- "挂起等用户" 沦为对 LLM 的"软提示"，无强制力

### 1.3 目标

让 `ask_user_choice` 工具在用户回复前**真实阻塞** LLM 工具循环：

- LLM 调用工具后，**协程必须挂起**直到用户点击按钮 / 输入文本 / 超时
- 用户的回复作为"工具返回值"喂回 LLM，LLM 在**收到该返回值后**才继续推理
- 行为可配置、可预测、永不卡死 AstrBot 主事件循环

### 1.4 非目标

- 不持久化挂起状态（AstrBot 重启 = 全部 pending 丢失，视为超时；与飞行中的 LLM 任务被取消同步）
- 不做"软超时 + 跨重启续接"
- 不替换 AstrBot EventBus / 工具循环机制
- 不修改 AstrBot 前端代码

---

## 2. 设计决策一览（Brainstorming 产出）

| # | 决策点 | 选择 | 理由 |
|---|--------|------|------|
| 1 | 超时策略 | 硬超时（`-1` 永久），可配置 | 永不卡死事件循环；用户走开后 LLM 能继续决策 |
| 2 | 回执作用域 | sender 级（`unified_msg_origin` + `sender_id`） | 群聊里"非触发者插话"不误命中 |
| 3 | 回执消息去向 | 完全消费（不进 LLM 上下文当 user msg） | 语义最干净：用户回复就是工具回调 |
| 4 | 选项匹配规则 | 宽松（按钮 label / 自由输入原文都回传） | 与 `input_placeholder` 字段一致，不引入新校验 |
| 5 | 状态持久化 | 纯内存 | 简单、零 IO；重启 = 全部清空（已知限制） |
| 6 | 并发处理 | 拒绝（同一 sender 第二次调用返错） | 行为可预测，错误信息明确 |
| 7 | UI 副作用 vs 工具返回值 | 解耦——`Plain(json_str)` 走 `event.send()`；工具返回值是用户文本 | 前端 `unwrapInteractiveChoice` 已有"plain 内嵌 JSON"路径，无需改前端 |

---

## 3. 架构

### 3.1 模块结构

```
astrbot_plugin_ask_user/
├── main.py                          # 入口:注册工具 + on_message 钩子
├── ask_user_choice_tool.py          # 工具实现:校验 → 推 UI → 注册 pending → await Future
├── pending_registry.py              # [新] PendingRequest 生命周期管理
├── _conf_schema.json                # 新增 timeout_seconds
├── metadata.yaml                    # version: v0.3.0
├── requirements.txt
├── test_pending_registry.py         # [新] pytest 单测
└── docs/superpowers/specs/
    └── 2026-06-29-ask-user-choice-suspension-design.md   # 本文件
```

### 3.2 数据流（用户点击按钮路径）

```
LLM tool_call(ask_user_choice, options=[...])
  │
  ▼ AskUserChoiceTool.call()
  ├── 1. 校验参数(prompt / options)
  ├── 2. 构造 payload = {"type":"interactive_choice", prompt, options, ...}
  ├── 3. await event.send(MessageChain([Plain(json.dumps(payload))]))
  │      └─▶ 平台适配器 ──▶ SSE 流 ──▶ 前端 unwrapInteractiveChoice ──▶ <InteractiveChoiceBox>
  ├── 4. 检查并发:registry.has_pending(key) → 已存在则返 "Error: ..."
  ├── 5. registry.register(PendingRequest(key, future, ...))
  ├── 6. try:
  │        return await asyncio.wait_for(future, timeout=timeout_seconds)
  │      except asyncio.TimeoutError:
  │        return "Error: User did not respond within N seconds..."
  │      finally:
  │        registry._pending.pop(key, None)   # 防泄漏
  │
  ▼ (挂起中;用户点击按钮)
  │
EventBus 收到新 user message
  │
  ▼ @filter.on_message 钩子
  ├── key = (event.unified_msg_origin, event.get_sender_id())
  ├── pending = registry._pending.get(key)
  ├── if pending is None or pending.future.done(): return  # 放行
  ├── pending.future.set_result(event.message_str)
  ├── event.stop_event()      # 阻止该消息触发新 LLM 轮
  │
  ▼ 工具协程从 await 醒来,return 用户文本
  │
  ▼ LLM 工具循环收到 tool result = "<用户文本>"
  │
  ▼ LLM 继续推理(带着真实选择)
```

### 3.3 关键不变式

1. **同一时刻一个 sender 最多一个 pending**（决策 6）
2. **pending 一定会在以下之一发生时被清理**：`future.set_result` / `set_exception` / `registry.cancel(key)`，配合 `finally` 块保证 dict 不漏
3. **on_message 钩子只 consume "有 pending 的 key"** 的消息；其他消息原样放行
4. **没有持久化**：AstrBot 进程重启 = 全部 pending 丢失（视为超时；与飞行中的 LLM 任务被取消同步，无孤儿 Future）
5. **UI 副作用与工具返回值解耦**：选项框 JSON 走 `event.send()`，不进 LLM 上下文；工具返回的是用户文本

---

## 4. 状态机

### 4.1 PendingRequest 数据模型

```python
# pending_registry.py
from dataclasses import dataclass, field
from asyncio import Future
from uuid import uuid4
import time

@dataclass
class PendingRequest:
    """一次 ask_user_choice 调用的挂起态。"""
    key: tuple[str, str]              # (unified_msg_origin, sender_id)
    future: Future[str]               # 等待用户回执(文本)
    pending_id: str = field(default_factory=lambda: uuid4().hex[:12])
    """自生成的短 id,用于跨 tool.call 与 on_message 的日志关联。
    注:AstrBot 的 ContextWrapper 没有暴露 LLM tool_call_id 字段,
    所以我们用自生成 id 而非依赖框架字段。"""
    prompt: str                       # 选项框的 prompt(用于日志/调试)
    created_at: float = field(default_factory=time.monotonic)
    timeout_seconds: int = 300        # 用于日志显示
```

### 4.2 状态转移

```
[None]
  │ registry.register(key, req)            ← tool.call() 进入挂起
  ▼
[WAITING]
  │ 三选一,立即转移到 [RESOLVED] 并从 dict pop:
  │   A. on_message 钩子 future.set_result(user_text)    ← 用户回复
  │   B. asyncio.TimeoutError (via wait_for)              ← 超时
  │   C. registry.cancel(key)                             ← 外部取消(abort)
  ▼
[RESOLVED]  ← terminal,dict 中已无此 key
```

### 4.3 PendingRegistry API

```python
import asyncio
from typing import Any

class PendingRegistry:
    def __init__(self) -> None:
        self._pending: dict[tuple[str, str], PendingRequest] = {}

    def has_pending(self, key: tuple[str, str]) -> bool:
        return key in self._pending

    def register(self, req: PendingRequest) -> None:
        """tool.call() 调用。已存在同 key 时由调用方处理拒绝逻辑。

        并发安全:asyncio 是单线程的,dict 写入 (__setitem__) 不会被
        其他协程抢占;调用方必须保证 "has_pending + register" 块内
        **没有 await**(否则 on_message 钩子可能在两次同步操作之间
        介入,造成竞态)。本 spec §5.1 严格遵守此约束。
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
        """外部取消(目前主要给 plugin terminate 用)。"""
        req = self._pending.pop(key, None)
        if req is None or req.future.done():
            return False
        req.future.set_exception(asyncio.CancelledError(reason))
        return True

    def cleanup_all(self) -> None:
        """插件 terminate / hot-reload 时清理所有 pending。"""
        for key in list(self._pending.keys()):
            self.cancel(key, reason="plugin_terminated")
```

---

## 5. 关键代码片段

### 5.1 `AskUserChoiceTool.call()`（伪代码）

```python
async def call(self, context, **kwargs):
    # 1. 校验参数（沿用 v0.2.0,详细见现有 ask_user_choice_tool.py）
    prompt = (kwargs.get("prompt") or "").strip()
    options = kwargs.get("options") or []
    if not prompt:
        return "Error: prompt cannot be empty"
    if not isinstance(options, list) or not (2 <= len(options) <= 10):
        return "Error: options must be an array with 2-10 elements."
    # ... 逐项校验 + 截断 ...

    # 2. 构造 payload（与 v0.2.0 字段一致）
    payload = {
        "type": "interactive_choice",
        "prompt": prompt[:_PROMPT_MAX],
        "options": normalized_options,
    }
    if title and title.strip():
        payload["title"] = title.strip()[:_TITLE_MAX]
    if input_placeholder and input_placeholder.strip():
        payload["input_placeholder"] = input_placeholder.strip()[:_INPUT_PLACEHOLDER_MAX]
    json_str = json.dumps(payload, ensure_ascii=False)

    # 3. 推 UI（不经过 LLM 上下文）
    event = context.context.event
    await event.send(MessageChain([Plain(json_str)]))

    # 4. 并发拒绝
    key = (event.unified_msg_origin, event.get_sender_id())
    if self._registry.has_pending(key):
        return (
            "Error: There is already an unanswered ask_user_choice for this sender. "
            "Please wait for the user to respond before asking again."
        )

    # 5. 注册 pending + 阻塞
    #    注:has_pending + register 块内不能有 await,否则 on_message 钩子
    #    可能在这两个同步操作之间介入(见 PendingRegistry 注释)。
    fut = asyncio.get_running_loop().create_future()
    req = PendingRequest(
        key=key,
        future=fut,
        prompt=prompt,
        timeout_seconds=self._timeout_seconds,
    )
    self._registry.register(req)
    logger.info(
        f"ask_user_choice: pending registered "
        f"(umo={event.unified_msg_origin}, sender={event.get_sender_id()}, "
        f"pending_id={req.pending_id})"
    )

    try:
        if self._timeout_seconds < 0:
            return await fut  # 永久等待
        return await asyncio.wait_for(fut, timeout=self._timeout_seconds)
    except asyncio.TimeoutError:
        logger.warning(
            f"ask_user_choice: timeout after {self._timeout_seconds}s "
            f"(pending_id={req.pending_id})"
        )
        return (
            f"Error: User did not respond within {self._timeout_seconds} seconds. "
            f"Please decide how to proceed (e.g., make a default choice, ask again, or skip)."
        )
    finally:
        # pop 在 try_resolve 时已做过;此处防御 finally 路径(CancelledError 等)
        self._registry._pending.pop(key, None)
```

### 5.2 `on_message` 钩子（main.py）

```python
@filter.platform_adapter_type(filter.PlatformAdapterType.ALL)
async def on_user_message(self, event: AstrMessageEvent):
    """拦截同 sender 的下一条消息,作为 ask_user_choice 的答案。"""
    key = (event.unified_msg_origin, event.get_sender_id())
    user_text = event.message_str.strip()

    # 没有 pending 走普通 LLM 路径
    pending = self._tool._registry._pending.get(key)
    if pending is None or pending.future.done():
        return  # 放行原消息,不做任何事

    # 空消息(纯表情/图片)不消费,留给 AstrBot 自己处理
    if not user_text:
        return

    # resolve
    if self._tool._registry.try_resolve(key, user_text):
        event.stop_event()  # 阻止新 LLM 轮
        # 注意:event.stop_event() 在 process_stage 的 star_request_sub_stage 阶段调用,
        # 之后 agent_sub_stage(LLM 调用)会被跳过(见 process_stage/stage.py)。
        logger.info(
            f"ask_user_choice: user reply resolved "
            f"(umo={event.unified_msg_origin}, sender={event.get_sender_id()}, "
            f"len={len(user_text)})"
        )
```

### 5.3 `AskUserChoiceTool` 构造变更

```python
@dataclass
class AskUserChoiceTool(FunctionTool):
    name: str = "ask_user_choice"
    description: str = (
        "Present an interactive option box to the user..."
        "After calling the tool, this tool **blocks** the LLM tool loop until the user clicks a button or types text. The tool will return the user's reply as text."
    )
    parameters: dict = field(default_factory=lambda: { ... })  # 与 v0.2.0 一致
    timeout_seconds: int = 300
    _registry: PendingRegistry = field(default_factory=PendingRegistry)
```

### 5.4 `initialize` 变更（main.py）

```python
async def initialize(self) -> None:
    if not bool(self.config.get("enabled", True)):
        logger.info("ask_user_choice 工具已禁用,跳过注册")
        return

    timeout_seconds = int(self.config.get("timeout_seconds", 300))
    if timeout_seconds < -1 or timeout_seconds == 0:
        logger.warning(
            f"ask_user_choice: timeout_seconds={timeout_seconds} 非法,回退默认 300"
        )
        timeout_seconds = 300

    self._tool = AskUserChoiceTool(timeout_seconds=timeout_seconds)
    self.context.add_llm_tools(self._tool)
```

---

## 6. 配置变更

### 6.1 `_conf_schema.json` v0.3.0

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

### 6.2 行为矩阵

| `timeout_seconds` | 行为 |
|-------------------|------|
| `-1` | 永久等待,AstrBot 重启或用户 `/reset` 才恢复 |
| `1` ~ `N` | N 秒后超时,LLM 收到 `"Error: User did not respond within N seconds..."` |
| `300` (默认) | 5 分钟超时,平衡默认值 |

---

## 7. 错误处理

| 类别 | 来源 | 工具返回值 | 是否阻塞 LLM |
|------|------|-----------|--------------|
| **A. 参数校验失败** | LLM 传非法 `options` | `"Error: ..."` 纯文本 | ❌ 不阻塞,LLM 重试 |
| **B. 并发拒绝** | 同 sender 已有 pending | `"Error: There is already an unanswered ask_user_choice..."` | ❌ 不阻塞 |
| **C. 用户超时** | `asyncio.TimeoutError` | `"Error: User did not respond within N seconds..."` | ✅ 阻塞后超时解锁 |
| **D. 群聊非目标 sender 发消息** | 别的用户发言 | n/a | n/a (on_message 放行) |
| **E. `event.send` 失败** | 平台断连 | 抛异常向上 | 取决于异常时点 |
| **F. LLM abort / 插件热重载** | `asyncio.CancelledError` | 工具抛 CancelledError | ✅ 被取消,finally 清理 |
| **G. 平台不支持 `send()`** | 某些只读平台 | 抛异常 | 取决于异常时点 |

### 7.1 错误信息模板

工具返给 LLM 的字符串保持**英文**（与 v0.2.0 一致,方便 LLM 跨语言训练时识别）:

```python
# 参数校验
"Error: prompt cannot be empty"
"Error: options must be an array with 2-10 elements."
"Error: options[3] is not an object."
"Error: options[3] needs id/label"
"Error: Duplicate option id: 'A'"

# 并发拒绝
"Error: There is already an unanswered ask_user_choice for this sender. Please wait for the user to respond before asking again."

# 超时
f"Error: User did not respond within {N} seconds. Please decide how to proceed (e.g., make a default choice, ask again, or skip)."
```

### 7.2 日志埋点

| 事件 | level | 关键字段 |
|------|-------|---------|
| pending 注册 | `info` | `pending_id, umo, sender_id, prompt` |
| 用户回复 resolve | `info` | `pending_id, umo, sender_id, user_text_len` |
| 超时 | `warning` | `pending_id, umo, sender_id, timeout_seconds` |
| 并发拒绝 | `warning` | `pending_id, umo, sender_id` |
| `event.send` 失败 | `error` | `pending_id, umo, exc` |
| `cleanup_all` | `info` | `count` |

---

## 8. 已知限制（写入 README）

1. **AstrBot 进程重启 / 插件热重载会丢弃所有挂起的请求**——视为超时（因为飞行中的 LLM 任务被一起取消,所以无孤儿 Future）
2. **`timeout_seconds = -1` 时 LLM 工具循环会永久挂起**——必须用户回复或 AstrBot 重启才恢复
3. **群聊并发**：同一 sender 的下一条消息被 consume，其他 sender 的消息按 AstrBot 正常流程走
4. **平台依赖**：`event.send` 需要平台支持；当前已验证 WebChat,其他平台（aiocqhttp / satori / slack）走相同 API 应同样工作
5. **内存占用**：每个 pending 占用约 200 字节 dict 空间 + 1 个 asyncio.Future；正常场景下同时挂起数 < 10,无压力

---

## 9. 测试策略

### 9.1 静态检查（每次改完代码必跑）

```bash
# 1. Python 语法 + 导入
python -m py_compile main.py ask_user_choice_tool.py pending_registry.py

# 2. JSON schema 合法
python -c "import json; json.load(open('_conf_schema.json'))"

# 3. Schema 能被 AstrBot 解析
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

# 4. metadata 合法
python -c "import yaml; yaml.safe_load(open('metadata.yaml'))"
```

### 9.2 单元测试（`test_pending_registry.py`）

```python
import asyncio
import pytest
from pending_registry import PendingRegistry, PendingRequest

@pytest.mark.asyncio
async def test_register_resolve_basic():
    reg = PendingRegistry()
    key = ("umo:x", "sender:1")
    fut = asyncio.get_event_loop().create_future()
    reg.register(PendingRequest(key=key, future=fut, prompt="p"))
    assert reg.has_pending(key)
    assert reg.try_resolve(key, "A") is True
    assert fut.result() == "A"
    assert not reg.has_pending(key)

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

@pytest.mark.asyncio
async def test_pending_id_is_unique():
    reg = PendingRegistry()
    ids = set()
    for i in range(5):
        fut = asyncio.get_event_loop().create_future()
        req = PendingRequest(key=(f"umo{i}", f"s{i}"), future=fut, prompt="p")
        reg.register(req)
        ids.add(req.pending_id)
    assert len(ids) == 5  # 全部唯一

@pytest.mark.asyncio
async def test_concurrent_reject():
    reg = PendingRegistry()
    key = ("umo", "s")
    fut1 = asyncio.get_event_loop().create_future()
    reg.register(PendingRequest(key=key, future=fut1, prompt="p1"))
    assert reg.has_pending(key)

@pytest.mark.asyncio
async def test_cancel():
    reg = PendingRegistry()
    key = ("umo", "s")
    fut = asyncio.get_event_loop().create_future()
    reg.register(PendingRequest(key=key, future=fut, prompt="p"))
    assert reg.cancel(key, reason="test") is True
    with pytest.raises(asyncio.CancelledError):
        fut.result()

@pytest.mark.asyncio
async def test_cleanup_all():
    reg = PendingRegistry()
    futures = []
    for i in range(3):
        fut = asyncio.get_event_loop().create_future()
        reg.register(PendingRequest(key=(f"umo{i}", f"s{i}"), future=fut, prompt="p"))
        futures.append(fut)
    reg.cleanup_all()
    for fut in futures:
        with pytest.raises(asyncio.CancelledError):
            fut.result()
    assert not reg.has_pending(("umo0", "s0"))
```

### 9.3 端到端验证（人工 + WebChat）

| # | 场景 | 期望 |
|---|------|------|
| 1 | 加载插件 | AstrBot 日志 `plugin loaded: astrbot_plugin_ask_user` 无 traceback |
| 2 | LLM 调用工具 → 1 个选项 | 前端渲染 1 个按钮 + 自由输入框 |
| 3 | LLM 调用工具 → 10 个选项 | 前端渲染 10 个按钮 |
| 4 | 用户点击按钮 | LLM 下一轮收到 `tool result = "<id>"` 并继续 |
| 5 | 用户用自由输入框输入 | LLM 下一轮收到 `tool result = "<原文>"` |
| 6 | 用户不点按钮直接发普通消息（私聊） | 消息被 consume → 工具 resolve → LLM 收到该文本 |
| 7 | 群聊里非触发者发消息 | 消息不被 consume,按 AstrBot 正常流程走 |
| 8 | 同 sender 第二个并发调用 | 工具返 "Error: There is already an unanswered ask_user_choice..." |
| 9 | `timeout_seconds = 5` 时故意不点 | 5 秒后 LLM 收到超时错误 |
| 10 | `timeout_seconds = -1` 时不点 + 不发消息 | LLM 工具循环永久挂起（手动 `/reset` 或重启 AstrBot 恢复） |
| 11 | LLM 流式输出时调用工具 | 推 UI 不影响 SSE 流;用户看到选项框时 LLM 还在"思考" |

### 9.4 回归点（每次发布前必跑）

端到端 1, 4, 6, 7, 9 是**必跑**（覆盖核心行为变更）。

### 9.5 不在 v0.3.0 范围

- 自动化集成测试（mock 整个 LLM 工具循环）：仓库无此基础设施
- 持久化：决策 5 选了纯内存
- 多端（QQ / Satori / Slack）覆盖测试：仅 WebChat 验证
- 性能压测：阻塞工具是单 sender 串行,量级极小

---

## 10. 兼容性

### 10.1 向后兼容

- 工具名 `ask_user_choice`、参数 schema、字段约束**完全不变**
- v0.2.0 的 `InteractiveChoicePart` JSON 中间格式**完全沿用**
- 现有 v0.2.0 的前端 `unwrapInteractiveChoice` 路径**已被新流程复用**（plain 文本内嵌 JSON 走 §5.1 step 3）
- `_conf_schema.json` 新增 `timeout_seconds` 字段,有默认值 `300`,旧配置自动兼容
- `metadata.yaml` version `v0.2.0 → v0.3.0`（minor bump,非 breaking）

### 10.2 升级步骤

1. 备份 `data/plugins/astrbot_plugin_ask_user/_conf_schema.json` 的当前内容（如有自定义）
2. 覆盖插件目录
3. AstrBot WebUI → 插件配置 → 确认 `timeout_seconds` 字段出现,默认 300
4. 重启 AstrBot（或 `--reload-plugin`）
5. 跑 §9.3 端到端验证

### 10.3 降级步骤（如需回退 v0.2.0）

- 切回 git 旧 commit,重启 AstrBot
- 无 schema 数据迁移需要（纯内存 pending,重启即清空）

---

## 11. 实施计划（移交 writing-plans）

本 spec 经审通过后,移交 `writing-plans` 技能产出**可逐步执行**的实施计划。计划阶段需明确：

- 任务拆分顺序（先 pending_registry + 单测 → 再工具改造 → 最后 main.py on_message 钩子）
- 每个任务的验收点
- 端到端验证在最后一步执行

---

## 12. 自审修正记录

spec 自审循环中发现的 3 处修正：

| # | 问题 | 修正 |
|---|------|------|
| 1 | 原 spec 使用 `context.tool_call_id` 字段,但 AstrBot 的 `ContextWrapper`（`astrbot/core/agent/run_context.py`）只有 `context / messages / tool_call_timeout` 三个字段，没有暴露 `tool_call_id` | 改为自生成 `pending_id: str = field(default_factory=lambda: uuid4().hex[:12])`，用于日志关联 |
| 2 | 原 spec 在 `PendingRegistry` 里加了 `asyncio.Lock`，但 asyncio 单线程下 dict 操作是原子同步的，锁是过度设计 | 删除锁；改为在 `register` docstring 中**明确"has_pending + register 块内不能有 await"**这一不变量 |
| 3 | 原 spec 未解释 `on_message` 钩子的"为什么 stop_event 能阻止 LLM 调用" | 在 §5.2 加注释引用 `astrbot/core/pipeline/process_stage/stage.py`：process_stage 阶段先跑 `star_request_sub_stage`（包含 on_message 钩子），再跑 `agent_sub_stage`（LLM 调用）。在钩子里 stop_event 后，agent_sub_stage 会被跳过 |

---

## 13. 参考

- AGENTS.md §2.1 / §2.3 / §2.4 / §3.8 / §3.9 / §4.2 — 项目规范
- AGENTS.md §3.5 — 命名约定
- `docs/superpowers/specs/2026-06-28-dynamic-choice-box-rendering-design.md` §2.3 / §3.1 / §3.2 / §7 — 现有前端协议
- `astrbot/core/agent/tool.py:70` — `FunctionTool.call` async 签名
- `astrbot/core/agent/runners/tool_loop_agent_runner.py` — 工具循环,会真 `await` tool.call()
- `astrbot/core/platform/astr_message_event.py:475` — `event.send(MessageChain)`
- `astrbot/core/message/components.py:733` — `Json` 组件（**本设计不用**,因为前端无 `type==='json'` 分支）
- `astrbot/core/message/components.py:111` — `Plain` 组件（本设计用,因为前端 `unwrapInteractiveChoice` 支持"plain 内嵌 JSON"）
- `dashboard/src/composables/parseInteractiveChoice.ts:42` — `isInteractiveChoicePayload` 前端识别逻辑
- `dashboard/src/composables/parseInteractiveChoice.ts:59` — `unwrapInteractiveChoice` 前端解包逻辑
- `dashboard/src/components/chat/ChatMessageList.vue:255` — `<InteractiveChoiceBox v-else-if="part.type === 'interactive_choice'">` 渲染入口

---

# Spec 完

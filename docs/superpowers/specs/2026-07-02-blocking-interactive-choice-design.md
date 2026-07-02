# AstrBot ask_user_choice 真阻塞式重构设计

> **Author**: elecvoid243
> **Date**: 2026-07-02
> **Spec version**: v1.0
> **Status**: Draft (待用户审阅)
> **Previous spec**: `2026-06-28-dynamic-choice-box-rendering-design.md` (v0.3 软阻塞,本 spec 将其废弃)

---

## 1. 背景与目标

### 1.1 现状问题 (v0.3 软阻塞)

`astrbot_plugin_ask_user_choice` v0.3 通过**"软阻塞"** 模拟 HITL 体验:

1. 工具 `call()` 返回 `{"type":"interactive_choice", ...}` JSON
2. 前端 `unwrapInteractiveChoice` 解析为 `InteractiveChoicePart`,渲染选项框
3. 用户选择 → emit 文本 → 父组件把文本作为**下一轮 user message** 传回 LLM
4. LLM 在**下一个 turn** 才看到选择结果
5. "调完即停" 依赖 `description` 硬话术 + `@filter.on_llm_request()` 注入 system_prompt,**不可靠**

### 1.2 目标 (v1.0 真阻塞)

- **真 `await`**:工具内部 `await Future`,LLM 整个 turn 挂起直到用户响应
- **直接 tool result**:用户选择直接 return 给 LLM(不是新 user message)
- **跨刷新持久化**:页面刷新/切 tab 后,选项框 UI 仍能恢复
- **完全替换 v0.3 软阻塞**:旧代码全部清理,不留兼容性包袱

### 1.3 范围

| 维度 | 范围 |
|------|------|
| **平台** | 仅 WebChat (Dashboard 浏览器) |
| **改动边界** | 仅 `astrbot_plugin_ask_user_choice` 插件 + Dashboard 前端,**不改 AstrBot core** |
| **breaking change** | 全部接受,一次性发布 v1.0.0 |

---

## 2. 决策摘要

| # | 决策 | 选择 | 备注 |
|---|------|------|------|
| 1 | 目标平台 | 仅 WebChat | 非 webchat 会话工具直接返回错误 |
| 2 | 交互类型 | 单选 + 自由文本兜底 | 选项 2-10 个,带 description 可选 |
| 3 | 用户响应通道 | REST 端点 | `POST /api/chat/interactive-choice/<request_id>` |
| 4 | 超时/取消 | 工具自治 | `asyncio.wait_for`,超时返回自定义 fallback |
| 5 | 改动范围 | 仅插件 + 前端 | 不动 AstrBot core |
| 6 | 前端持久化 | localStorage + GET pending | localStorage 瞬时显示,GET reconcile 一致性 |
| 7 | REST URL 形态 | `/api/chat/interactive-choice/<request_id>` | legacy `/api/*`,**不挂 v1** |
| 8 | 鉴权 | Dashboard JWT + UMO strict match | 解析失败返回 403 |
| 9 | SSE 协议 | 顶层 `type:"interactive_choice"` | 不再嵌 plain 文本或 tool_call |
| 10 | 持久化策略 | 不持久化,纯内存 + 超时兜底 | 后端重启后所有 pending 在 5 分钟内自动清 |
| 11 | request_id 传递 | emit 第二参数 | `(requestId, payload)` 显式传递 |
| 12 | 乐观更新 | 乐观 + 失败回滚 + SSE 幂等 | 失败不删本地,重试;成功立即隐藏 |

---

## 3. 架构总览

### 3.1 组件图

```
┌────────────────────────────────────────────────────────────────────────┐
│            astrbot_plugin_ask_user_choice (v1.0 真阻塞)                  │
│                                                                        │
│  AskUserChoiceTool.call(context, **kwargs) → str:                       │
│    1. 守卫:非 webchat 会话 → return error                              │
│    2. 校验参数 → 构造 InteractiveChoiceSpec                            │
│    3. 解析 umo,生成 request_id = uuid4()                                │
│    4. 创建 future,registry.add(rid, umo, future, spec, ttl)            │
│    5. webchat_back_queue.put(interactive_choice 事件)                   │
│    6. await asyncio.wait_for(future, timeout=N)                        │
│    7. return _format_choice_for_llm(user_choice, spec)                 │
│    8. (finally) registry.remove(rid)                                    │
│                                                                        │
│  InteractiveChoiceRegistry (单例, in-memory)                            │
│    _pending: dict[rid, PendingChoice]                                  │
│    _by_umo: dict[umo, set[rid]]                                        │
│    add / resolve / remove / list_pending_for_umo / _gc_loop            │
│                                                                        │
│  interactive_choice_api.py (FastAPI routes, legacy /api/*)             │
│    POST /api/chat/interactive-choice/<request_id>                       │
│    GET  /api/chat/interactive-choice/pending?session_id=<umo>           │
└────────────────────────────────────────────────────────────────────────┘
                │
                │ SSE + REST
                ▼
┌────────────────────────────────────────────────────────────────────────┐
│                       Dashboard Frontend (Vue 3)                        │
│                                                                        │
│  useInteractiveChoiceStore (Pinia)                                     │
│    activeChoices: { [request_id]: InteractiveChoicePart }              │
│    addChoice / removeChoice / hydrate / reconcile / submitChoice        │
│    localStorage: 'astrbot-interactive-choice-pending'                   │
│                                                                        │
│  ChatMessageList.vue:                                                   │
│    - onMounted: store.hydrate() + reconcile(umo)                       │
│    - onActivated: store.reconcile(umo)                                 │
│    - SSE listener: case 'interactive_choice' → store.addChoice         │
│                    case 'interactive_choice_resolved' → store.remove   │
│                                                                        │
│  InteractiveChoiceBox.vue:                                              │
│    props: { part, isDark, isIgnored }                                  │
│    emit('submit', requestId, { choice_id, free_text })                 │
└────────────────────────────────────────────────────────────────────────┘
```

### 3.2 时序图(成功路径)

```
LLM       Tool       Registry    BackQueue    SSE     Frontend   REST
 │         │            │          │          │          │          │
 │ tool_c()│            │          │          │          │          │
 ├────────►│            │          │          │          │          │
 │         │ add(fut)   │          │          │          │          │
 │         ├───────────►│          │          │          │          │
 │         │ put(req)   │          │          │          │          │
 │         ├─────────────────────►│          │          │          │
 │         │            │          │ listener │          │          │
 │         │            │          ├─────────►│          │          │
 │         │            │          │          │ evt      │          │
 │         │            │          │          ├─────────►│          │
 │         │            │          │          │          │ render   │
 │         │            │          │          │          │ UI       │
 │         │            │          │          │          │          │
 │         │ await wait_for(future, 300s)   │  user     │          │
 │         │            │          │          │  picks A │          │
 │         │            │          │          │          │ POST     │
 │         │            │          │          │          ├─────────►│
 │         │            │ resolve  │          │          │          │
 │         │            │◄─────────┼──────────┼──────────┼──────────┤
 │         │            │ set_res(A)         │          │          │
 │         │            │          │ put(resolved)      │          │
 │         │            │          ├─────────►│          │          │
 │         │            │          │          │ evt      │          │
 │         │            │          │          ├─────────►│          │
 │         │            │          │          │          │ hide UI  │
 │         │            │          │          │          │          │
 │         │ return "A" │          │          │          │          │
 │         │◄───────────┼──────────┼──────────┼──────────┼──────────┤
 │ got "A" │            │          │          │          │          │
 │◄────────┤            │          │          │          │          │
 │         │            │          │          │          │          │
 │ (继续 LLM turn)     │          │          │          │          │
```

### 3.3 关键不变式

- **同一 request_id 唯一**:后端 uuid4,前端只信任后端给的
- **request_id 必填**:`InteractiveChoicePart.request_id` 在新机制下是必填,旧 v0.3 JSON(无 request_id)被 `validateInteractiveChoice` 判非法 → 降级 unknown-part
- **webchat-only**:工具内 early return 拒绝非 webchat 会话,杜绝跨平台混乱
- **不持久化到 disk**:纯内存,后端崩溃 = 等待中的工具在 5 分钟内自动超时

---

## 4. 后端实现

### 4.1 AskUserChoiceTool

**文件**:`astrbot_plugin_ask_user_choice/ask_user_choice_tool.py` (完全重写)

```python
from __future__ import annotations
import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from astrbot.api import FunctionTool
from .interactive_choice_registry import registry, PendingChoice

if TYPE_CHECKING:
    from astrbot.core.agent.run_context import ContextWrapper


_PROMPT_MAX = 200
_TITLE_MAX = 30
_LABEL_MAX = 30
_DESCRIPTION_MAX = 200
_INPUT_PLACEHOLDER_MAX = 60
_OPTIONS_MIN = 2
_OPTIONS_MAX = 10


@dataclass
class AskUserChoiceTool(FunctionTool):
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
            "prompt": {"type": "string", "description": "Question displayed at the top of the option box"},
            "options": {
                "type": "array",
                "minItems": 2, "maxItems": 10,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "Unique option ID (e.g. A/B/C)"},
                        "label": {"type": "string", "description": "Button text"},
                        "description": {"type": "string", "description": "Optional detail"},
                    },
                    "required": ["id", "label"],
                },
            },
            "title": {"type": "string", "description": "Optional dialog title"},
            "input_placeholder": {"type": "string", "description": "Free-text input placeholder"},
        },
        "required": ["prompt", "options"],
    })

    async def call(self, context: ContextWrapper, **kwargs: Any) -> str:
        # ── 1. 平台守卫 ──
        umo = context.context.event.unified_msg_origin
        if not umo.startswith("webchat:"):
            return (
                "Error: ask_user_choice is only supported in the webchat dashboard. "
                f"Current platform: {umo.split(':', 1)[0]}. "
                "Please open the dashboard to make your selection."
            )

        # ── 2. 参数校验 + 截断 ──
        spec_or_error = self._validate_and_build_spec(kwargs)
        if isinstance(spec_or_error, str):
            return spec_or_error
        spec = spec_or_error

        # ── 3. 配置加载 ──
        config = self._load_tool_config(context)
        timeout_s = int(config.get("timeout_seconds", 300))
        fallback = config.get(
            "timeout_fallback_message",
            f"[User did not respond within {{timeout}} seconds. Please proceed with a reasonable default.]",
        ).format(timeout=timeout_s)
        max_concurrent = int(config.get("max_concurrent_pending", 32))

        # ── 4. 并发上限检查 ──
        if len(registry._pending) >= max_concurrent:
            return (
                f"Error: too many concurrent interactive choices (max {max_concurrent}). "
                "Please wait for some to resolve."
            )

        # ── 5. 注册 + 推送 SSE 事件 ──
        request_id = str(uuid.uuid4())
        loop = asyncio.get_event_loop()
        future: asyncio.Future[dict] = loop.create_future()
        expires_at = time.time() + timeout_s

        registry.add(
            request_id=request_id,
            umo=umo,
            future=future,
            spec=spec,
            created_at=time.time(),
            timeout_at=expires_at,
        )

        try:
            await self._push_to_webchat_back_queue(
                request_id=request_id, umo=umo, spec=spec, expires_at=expires_at,
            )
        except Exception as exc:
            registry.remove(request_id)
            return f"Error: failed to push interactive choice to frontend: {exc}"

        # ── 6. 真阻塞 ──
        try:
            user_choice = await asyncio.wait_for(future, timeout=timeout_s)
        except asyncio.TimeoutError:
            return fallback
        except asyncio.CancelledError:
            return "[User input was cancelled]"
        finally:
            registry.remove(request_id)

        # ── 7. 推 resolved 广播 ──
        try:
            await self._push_resolved_to_back_queue(
                request_id=request_id, umo=umo, reason="submitted",
            )
        except Exception:
            pass  # 广播失败不影响主流程

        # ── 8. 格式化为 LLM 可见字符串 ──
        return self._format_choice_for_llm(user_choice, spec)

    def _validate_and_build_spec(self, kwargs: dict) -> dict | str:
        """返回 spec dict 或错误字符串(同 v0.3 校验逻辑)。"""
        prompt = (kwargs.get("prompt") or "").strip()
        if not prompt:
            return "Error: prompt cannot be empty"
        options = kwargs.get("options") or []
        if not isinstance(options, list) or not (_OPTIONS_MIN <= len(options) <= _OPTIONS_MAX):
            return f"Error: options must be an array with {_OPTIONS_MIN}-{_OPTIONS_MAX} elements."

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

    async def _push_to_webchat_back_queue(
        self, request_id: str, umo: str, spec: dict, expires_at: float,
    ) -> None:
        from astrbot.core.platform.sources.webchat.webchat_queue_mgr import webchat_queue_mgr
        # umo: webchat:FriendMessage:webchat!user!session_id
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

    def _format_choice_for_llm(self, user_choice: dict, spec: dict) -> str:
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

    def _load_tool_config(self, context: ContextWrapper) -> dict:
        """从插件 config 读配置。如果无法拿到,返回默认。"""
        try:
            return context.context.get_config or {}
        except Exception:
            return {}
```

### 4.2 InteractiveChoiceRegistry

**文件**:`astrbot_plugin_ask_user_choice/interactive_choice_registry.py` (新建)

```python
from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PendingChoice:
    request_id: str
    umo: str
    future: asyncio.Future
    spec: dict
    created_at: float
    timeout_at: float
    cleanup_done: bool = False


class InteractiveChoiceRegistry:
    """In-memory 等待池,单例。"""

    def __init__(self) -> None:
        self._pending: dict[str, PendingChoice] = {}
        self._by_umo: dict[str, set[str]] = {}
        self._lock = asyncio.Lock()
        self._gc_task: asyncio.Task | None = None

    def add(
        self, request_id: str, umo: str, future: asyncio.Future,
        spec: dict, created_at: float, timeout_at: float,
    ) -> None:
        self._pending[request_id] = PendingChoice(
            request_id=request_id, umo=umo, future=future,
            spec=spec, created_at=created_at, timeout_at=timeout_at,
        )
        self._by_umo.setdefault(umo, set()).add(request_id)
        self._ensure_gc()

    def resolve(self, request_id: str, payload: dict) -> bool:
        pending = self._pending.get(request_id)
        if pending is None or pending.cleanup_done:
            return False
        if pending.future.done():
            return False
        pending.future.set_result(payload)
        return True

    def remove(self, request_id: str) -> None:
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

    def list_pending_for_umo(self, umo: str) -> list[dict]:
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

    def stats(self) -> dict:
        return {
            "total_pending": len(self._pending),
            "by_umo": {umo: len(ids) for umo, ids in self._by_umo.items()},
        }

    def _ensure_gc(self) -> None:
        if self._gc_task is not None and not self._gc_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._gc_task = loop.create_task(self._gc_loop(), name="interactive_choice_gc")

    async def _gc_loop(self) -> None:
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
        """优雅关闭:cancel 所有 future 和 GC task。"""
        for pending in list(self._pending.values()):
            if not pending.future.done():
                pending.future.cancel()
        self._pending.clear()
        self._by_umo.clear()
        if self._gc_task and not self._gc_task.done():
            self._gc_task.cancel()
            try:
                await self._gc_task
            except (asyncio.CancelledError, Exception):
                pass


# 全局单例
registry = InteractiveChoiceRegistry()
```

### 4.3 REST 端点

**文件**:`astrbot_plugin_ask_user_choice/interactive_choice_api.py` (新建)

```python
from __future__ import annotations
import json
import logging
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from astrbot.dashboard.api.auth import require_dashboard_user
from astrbot.dashboard.responses import ApiError, ok
from .interactive_choice_registry import registry

logger = logging.getLogger(__name__)
router = APIRouter()


def _extract_username_from_umo(umo: str) -> str:
    """从 webchat umo 提取 dashboard username。失败返回 ''。"""
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


@router.post("/api/chat/interactive-choice/<request_id>")
async def submit_interactive_choice(
    request_id: str,
    request: Request,
    username: str = Depends(require_dashboard_user),
):
    """用户提交选择。"""
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


@router.get("/api/chat/interactive-choice/pending")
async def list_pending(
    request: Request,
    session_id: str = "",
    username: str = Depends(require_dashboard_user),
):
    """列出某 umo 下所有仍 pending 的 interactive_choice。"""
    if not session_id:
        raise ApiError("Missing key: session_id", status_code=400)
    if not session_id.startswith("webchat:"):
        raise ApiError("Only webchat sessions supported", status_code=400)

    expected = _extract_username_from_umo(session_id)
    if not expected or expected != username:
        raise ApiError("Not authorized", status_code=403)

    pending_list = registry.list_pending_for_umo(session_id)
    # 转换为完整 InteractiveChoicePart(前端期望)
    parts = []
    for item in pending_list:
        spec = item["spec"].copy()
        spec["request_id"] = item["request_id"]
        spec["expires_at"] = item["timeout_at"]
        parts.append(spec)
    return ok({"pending": parts})
```

**挂载到 Dashboard**:在插件 `initialize()` 中:
```python
from astrbot.core.dashboard.server import APP  # AstrBotDashboard.app
APP._app.include_router(router)  # FastAPI app 上加 router
```

> **注**:实际挂载方式需要确认 `APP` 是否可导入;若不可,用 `FastAPIAppAdapter.add_url_rule` 风格单独注册。

### 4.4 插件 main.py 改造

**文件**:`astrbot_plugin_ask_user_choice/main.py` (重写)

```python
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
    def __init__(self, context: star.Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.config = config

    async def initialize(self) -> None:
        enabled = bool(self.config.get("enabled", True))
        if not enabled:
            logger.info("ask_user_choice 工具已禁用")
            return

        # 1. 注册工具
        self.context.add_llm_tools(AskUserChoiceTool(self.config))

        # 2. 注册 REST 端点
        # (实际挂载代码根据 #4.3 注说明调整)
        try:
            from astrbot.core.dashboard.server import APP
            if APP is not None:
                APP.include_router(api_router)
                logger.info("ask_user_choice: REST 端点已注册")
        except Exception as e:
            logger.warning(f"ask_user_choice: REST 端点注册失败:{e}")

    async def terminate(self) -> None:
        # 关闭 Registry:cancel 所有 pending + GC task
        await registry.shutdown()
```

---

## 5. 前端实现

### 5.1 InteractiveChoicePart schema 扩展

**文件**:`dashboard/src/composables/parseInteractiveChoice.ts` (重写)

```typescript
// Author: elecvoid243
// Date: 2026-07-02
// Spec: docs/superpowers/specs/2026-07-02-blocking-interactive-choice-design.md §5.1
//
// 纯函数:把后端 push 的 SSE interactive_choice 事件 → InteractiveChoicePart
// 翻译逻辑。v1.0 不再解 plain 文本/拆 tool_call,事件走顶层 type。

export interface InteractiveChoiceOption {
  id: string;
  label: string;
  description?: string;
  /** 旧 plugin 字段(v0.3 schema 兼容),新代码忽略 */
  value?: string;
}

export interface InteractiveChoicePart {
  type: "interactive_choice";
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
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const obj = value as Record<string, unknown>;
  return obj.type === "interactive_choice";
}

export function validateInteractiveChoice(obj: unknown): boolean {
  if (!isInteractiveChoicePayload(obj)) return false;
  const part = obj as Record<string, unknown>;
  if (typeof part.request_id !== "string" || !part.request_id.trim()) return false;
  if (typeof part.prompt !== "string" || !part.prompt.trim()) return false;
  if (!Array.isArray(part.options) || part.options.length < 2) return false;
  const seen = new Set<string>();
  for (const opt of part.options) {
    if (!opt || typeof opt !== "object") return false;
    const o = opt as Record<string, unknown>;
    if (typeof o.id !== "string" || !o.id.trim()) return false;
    if (typeof o.label !== "string" || !o.label.trim()) return false;
    if (seen.has(o.id)) return false;
    seen.add(o.id);
  }
  return true;
}

export function truncateInteractiveChoice(part: InteractiveChoicePart): InteractiveChoicePart {
  const LIMITS = { PROMPT_MAX: 200, TITLE_MAX: 30, LABEL_MAX: 30, DESC_MAX: 200, PLACEHOLDER_MAX: 60 };
  let mutated = false;
  const out: InteractiveChoicePart = { ...part };
  if (out.prompt.length > LIMITS.PROMPT_MAX) { out.prompt = out.prompt.slice(0, LIMITS.PROMPT_MAX); mutated = true; }
  if (typeof out.title === "string" && out.title.length > LIMITS.TITLE_MAX) { out.title = out.title.slice(0, LIMITS.TITLE_MAX); mutated = true; }
  if (typeof out.input_placeholder === "string" && out.input_placeholder.length > LIMITS.PLACEHOLDER_MAX) {
    out.input_placeholder = out.input_placeholder.slice(0, LIMITS.PLACEHOLDER_MAX); mutated = true;
  }
  if (Array.isArray(out.options)) {
    const newOpts: InteractiveChoiceOption[] = [];
    for (const opt of out.options) {
      const o: InteractiveChoiceOption = { ...opt };
      if (o.label.length > LIMITS.LABEL_MAX) { o.label = o.label.slice(0, LIMITS.LABEL_MAX); mutated = true; }
      if (typeof o.description === "string" && o.description.length > LIMITS.DESC_MAX) {
        o.description = o.description.slice(0, LIMITS.DESC_MAX); mutated = true;
      }
      newOpts.push(o);
    }
    out.options = newOpts;
  }
  return mutated ? out : part;
}

export function getOptionSubmitText(opt: InteractiveChoiceOption): string {
  if (typeof opt.value === "string" && opt.value.length > 0) return opt.value;
  const id = typeof opt.id === "string" ? opt.id : "";
  const label = typeof opt.label === "string" ? opt.label : "";
  if (id && label) return `${id}. ${label}`;
  if (label) return label;
  return id;
}
```

> **删除**:`unwrapInteractiveChoice` / `extractAskUserChoiceFromToolCall` / `MaybePlainPart` / `MaybeToolCall` 等仅 v0.3 使用的辅助类型和函数。

### 5.2 Pinia store

**文件**:`dashboard/src/stores/interactiveChoice.ts` (新建)

```typescript
// Author: elecvoid243
// Date: 2026-07-02
// Spec: docs/superpowers/specs/2026-07-02-blocking-interactive-choice-design.md §5.2
import { defineStore } from 'pinia';
import { httpClient } from '@/api/http';
import type { ApiEnvelope } from '@/api/v1';
import type { InteractiveChoicePart } from '@/composables/parseInteractiveChoice';

const STORAGE_KEY = 'astrbot-interactive-choice-pending';

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
    async submitChoice(requestId: string, payload: { choice_id: string; free_text: string }) {
      const res = await httpClient.post<ApiEnvelope<any>>(
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

### 5.3 InteractiveChoiceBox 改造

**文件**:`dashboard/src/components/chat/message_list_comps/InteractiveChoiceBox.vue` (改 emit)

```vue
<script setup lang="ts">
// ... 同 v0.3 状态机 (pending / submitted_via_option / submitted_via_input / ignored)
import { computed, ref } from "vue";
import { useModuleI18n } from "@/i18n/composables";
import {
  getOptionSubmitText,
  type InteractiveChoicePart,
  type InteractiveChoiceOption,
} from "@/composables/parseInteractiveChoice";

const props = defineProps<{
  part: InteractiveChoicePart;
  isDark?: boolean;
  isIgnored?: boolean;
}>();

// v1.0:emit 改为 (requestId, payload) 而非 text
const emit = defineEmits<{
  submit: [requestId: string, payload: { choice_id: string; free_text: string }];
}>();

// ... (其他 state 保持 v0.3 不变)

function onOptionClick(opt: InteractiveChoiceOption) {
  if (state.value !== "pending") return;
  emit("submit", props.part.request_id, { choice_id: opt.id, free_text: "" });
  submittedValue.value = getOptionSubmitText(opt);
  submittedKind.value = "option";
  submittedOption.value = opt;
}

function onInputSubmit() {
  const text = freeText.value.trim();
  if (!text || state.value !== "pending") return;
  emit("submit", props.part.request_id, { choice_id: "__free_text__", free_text: text });
  submittedValue.value = text;
  submittedKind.value = "input";
}
</script>
```

### 5.4 ChatMessageList 改造

**文件**:`dashboard/src/components/chat/ChatMessageList.vue`

**变更点**:
1. `onInteractiveChoiceSubmit` 改签名,调 `interactiveChoiceStore.submitChoice`
2. SSE 监听器新增 `interactive_choice` / `interactive_choice_resolved` 事件
3. `onMounted` + `onActivated` 触发 hydrate + reconcile

```typescript
import { useInteractiveChoiceStore } from '@/stores/interactiveChoice';

const store = useInteractiveChoiceStore();
const currentUmo = computed(() => buildWebchatUmoDetails(currentSessionId.value).umo);

onMounted(() => {
  store.hydrate();
  store.reconcile(currentUmo.value);
});
onActivated(() => {
  store.reconcile(currentUmo.value);
});

// SSE listener(在 useMessages.ts 或 ChatMessageList 内部,根据现有架构)
function onSseEvent(event: { type: string; data: any }) {
  switch (event.type) {
    case 'interactive_choice': {
      const part: InteractiveChoicePart = {
        type: 'interactive_choice',
        request_id: event.data.request_id,
        ...event.data.spec,
        expires_at: event.data.expires_at,
      };
      store.addChoice(part);
      break;
    }
    case 'interactive_choice_resolved': {
      store.removeChoice(event.data.request_id);
      break;
    }
    // ... 其他事件保持原样
  }
}

async function onInteractiveChoiceSubmit(
  requestId: string,
  payload: { choice_id: string; free_text: string },
) {
  try {
    await store.submitChoice(requestId, payload);
  } catch (e) {
    console.error('[interactiveChoice] submit failed:', e);
    // 失败:不删本地,UI 保持,用户可重试
  }
}
```

### 5.5 渲染集成

`InteractiveChoiceBox` 的挂载点(现有 `v-else-if="part.type === 'interactive_choice'"`)需要从"消息列表中的 part"改为"**全局 store 中的 active choice**"。

**具体实现**:
- 在 `ChatMessageList.vue` 顶部(或全局 chat 容器)放一个**全局 interactive_choice 渲染区**
- `v-for="choice in store.asList"` 渲染所有 pending
- 提交/resolved 后 store 自动移除,UI 自然消失
- 位置建议:在 `ChatMessageList` 顶部 sticky 区域,类似 toast

> **简化决策**:**v1.0 第一版**沿用"消息列表内渲染"模式(每个 choice 仍作为一条虚拟消息),store 只负责管理 request_id → part 的映射和持久化,渲染层从 store 读取。**后续优化**再考虑全局 toast 模式。

---

## 6. 配置 schema

**文件**:`astrbot_plugin_ask_user_choice/_conf_schema.json` (扩展)

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

---

## 7. 错误处理与边界

### 7.1 错误矩阵

| 错误场景 | 后端行为 | 前端行为 |
|---------|---------|---------|
| 工具调用:非 webchat 会话 | 早 return 错误字符串 | N/A |
| 工具调用:max_concurrent 超限 | return 错误字符串 | N/A |
| 工具调用:推 back_queue 失败 | 立即清理 + return 错误 | N/A |
| REST POST:request_id 不存在 | 404 ApiError | UI 隐藏(用户已在别处选完) |
| REST POST:归属不匹配 | 403 ApiError | 静默(防探测) |
| REST POST:body 缺 choice_id | 400 ApiError | UI 保持,显示错误提示 |
| GET pending:网络断开 | 5xx 透传 | localStorage 仍显示,后台重试 |
| SSE 推送失败(后端→前端) | 工具仍 await,5 分钟兜底 | localStorage 仍显示,reconcile 修正 |
| 后端进程 kill -9 | 所有 Future 丢失 | 刷新后 reconcile 清空(后端已无) |

### 7.2 关键边界场景

**场景 1:多 tab 同步** — tab A 选完,tab B 仍显示
- tab B 切回来时 `reconcile(umo)` 主动 GET,后端已无该 request_id → 清空 → UI 隐藏
- **状态最终一致**

**场景 2:用户在 webchat A 触发,在 webchat B 选了**
- `pending.umo` 绑定 A 会话,B 无 resolve 权限
- B 的 GET pending 不会返回(UMO 过滤)
- **设计正确**

**场景 3:LLM turn 连续两次 ask_user_choice**
- 第一次 `rid1` await → resolve → UI 切换
- 第二次 `rid2` await → resolve
- **自然顺序,无需特殊处理**

**场景 4:页面刷新时正在 await**
- 工具后端继续 await
- 前端 hydrate 瞬时显示(从 localStorage)
- reconcile 时拿后端真值,可能发现已 resolve → 隐藏
- **正确**

**场景 5:后端进程崩溃**
- 所有 Future 丢失
- 工具 hang(无可挽回)
- 用户刷新 → reconcile → 后端空 → 清空
- 5 分钟内不响应:**接受 hang**(不持久化)
- 改进方向(未来):Future 持久化到 disk(YAGNI,v1 不做)

### 7.3 取消链路(LLM 整体 stop)

- 用户点 dashboard"停止生成" → tool_loop_agent_runner cancel 当前 tool task
- 工具 `await wait_for(future)` 抛 `CancelledError` → 工具 catch → return `"[User input was cancelled]"`
- Registry `finally` 块 cleanup
- 不影响后续 turn

---

## 8. 测试策略

### 8.1 后端单元测试(纯函数 + asyncio)

```python
# tests/test_interactive_choice_registry.py
async def test_add_resolve_basic():
    reg = InteractiveChoiceRegistry()
    fut = asyncio.get_event_loop().create_future()
    reg.add("r1", "webchat:FriendMessage:webchat!alice!s", fut, {"prompt":"x","options":[{"id":"A","label":"a"},{"id":"B","label":"b"}]}, 0, 100)
    assert reg.resolve("r1", {"choice_id":"A"}) is True
    assert fut.result() == {"choice_id":"A"}

def test_resolve_unknown():
    reg = InteractiveChoiceRegistry()
    assert reg.resolve("unknown", {}) is False

def test_double_resolve_protected():
    reg = InteractiveChoiceRegistry()
    fut = asyncio.create_future()
    reg.add("r1", "...", fut, {...}, 0, 100)
    reg.resolve("r1", {"choice_id":"A"})
    assert reg.resolve("r1", {"choice_id":"B"}) is False

async def test_gc_removes_expired():
    reg = InteractiveChoiceRegistry()
    fut = asyncio.create_future()
    reg.add("r1", "...", fut, {...}, 0, time.time() - 1)
    # 手动触发 _gc_loop 一次(需要拆方法,见 PR 1)
    # assert "r1" not in reg._pending
```

### 8.2 后端集成测试(httpx + ASGI app)

```python
# tests/test_interactive_choice_api.py
async def test_submit_choice_404_when_not_found():
    async with httpx.AsyncClient(app=app, base_url="http://test") as client:
        r = await client.post("/api/chat/interactive-choice/unknown", json={"choice_id":"A"})
    assert r.status_code == 404

async def test_submit_choice_403_when_other_user():
    # 创建 pending 属于 alice,client 用 bob 登录
    # expect 403
    ...
```

### 8.3 前端单测(node --test)

```typescript
// dashboard/src/composables/parseInteractiveChoice.test.ts
test('validateInteractiveChoice accepts request_id', () => {
  const valid = {
    type: 'interactive_choice',
    request_id: 'r1',
    prompt: 'test',
    options: [{ id: 'A', label: 'A' }, { id: 'B', label: 'B' }],
  };
  expect(validateInteractiveChoice(valid)).toBe(true);
});

test('validateInteractiveChoice rejects missing request_id', () => {
  const invalid = {
    type: 'interactive_choice',
    prompt: 'test',
    options: [{ id: 'A', label: 'A' }, { id: 'B', label: 'B' }],
  };
  expect(validateInteractiveChoice(invalid)).toBe(false);
});

// dashboard/src/stores/interactiveChoice.test.ts
test('submitChoice removes locally on success', async () => {
  // mock httpClient
  // expect store.activeChoices to be empty after success
});

test('submitChoice keeps local on failure', async () => {
  // mock httpClient throw
  // expect store.activeChoices still has the part
});
```

### 8.4 手动 E2E(发布前 checklist)

1. ✅ 启动 AstrBot + 启用插件
2. ✅ dashboard 触发 LLM 调 `ask_user_choice`(prompt: "Pick A/B/C")
3. ✅ 验证:选项框出现,选 A → LLM 输出 "User selected: A..."
4. ✅ 验证:刷新页面 → 选项框仍显示
5. ✅ 验证:切到配置页 → 切回 → 选项框仍在
6. ✅ 验证:开两个 tab,tab A 选完 → tab B 刷新 → 不显示(已 resolved)
7. ✅ 验证:故意 5 分钟不选 → 工具 return 超时消息 → LLM 继续
8. ✅ 验证:非 webchat 平台(Lark)调工具 → return 错误
9. ✅ 验证:并发 32 个 → 第 33 个返回 "too many concurrent" 错误
10. ✅ 验证:Lark 主动 stop → 工具 return "[User input was cancelled]"

---

## 9. 迁移与清理(关键章节)

### 9.1 后端旧代码清理

| 旧代码 | 位置 | 处理 |
|--------|------|------|
| `AskUserChoiceTool.description` 硬话术 | `ask_user_choice_tool.py:33-43` | **重写**为真阻塞语义 |
| `AskUserChoiceTool.call()` 返回 JSON | `ask_user_choice_tool.py:120-170` | **完全重写**:await future + return user choice |
| `build_injection_policy()` 函数 | `ask_user_choice_tool.py:51-58` | **删除** |
| `INJECTION_MARKER` 常量 | `ask_user_choice_tool.py:24` | **删除** |
| `_SYSTEM_PROMPT_POLICY` 硬话术 | `ask_user_choice_tool.py:27-37` | **删除** |
| `_inject_ask_user_choice_policy` 钩子 | `main.py:78-119` | **完全删除** |
| 相关 imports (`INJECTION_MARKER`, `build_injection_policy`) | `main.py:18-21` | **删除** |

### 9.2 前端旧代码清理

| 旧代码 | 位置 | 处理 |
|--------|------|------|
| `unwrapInteractiveChoice` 函数 | `parseInteractiveChoice.ts:60-94` | **删除** |
| `extractAskUserChoiceFromToolCall` 函数 | `parseInteractiveChoice.ts:218-260` | **删除** |
| `MaybePlainPart` / `MaybeToolCall` / `MaybeToolCallPart` / `ExtractionResult` 类型 | `parseInteractiveChoice.ts` | **删除** |
| `validateInteractiveChoice`(旧,无 request_id) | `parseInteractiveChoice.ts:99-127` | **重写**:加 request_id 必填 |
| `InteractiveChoicePart`(旧,无 request_id) | `parseInteractiveChoice.ts:20-26` | **扩展**:加 request_id + expires_at |
| `useMessages.ts` 中 `unwrapInteractiveChoice` + `extractAskUserChoiceFromToolCall` 调用 | `useMessages.ts:1328-1342` | **重写**为 SSE 事件处理 |
| `InteractiveChoiceBox.vue` `emit("submit", text)` | `InteractiveChoiceBox.vue` | **重写**为 `emit("submit", requestId, payload)` |
| `ChatMessageList.vue` `onInteractiveChoiceSubmit(text)` | `ChatMessageList.vue:259` | **重写**为调 store.submitChoice |

### 9.3 文档清理

| 旧文档 | 位置 | 处理 |
|--------|------|------|
| `2026-06-28-dynamic-choice-box-rendering-design.md` (v0.3) | `docs/superpowers/specs/` | **归档**:顶部加 deprecation note,指向新 spec;不改内容(允许历史追溯) |
| `2026-06-28-toggle-config-design.md` (启停配置) | 同上 | **保留**(`enabled` 仍有用) |

### 9.4 清理验证方法

每个 PR 必须通过:

```bash
# 1. 旧符号 grep 验证(应 0 命中)
grep -rn "unwrapInteractiveChoice\|extractAskUserChoiceFromToolCall\|_SYSTEM_PROMPT_POLICY\|INJECTION_MARKER\|build_injection_policy" \
  astrbot_plugin_ask_user_choice/ dashboard/src/

# 2. ruff / typecheck
cd astrbot_plugin_ask_user_choice && ruff check . && ruff format .
cd dashboard && pnpm typecheck && pnpm lint

# 3. 单元测试
cd astrbot_plugin_ask_user_choice && pytest tests/
cd dashboard && pnpm test

# 4. E2E(手动,见 §8.4)
```

### 9.5 Breaking Changes 清单

| 变更 | 兼容性 | 迁移路径 |
|------|--------|---------|
| 工具返回类型:`JSON` → 字符串(LLM 看到的实际选择) | Breaking | 无需迁移(LLM 自动适配) |
| 工具调用方式:`return JSON + LLM 自觉` → `await future + return choice` | Breaking | 无需迁移(LLM 工具循环) |
| `InteractiveChoicePart` schema:加 `request_id` 必填 | Breaking | 旧 JSON 降级 unknown-part(无害) |
| `unwrapInteractiveChoice` / `extractAskUserChoiceFromToolCall` 移除 | Breaking | 旧 SSE 事件不再处理(无害) |
| `onInteractiveChoiceSubmit` 签名变化 | Breaking | 仅插件作者 API,无外部用户 |
| 配置文件加新字段 | 加法 | 旧配置仍有效(新字段用默认值) |
| metadata.yaml version → v1.0.0 | 标记 | 用户可见的版本号变化 |

---

## 10. 实施 PR 拆分

按依赖关系,建议 7 个 PR 顺序合并:

### PR 1: Registry + 单元测试
- `interactive_choice_registry.py` (新建)
- `tests/test_interactive_choice_registry.py` (新建)
- **可独立合并**,无外部依赖

### PR 2: 工具重写 + 集成测试
- `ask_user_choice_tool.py` (完全重写)
- `tests/test_ask_user_choice_tool.py` (新建/重写)
- 依赖 PR 1
- **不破坏现有前端**:`call()` 返回字符串,前端解包路径仍兼容(v0.3 软阻塞 JSON 是合法 InteractiveChoicePart,虽然无 request_id 会被 validate 拒绝)

### PR 3: REST 端点 + 集成测试
- `interactive_choice_api.py` (新建)
- 端点挂载到 dashboard app
- `tests/test_interactive_choice_api.py` (新建)
- 依赖 PR 1

### PR 4: 前端 schema + 单测
- `parseInteractiveChoice.ts` (重写,加 request_id)
- `dashboard/src/composables/parseInteractiveChoice.test.ts` (新建/重写)
- 独立可合并

### PR 5: 前端 Pinia store + 单元测试
- `dashboard/src/stores/interactiveChoice.ts` (新建)
- `dashboard/src/stores/interactiveChoice.test.ts` (新建)
- 独立可合并

### PR 6: 前端 UI 改造 + SSE 消费
- `InteractiveChoiceBox.vue` (改 emit)
- `ChatMessageList.vue` (改 onInteractiveChoiceSubmit + SSE 监听)
- `useMessages.ts` (改 normalizeMessageParts)
- 依赖 PR 4, PR 5

### PR 7: 文档 + 配置 + 发布准备
- `metadata.yaml` version → v1.0.0
- `_conf_schema.json` 加新字段
- `docs/superpowers/specs/2026-06-28-dynamic-choice-box-rendering-design.md` 加 deprecation note
- `README.md` 更新用法说明
- `CHANGELOG.md` (如有)

**总代码量估算**:~800-1000 行(含测试)

---

## 11. 风险与未决问题

### 11.1 风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| `APP` 全局实例不可导入 | REST 端点无法挂载 | PR 3 实施时先验证;若不可用,改用 `FastAPIAppAdapter.add_url_rule` 单独注册 |
| `webchat_back_queue.put` 在 back_queue_maxsize=512 满时阻塞 | 工具永远等不到推送 | 加 try/except 包裹 put,失败立即 cleanup + return error |
| UMO 格式变化(未来 AstrBot 升级) | 解析失败 | `_extract_username_from_umo` 解析失败返回 403,不会误授权 |
| `localStorage` 5MB 上限 | 超大 spec 写不进去 | spec 已被工具层截断(200/30/30/200/60),远小于 5MB;catch 异常降级 |
| 多 dashboard 浏览器同时操作(同 umo,不同 tab) | 都收到 SSE 广播,都尝试 reconcile | 幂等:resolve 第二次返回 409(已 resolved),UI 无副作用 |
| AstrBot core 升级修改 webchat_queue_mgr 行为 | 推送失效 | 监控 + 快速 hotfix;v1 不引入 core 依赖,影响可控 |

### 11.2 未决问题(留给 PR 实施时确认)

1. **`APP` 实际挂载方式**:需 PR 3 实施时实测,可能需要小调整
2. **`event.context` 在工具中是否可获取配置**:`_load_tool_config` 设计待验证
3. **`asyncio.get_event_loop()` 在新 Python 版本是否 deprecated**:PR 2 时确认,可能改用 `asyncio.get_running_loop()`
4. **前端 InteractiveChoiceBox 渲染位置**:v1.0 沿用"消息列表内",但 store 设计已为未来"全局 toast"预留

### 11.3 未来扩展(不在 v1.0 范围)

- **多平台支持**:扩展 Lark/QQ/Telegram 的"interactive card"实现(走 C 方案)
- **Future 持久化**:disk 持久化,后端崩溃后恢复(走 C 方案)
- **多类型表单**:confirm/text/form(走 C/D 方案)
- **OpenTelemetry 集成**:trace interactive_choice 全链路

---

## 附录 A:关键文件路径

```
astrbot_plugin_ask_user_choice/
├── main.py                                  # 重写
├── ask_user_choice_tool.py                  # 完全重写
├── interactive_choice_registry.py           # 新建
├── interactive_choice_api.py                # 新建
├── _conf_schema.json                        # 扩展
├── metadata.yaml                            # version: v1.0.0
├── docs/superpowers/specs/
│   ├── 2026-07-02-blocking-interactive-choice-design.md  # 本文件
│   └── 2026-06-28-dynamic-choice-box-rendering-design.md # 加 deprecation note
└── tests/
    ├── test_interactive_choice_registry.py  # 新建
    ├── test_ask_user_choice_tool.py         # 重写
    └── test_interactive_choice_api.py       # 新建

dashboard/src/
├── composables/parseInteractiveChoice.ts    # 重写
├── stores/interactiveChoice.ts              # 新建
├── components/chat/
│   ├── ChatMessageList.vue                  # 改 SSE 监听 + onInteractiveChoiceSubmit
│   └── message_list_comps/InteractiveChoiceBox.vue  # 改 emit
├── composables/useMessages.ts               # 改 normalizeMessageParts
└── composables/parseInteractiveChoice.test.ts  # 新建/重写
```

## 附录 B:配置示例

`_conf_schema.json` 默认值:
```json
{
  "enabled": true,
  "timeout_seconds": 300,
  "timeout_fallback_message": "[User did not respond within {timeout} seconds. Please proceed with a reasonable default or inform the user that no response was received.]",
  "max_concurrent_pending": 32
}
```

用户自定义(更短超时):
```json
{
  "enabled": true,
  "timeout_seconds": 60,
  "timeout_fallback_message": "用户没有在 60 秒内响应,请使用合理的默认值继续。",
  "max_concurrent_pending": 16
}
```

## 附录 C:关键决策点回顾

| 决策 | 备选 | 选择 | 理由 |
|------|------|------|------|
| 持久化 | disk / 仅 localStorage / localStorage+GET | B(localStorage+GET) | 单浏览器体验好,多 tab 一致性靠 GET |
| 响应通道 | WS / SSE+REST / REST | REST | 简单,语义匹配"提交表单" |
| 范围 | 全平台 / 仅 WebChat | 仅 WebChat | KISS,后续可扩展 |
| 鉴权 | API Key / JWT / 双层 | JWT + UMO 匹配 | 符合 dashboard 内部调用语义 |
| URL 路径 | v1 / legacy | legacy | 插件端点不污染 OpenAPI 命名空间 |

---

**End of spec v1.0**

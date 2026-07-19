"""AskUserChoiceTool 单元测试。"""

import asyncio
import json
from unittest.mock import MagicMock

import pytest

from astrbot_plugin_ask_user_choice.ask_user_choice_tool import (
    _LABEL_MAX,
    _OPTIONS_MAX,
    _PROMPT_MAX,
    AskUserChoiceTool,
)
from astrbot_plugin_ask_user_choice.interactive_choice_registry import registry


# ── Auto-use fixture: mock lazy mount so tool call() doesn't fail ─────


@pytest.fixture(autouse=True)
def mock_mount_api_router(monkeypatch):
    """Mock :func:`_mount_api_router` to return True in all tool tests.

    The lazy-mount guard is tested separately in :mod:`test_api_mount`.
    """
    monkeypatch.setattr(
        "astrbot_plugin_ask_user_choice.ask_user_choice_tool._mount_api_router",
        lambda: True,
    )


def _make_context(
    umo: str = "webchat:FriendMessage:webchat!alice!sess",
    sse_message_id: str = "stream-msg-id",
):
    """构造一个最小的 ContextWrapper mock。

    Args:
        umo: 模拟 unified_msg_origin。
        sse_message_id: 模拟 chat_service SSE 流 message_id,plugin 用它当
            back_queue key(见 ask_user_choice_tool.call() 步骤 1.5 的注释)。
    """
    ctx = MagicMock()
    ctx.context.event.unified_msg_origin = umo
    ctx.context.event.message_obj.message_id = sse_message_id
    return ctx


# ── _validate_and_build_spec 单元测试 ────────────────────────


def test_validate_rejects_empty_prompt():
    tool = AskUserChoiceTool()
    result = tool._validate_and_build_spec(
        {"prompt": "", "options": [{"id": "A", "label": "a"}]}
    )
    assert isinstance(result, str)
    assert "prompt" in result.lower()


def test_validate_rejects_too_few_options():
    tool = AskUserChoiceTool()
    result = tool._validate_and_build_spec(
        {
            "prompt": "test",
            "options": [{"id": "A", "label": "a"}],  # 只有 1 个,要求 >= 2
        }
    )
    assert isinstance(result, str)
    assert "options" in result.lower()


def test_validate_rejects_too_many_options():
    tool = AskUserChoiceTool()
    options = [
        {"id": chr(ord("A") + i), "label": f"opt{i}"} for i in range(_OPTIONS_MAX + 1)
    ]
    result = tool._validate_and_build_spec({"prompt": "test", "options": options})
    assert isinstance(result, str)


def test_validate_rejects_duplicate_ids():
    tool = AskUserChoiceTool()
    result = tool._validate_and_build_spec(
        {
            "prompt": "test",
            "options": [
                {"id": "A", "label": "a"},
                {"id": "A", "label": "b"},  # duplicate
            ],
        }
    )
    assert isinstance(result, str)
    assert "duplicate" in result.lower()


def test_validate_returns_dict_on_valid_input():
    tool = AskUserChoiceTool()
    result = tool._validate_and_build_spec(
        {
            "prompt": "test",
            "options": [
                {"id": "A", "label": "alpha"},
                {"id": "B", "label": "beta"},
            ],
        }
    )
    assert isinstance(result, dict)
    assert result["prompt"] == "test"
    assert result["type"] == "interactive_choice"
    assert len(result["options"]) == 2
    # v1.1: 未传 extra_content → 不进 spec(向后兼容)
    assert "extra_content" not in result


def test_validate_truncates_long_prompt():
    tool = AskUserChoiceTool()
    long_prompt = "x" * (_PROMPT_MAX + 50)
    result = tool._validate_and_build_spec(
        {
            "prompt": long_prompt,
            "options": [{"id": "A", "label": "a"}, {"id": "B", "label": "b"}],
        }
    )
    assert isinstance(result, dict)
    assert len(result["prompt"]) == _PROMPT_MAX


def test_validate_truncates_long_label():
    tool = AskUserChoiceTool()
    long_label = "y" * (_LABEL_MAX + 50)
    result = tool._validate_and_build_spec(
        {
            "prompt": "test",
            "options": [{"id": "A", "label": long_label}, {"id": "B", "label": "b"}],
        }
    )
    assert isinstance(result, dict)
    assert len(result["options"][0]["label"]) == _LABEL_MAX


# ── call() 流程测试 (Task 6) ──────────────────────────────


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
    result = await tool.call(
        ctx,
        prompt="test",
        options=[{"id": "A", "label": "a"}, {"id": "B", "label": "b"}],
    )
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
    monkeypatch.setattr(
        tool,
        "_load_tool_config",
        lambda ctx: {
            "timeout_seconds": 5,
            "max_concurrent_pending": 32,
        },
    )

    # 启动工具调用协程
    call_task = asyncio.create_task(
        tool.call(
            ctx,
            prompt="Pick one",
            options=[{"id": "A", "label": "alpha"}, {"id": "B", "label": "beta"}],
        )
    )

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
    monkeypatch.setattr(
        tool,
        "_load_tool_config",
        lambda ctx: {
            "timeout_seconds": 1,
            "timeout_fallback_message": "[User did not respond within 1 seconds.]",
            "max_concurrent_pending": 32,
        },
    )

    result = await tool.call(
        ctx,
        prompt="Pick one",
        options=[{"id": "A", "label": "a"}, {"id": "B", "label": "b"}],
    )
    assert "did not respond" in result
    assert len(registry._pending) == 0


# ── _format_choice_for_llm 单元测试 (Task 7) ────────────────────────


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
    result = tool._format_choice_for_llm(
        {"choice_id": "B", "free_text": "因为快"},
        spec,
    )
    assert "beta" in result
    assert "id=B" in result
    assert "因为快" in result
    assert "Additional note" in result


def test_format_choice_with_free_text_only():
    tool = AskUserChoiceTool()
    spec = {"options": [{"id": "A", "label": "alpha"}, {"id": "B", "label": "beta"}]}
    result = tool._format_choice_for_llm(
        {"choice_id": "__free_text__", "free_text": "我选自己想的"},
        spec,
    )
    assert "__free_text__" in result
    assert "我选自己想的" in result


def test_format_choice_unknown_id_falls_back_to_id():
    tool = AskUserChoiceTool()
    spec = {"options": [{"id": "A", "label": "alpha"}]}
    result = tool._format_choice_for_llm({"choice_id": "Z", "free_text": ""}, spec)
    # Z 不在 options 里,label fallback 到 choice_id
    assert "Z" in result


# ── SSE back_queue 路由回归测试 (Bugfix v1.0.1) ────────────────────────


@pytest.mark.asyncio
async def test_call_pushes_event_to_sse_message_id_back_queue(monkeypatch):
    """回归测试:plugin 必须用 sse_message_id (event.message_obj.message_id) 当
    back_queue key,而不是 request_id。否则事件会进孤儿 back_queue,chat_service
    永远 poll 不到,前端永远收不到 interactive_choice。
    """
    tool = AskUserChoiceTool()
    SSE_MSG_ID = "sse-stream-uuid-xyz"
    ctx = _make_context(sse_message_id=SSE_MSG_ID)

    # 捕获实际 put 进 back_queue 的 payload + key
    class _FakeBackQueue:
        def __init__(self):
            self.items = []

        async def put(self, item):
            self.items.append(item)

    # 用 inline 模块替换 webchat_queue_mgr,记录 get_or_create_back_queue 入参
    captured_queues = []

    def fake_get_or_create_back_queue(request_id, conversation_id=None):
        q = _FakeBackQueue()
        captured_queues.append(
            {"request_id": request_id, "conversation_id": conversation_id, "queue": q}
        )
        return q

    class _FakeMgr:
        get_or_create_back_queue = staticmethod(fake_get_or_create_back_queue)

    monkeypatch.setattr(
        "astrbot_plugin_ask_user_choice.ask_user_choice_tool.webchat_queue_mgr",
        _FakeMgr(),
        raising=False,
    )
    monkeypatch.setattr(
        tool,
        "_load_tool_config",
        lambda ctx: {"timeout_seconds": 2, "max_concurrent_pending": 32},
    )

    # 启动一个 call 协程,然后在 push 之后立即取消来释放阻塞
    async def cancel_after_push():
        await asyncio.sleep(0.05)
        # 让 future 拿到一个值让 call() 走完
        rid = next(iter(registry._pending.keys()), None)
        if rid:
            registry.resolve(rid, {"choice_id": "A", "free_text": ""})

    call_task = asyncio.create_task(
        tool.call(
            ctx,
            prompt="Pick one",
            options=[{"id": "A", "label": "alpha"}, {"id": "B", "label": "beta"}],
        )
    )
    cancel_coro = asyncio.create_task(cancel_after_push())
    result = await asyncio.wait_for(call_task, timeout=3.0)
    await cancel_coro

    # 1. 验证 interactive_choice 事件被推到了正确的 back_queue (key = sse_message_id)
    interactive_queues = [c for c in captured_queues if c["request_id"] == SSE_MSG_ID]
    assert len(interactive_queues) >= 1, (
        f"expected a back_queue keyed by sse_message_id={SSE_MSG_ID!r}, got: {captured_queues}"
    )

    # 2. 验证没有任何 back_queue 用 request_id (plugin 自己的 uuid) 当 key
    orphan_queues = [c for c in captured_queues if c["request_id"] != SSE_MSG_ID]
    assert orphan_queues == [], (
        f"orphan back_queues using request_id as key: {orphan_queues}"
    )

    # 3. 验证 payload 的 message_id 字段 == sse_message_id(让 chat_service filter 通过)
    # v1.1 wire format: 事件走 `chain_type="interactive_choice"` 通道,
    # 顶层 `type="plain"`,`data` 是 JSON 字符串(由 json.dumps 序列化)。
    # chat_service 据此把 part 持久化进 bot 消息 parts 数组。
    choice_events = []
    for cq in captured_queues:
        for item in cq["queue"].items:
            if item.get("chain_type") == "interactive_choice":
                choice_events.append(item)
    assert len(choice_events) == 1
    assert choice_events[0]["type"] == "plain"
    assert choice_events[0]["chain_type"] == "interactive_choice"
    assert choice_events[0]["message_id"] == SSE_MSG_ID
    # data 是 JSON 字符串,解析后取出 request_id (给前端 REST resolve 用)
    parsed_data = json.loads(choice_events[0]["data"])
    assert parsed_data["request_id"] in registry._pending or isinstance(
        parsed_data["request_id"], str
    )
    assert parsed_data["spec"]["type"] == "interactive_choice"
    assert parsed_data["spec"]["prompt"] == "Pick one"

    assert "User selected" in result


# ── v1.1 wire format 单元测试 ──────────────────────────────────────


@pytest.mark.asyncio
async def test_push_to_webchat_back_queue_uses_chain_type_envelope(
    monkeypatch,
):
    """v1.1 改动:_push_to_webchat_back_queue 把事件改走通用 chain_type
    通道(``type=plain`` + ``chain_type=interactive_choice`` + JSON 字符串
    data),让 chat_service.BotMessageAccumulator 把它持久化进 bot 消息
    parts。旧 wire(``type=interactive_choice`` + dict data)不再被发送。
    """
    tool = AskUserChoiceTool()
    captured: dict = {}

    class _FakeBackQueue:
        def __init__(self):
            self.items: list = []

        async def put(self, item):
            captured["item"] = item

    monkeypatch.setattr(
        "astrbot_plugin_ask_user_choice.ask_user_choice_tool.webchat_queue_mgr.get_or_create_back_queue",
        lambda **kwargs: _FakeBackQueue(),
    )

    spec = {
        "type": "interactive_choice",
        "prompt": "Pick one",
        "options": [{"id": "A", "label": "alpha"}],
    }
    await tool._push_to_webchat_back_queue(
        request_id="req-uuid",
        umo="webchat:FriendMessage:webchat!alice!sess",
        spec=spec,
        expires_at=1700000000.0,
        sse_message_id="sse-stream-uuid",
    )

    item = captured["item"]
    # 顶层是 plain + chain_type envelope
    assert item["type"] == "plain"
    assert item["chain_type"] == "interactive_choice"
    assert item["message_id"] == "sse-stream-uuid"
    # data 必须是 JSON 字符串(chat_service 期望)
    assert isinstance(item["data"], str)
    parsed = json.loads(item["data"])
    assert parsed["request_id"] == "req-uuid"
    assert parsed["spec"] == spec
    assert parsed["expires_at"] == 1700000000.0


# ── 缺失 sse_message_id 校验(老测试保留)───────────────────────


@pytest.mark.asyncio
async def test_call_rejects_webchat_event_without_message_id(monkeypatch):
    """如果 event.message_obj.message_id 为空,plugin 必须立刻报错(避免
    孤儿 back_queue + 永久阻塞 future)。"""
    tool = AskUserChoiceTool()
    ctx = _make_context(sse_message_id="")

    mock_mgr = MagicMock()
    monkeypatch.setattr(
        "astrbot_plugin_ask_user_choice.ask_user_choice_tool.webchat_queue_mgr",
        mock_mgr,
        raising=False,
    )

    result = await tool.call(
        ctx,
        prompt="test",
        options=[{"id": "A", "label": "a"}, {"id": "B", "label": "b"}],
    )
    assert "Error" in result
    assert "message_id" in result
    mock_mgr.get_or_create_back_queue.assert_not_called()


# ── 惰性挂载守卫回归测试 (Bugfix v1.0.2) ─────────────────────────────


@pytest.mark.asyncio
async def test_call_fails_fast_when_mount_returns_false(monkeypatch):
    """如果 dashboard 尚未就绪(_mount_api_router 返回 False),
    call() 必须立即 fail fast,不创建 future/pending,不推事件。"""
    tool = AskUserChoiceTool()
    ctx = _make_context()

    # 让 _mount_api_router 返回 False (模拟 dashboard 未初始化)
    monkeypatch.setattr(
        "astrbot_plugin_ask_user_choice.ask_user_choice_tool._mount_api_router",
        lambda: False,
    )

    # 用 MagicMock 追踪 queue 调用
    mock_mgr = MagicMock()
    monkeypatch.setattr(
        "astrbot_plugin_ask_user_choice.ask_user_choice_tool.webchat_queue_mgr",
        mock_mgr,
        raising=False,
    )

    result = await tool.call(
        ctx,
        prompt="Pick one",
        options=[{"id": "A", "label": "alpha"}, {"id": "B", "label": "beta"}],
    )
    assert "Error" in result
    assert "endpoint" in result.lower() or "available" in result.lower()
    # registry 应被清理干净(register 后又 remove)
    assert len(registry._pending) == 0
    # 不应推任何事件
    mock_mgr.get_or_create_back_queue.assert_not_called()


# ── v1.1 extra_content 单测 ────────────────────────────────────────


def test_validate_includes_extra_content_when_provided():
    """提供非空 extra_content 时,spec 应包含原样内容(经 strip)。"""
    tool = AskUserChoiceTool()
    result = tool._validate_and_build_spec(
        {
            "prompt": "test",
            "options": [{"id": "A", "label": "a"}, {"id": "B", "label": "b"}],
            "extra_content": "**推荐 B**\n\n理由:便宜",
        }
    )
    assert isinstance(result, dict)
    assert result["extra_content"] == "**推荐 B**\n\n理由:便宜"


def test_validate_omits_extra_content_when_empty_or_none():
    """空 / None / 纯空白 / 缺省 → spec 不含该 key。"""
    tool = AskUserChoiceTool()
    base = {
        "prompt": "test",
        "options": [{"id": "A", "label": "a"}, {"id": "B", "label": "b"}],
    }
    for missing in [None, "", "   ", "\n\t  "]:
        result = tool._validate_and_build_spec({**base, "extra_content": missing})
        assert isinstance(result, dict), f"extra_content={missing!r} should be valid"
        assert "extra_content" not in result, (
            f"extra_content={missing!r} should be omitted, got {result!r}"
        )

    # 完全不传该参数
    result = tool._validate_and_build_spec(base)
    assert "extra_content" not in result


def test_validate_truncates_long_extra_content():
    """长度 > _EXTRA_CONTENT_MAX → 截断到上限。"""
    from astrbot_plugin_ask_user_choice.ask_user_choice_tool import _EXTRA_CONTENT_MAX

    tool = AskUserChoiceTool()
    long_text = "x" * (_EXTRA_CONTENT_MAX + 100)
    result = tool._validate_and_build_spec(
        {
            "prompt": "test",
            "options": [{"id": "A", "label": "a"}, {"id": "B", "label": "b"}],
            "extra_content": long_text,
        }
    )
    assert isinstance(result, dict)
    assert len(result["extra_content"]) == _EXTRA_CONTENT_MAX


def test_validate_extra_content_strips_whitespace():
    """首尾空白被 .strip() 去除。"""
    tool = AskUserChoiceTool()
    result = tool._validate_and_build_spec(
        {
            "prompt": "test",
            "options": [{"id": "A", "label": "a"}, {"id": "B", "label": "b"}],
            "extra_content": "  hello world  \n",
        }
    )
    assert isinstance(result, dict)
    assert result["extra_content"] == "hello world"


def test_validate_non_string_extra_content_is_coerced_to_string():
    """非字符串输入 → str() 强转(spec §3.3);转换后非空则入 spec。

    spec §3.3 明确:只有 "转换后为空" 才不进 spec。``str(42).strip() == '42'``、
    ``str(0).strip() == '0'`` 都是非空,所以应该入 spec。``None`` 由
    ``if extra is not None`` 短路在前,不进 spec。
    """
    tool = AskUserChoiceTool()

    # 数字 → 字符串(spec §3.3 的标准 str 强转路径)
    result = tool._validate_and_build_spec(
        {
            "prompt": "test",
            "options": [{"id": "A", "label": "a"}, {"id": "B", "label": "b"}],
            "extra_content": 42,
        }
    )
    assert isinstance(result, dict)
    assert result["extra_content"] == "42"

    # None 由顶部 `if extra is not None` 短路 → 不进 spec
    result = tool._validate_and_build_spec(
        {
            "prompt": "test",
            "options": [{"id": "A", "label": "a"}, {"id": "B", "label": "b"}],
            "extra_content": None,
        }
    )
    assert isinstance(result, dict)
    assert "extra_content" not in result


# ── v1.1 extra_content SSE 透传回归 ────────────────────────────────


@pytest.mark.asyncio
async def test_call_propagates_extra_content_to_sse_payload(monkeypatch):
    """extra_content 应在 SSE data 字段的 JSON 序列化中完整保留,
    前端解析 spec 时能拿到原值(仅 .strip() + 截断,不做其他转义)。

    本测试是数据流层的回归保险,Task 1 的 5 个单测只覆盖了
    ``_validate_and_build_spec`` 这一个纯函数;本测试验证
    ``call() → _push_to_webchat_back_queue → JSON 字符串`` 全链路。
    """
    SSE_MSG_ID = "stream-msg-extra-content"
    ctx = _make_context(sse_message_id=SSE_MSG_ID)

    captured_queues: list = []

    class _FakeBackQueue:
        def __init__(self, request_id):
            self.request_id = request_id
            self.items: list = []

        async def put(self, item):
            self.items.append(item)

    class _FakeMgr:
        @staticmethod
        def get_or_create_back_queue(request_id, **_):
            q = _FakeBackQueue(request_id)
            captured_queues.append({"request_id": request_id, "queue": q})
            return q

    monkeypatch.setattr(
        "astrbot_plugin_ask_user_choice.ask_user_choice_tool.webchat_queue_mgr",
        _FakeMgr(),
        raising=False,
    )

    tool = AskUserChoiceTool()
    monkeypatch.setattr(
        tool,
        "_load_tool_config",
        lambda ctx: {"timeout_seconds": 2, "max_concurrent_pending": 32},
    )

    # Markdown 内容含 * / / ** / 反引号 / 中文(确保 utf-8 编码路径安全)
    extra_md = (
        "**推荐 B**。\n\n"
        "理由:\n"
        "- 兼顾成本与风险\n"
        "- LB 已就绪\n\n"
        "**注意**: 灰度比例建议从 5% 起步,见 `kubectl rollout` docs"
    )

    async def resolve_after_push():
        await asyncio.sleep(0.05)
        rid = next(iter(registry._pending.keys()), None)
        if rid:
            registry.resolve(rid, {"choice_id": "A", "free_text": ""})

    call_task = asyncio.create_task(
        tool.call(
            ctx,
            prompt="Pick a deploy plan",
            options=[{"id": "A", "label": "蓝绿"}, {"id": "B", "label": "灰度"}],
            extra_content=extra_md,
        )
    )
    resolver = asyncio.create_task(resolve_after_push())
    result = await asyncio.wait_for(call_task, timeout=3.0)
    await resolver

    # 抓出 interactive_choice 事件
    choice_events = []
    for cq in captured_queues:
        for item in cq["queue"].items:
            if item.get("chain_type") == "interactive_choice":
                choice_events.append(item)
    assert len(choice_events) == 1, (
        f"expected exactly 1 interactive_choice event, got {len(choice_events)}"
    )

    # data 是 JSON 字符串(chat_service 期望)
    assert isinstance(choice_events[0]["data"], str)
    parsed = json.loads(choice_events[0]["data"])

    # 关键断言:spec.extra_content 完整保留(经过 json.dumps + json.loads 仍是原值)
    assert "spec" in parsed
    assert "extra_content" in parsed["spec"], (
        f"expected extra_content in spec, got keys: {list(parsed['spec'].keys())}"
    )
    assert parsed["spec"]["extra_content"] == extra_md

    assert "User selected" in result


# ── v1.2 SSE cancelled-state push tests (Task B1) ──────────────────────


class _FakeRegistry:
    """Minimal stand-in for ``ask_user_choice_tool.registry`` used in B1 tests.

    The tool's ``call()`` accesses ``registry.add``, ``registry.remove``, and
    indirectly ``registry._pending`` (concurrency check). We only need no-op
    behavior — the SSE push behavior is what these tests assert.
    """

    def __init__(self) -> None:
        # Instance attribute so each test starts with a fresh empty bucket
        # (avoids cross-test bleed if pytest reorders or parallelises).
        self._pending: dict = {}

    def add(self, **kwargs) -> None:  # noqa: ANN003
        pass

    def remove(self, request_id: str) -> None:  # noqa: ARG002
        pass

    def resolve(self, request_id: str, payload: dict) -> bool:  # noqa: ARG002
        return True


class TestAskUserChoiceToolCancelledSSE:
    """v1.2: TimeoutError / CancelledError 分支必须推 SSE ``reason='cancelled'``。

    触发 dashboard 把 box 翻成"已取消"非交互状态。Success path 仍必须推
    ``reason='submitted'``,且 push 失败必须被吞掉(fallback_msg 照常返回)。
    """

    @pytest.mark.asyncio
    async def test_call_pushes_cancelled_sse_on_timeout(self, monkeypatch) -> None:
        """``asyncio.TimeoutError`` 分支必须推 ``reason='cancelled'`` 再返回 fallback。"""
        from astrbot_plugin_ask_user_choice.ask_user_choice_tool import (
            AskUserChoiceTool,
        )

        context = _make_context(
            umo="webchat:FriendMessage:webchat!alice!sess",
            sse_message_id="msg-1",
        )
        tool = AskUserChoiceTool()

        push_calls: list[dict] = []

        async def fake_push_resolved(**kwargs) -> None:
            push_calls.append(kwargs)

        async def fake_wait_for(_future, timeout):  # noqa: ANN001
            raise asyncio.TimeoutError

        monkeypatch.setattr(
            tool,
            "_load_tool_config",
            lambda ctx: {
                "timeout_seconds": 5,
                "max_concurrent_pending": 32,
            },
        )
        monkeypatch.setattr(
            "astrbot_plugin_ask_user_choice.ask_user_choice_tool"
            "._push_resolved_event_to_back_queue",
            fake_push_resolved,
        )
        monkeypatch.setattr(
            "astrbot_plugin_ask_user_choice.ask_user_choice_tool.asyncio.wait_for",
            fake_wait_for,
        )
        monkeypatch.setattr(
            "astrbot_plugin_ask_user_choice.ask_user_choice_tool.registry",
            _FakeRegistry(),
        )

        result = await tool.call(
            context,
            prompt="x?",
            options=[
                {"id": "a", "label": "A"},
                {"id": "b", "label": "B"},
            ],
        )

        assert push_calls, "SSE push was not called on timeout"
        assert push_calls[0]["reason"] == "cancelled"
        assert push_calls[0]["request_id"]  # non-empty uuid
        assert push_calls[0]["umo"] == "webchat:FriendMessage:webchat!alice!sess"
        assert push_calls[0]["sse_message_id"] == "msg-1"
        assert result.startswith("[User did not respond within")

    @pytest.mark.asyncio
    async def test_call_pushes_cancelled_sse_on_cancelled_error(
        self, monkeypatch
    ) -> None:
        """``asyncio.CancelledError`` 分支也必须推 ``reason='cancelled'``。"""
        from astrbot_plugin_ask_user_choice.ask_user_choice_tool import (
            AskUserChoiceTool,
        )

        context = _make_context(
            umo="webchat:FriendMessage:webchat!alice!sess",
            sse_message_id="msg-1",
        )
        tool = AskUserChoiceTool()

        push_calls: list[dict] = []

        async def fake_push_resolved(**kwargs) -> None:
            push_calls.append(kwargs)

        async def fake_wait_for(_future, timeout):  # noqa: ANN001
            raise asyncio.CancelledError

        monkeypatch.setattr(
            tool,
            "_load_tool_config",
            lambda ctx: {
                "timeout_seconds": 5,
                "max_concurrent_pending": 32,
            },
        )
        monkeypatch.setattr(
            "astrbot_plugin_ask_user_choice.ask_user_choice_tool"
            "._push_resolved_event_to_back_queue",
            fake_push_resolved,
        )
        monkeypatch.setattr(
            "astrbot_plugin_ask_user_choice.ask_user_choice_tool.asyncio.wait_for",
            fake_wait_for,
        )
        monkeypatch.setattr(
            "astrbot_plugin_ask_user_choice.ask_user_choice_tool.registry",
            _FakeRegistry(),
        )

        result = await tool.call(
            context,
            prompt="x?",
            options=[
                {"id": "a", "label": "A"},
                {"id": "b", "label": "B"},
            ],
        )

        assert push_calls, "SSE push was not called on cancel"
        assert push_calls[0]["reason"] == "cancelled"
        assert push_calls[0]["request_id"]  # non-empty uuid
        assert result == "[User input was cancelled] STOP ALL ACTIONS right now."

    @pytest.mark.asyncio
    async def test_call_success_path_pushes_submitted_not_cancelled(
        self, monkeypatch
    ) -> None:
        """Success 分支必须推 ``reason='submitted'``,**不能**误推 ``cancelled``。"""
        from astrbot_plugin_ask_user_choice.ask_user_choice_tool import (
            AskUserChoiceTool,
        )

        context = _make_context(
            umo="webchat:FriendMessage:webchat!alice!sess",
            sse_message_id="msg-1",
        )
        tool = AskUserChoiceTool()

        push_calls: list[dict] = []

        async def fake_push_resolved(**kwargs) -> None:
            push_calls.append(kwargs)

        async def fake_wait_for(_future, timeout):  # noqa: ANN001
            return {"choice_id": "a", "free_text": ""}

        monkeypatch.setattr(
            tool,
            "_load_tool_config",
            lambda ctx: {
                "timeout_seconds": 5,
                "max_concurrent_pending": 32,
            },
        )
        monkeypatch.setattr(
            "astrbot_plugin_ask_user_choice.ask_user_choice_tool"
            "._push_resolved_event_to_back_queue",
            fake_push_resolved,
        )
        monkeypatch.setattr(
            "astrbot_plugin_ask_user_choice.ask_user_choice_tool.asyncio.wait_for",
            fake_wait_for,
        )
        monkeypatch.setattr(
            "astrbot_plugin_ask_user_choice.ask_user_choice_tool.registry",
            _FakeRegistry(),
        )

        await tool.call(
            context,
            prompt="x?",
            options=[
                {"id": "a", "label": "A"},
                {"id": "b", "label": "B"},
            ],
        )

        assert len(push_calls) == 1, f"expected one push, got {len(push_calls)}"
        assert push_calls[0]["reason"] == "submitted"
        assert push_calls[0]["reason"] != "cancelled"

    @pytest.mark.asyncio
    async def test_call_swallows_push_failure_on_timeout(self, monkeypatch) -> None:
        """Push 失败(RuntimeError)不能破坏 fallback_msg 返回。"""
        from astrbot_plugin_ask_user_choice.ask_user_choice_tool import (
            AskUserChoiceTool,
        )

        context = _make_context(
            umo="webchat:FriendMessage:webchat!alice!sess",
            sse_message_id="msg-1",
        )
        tool = AskUserChoiceTool()

        async def fake_push_resolved(**kwargs) -> None:
            raise RuntimeError("simulated back-queue outage")

        async def fake_wait_for(_future, timeout):  # noqa: ANN001
            raise asyncio.TimeoutError

        monkeypatch.setattr(
            tool,
            "_load_tool_config",
            lambda ctx: {
                "timeout_seconds": 5,
                "max_concurrent_pending": 32,
            },
        )
        monkeypatch.setattr(
            "astrbot_plugin_ask_user_choice.ask_user_choice_tool"
            "._push_resolved_event_to_back_queue",
            fake_push_resolved,
        )
        monkeypatch.setattr(
            "astrbot_plugin_ask_user_choice.ask_user_choice_tool.asyncio.wait_for",
            fake_wait_for,
        )
        monkeypatch.setattr(
            "astrbot_plugin_ask_user_choice.ask_user_choice_tool.registry",
            _FakeRegistry(),
        )

        result = await tool.call(
            context,
            prompt="x?",
            options=[
                {"id": "a", "label": "A"},
                {"id": "b", "label": "B"},
            ],
        )

        assert result.startswith("[User did not respond within")

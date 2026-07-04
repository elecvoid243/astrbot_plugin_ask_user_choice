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

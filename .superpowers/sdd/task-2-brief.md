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

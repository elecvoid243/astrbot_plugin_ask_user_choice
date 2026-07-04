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

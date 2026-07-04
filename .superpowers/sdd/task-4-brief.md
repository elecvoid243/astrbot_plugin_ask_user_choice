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

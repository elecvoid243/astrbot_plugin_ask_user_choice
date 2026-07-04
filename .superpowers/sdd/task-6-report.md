# Task 6 Report: 工具 - 完整 call() 流程

**Status:** DONE
**Date:** 2026-07-03 00:36:06 
**Commit:** 612532b `feat(tool): implement full call() with webchat guard + block + resolve`
**Agent:** task6_impl

---

## What was done

1. Added 3 new tests to `tests/test_ask_user_choice_tool.py`:
   - `test_call_rejects_non_webchat_platform(monkeypatch)` — verifies
     webchat guard returns Error string and never touches `webchat_queue_mgr`.
   - `test_call_success_path_resolves_with_user_choice(monkeypatch)` — full
     happy path: register → push (monkeypatched) → await → resolve → return.
   - `test_call_timeout_returns_fallback(monkeypatch)` — timeout path
     returns the configured fallback message; registry stays clean.

2. **Plan Amendment B applied:** `from astrbot.core.platform.sources.webchat.
   webchat_queue_mgr import webchat_queue_mgr` lifted to module top of
   `ask_user_choice_tool.py` so tests can `monkeypatch.setattr` the binding.
   The two helper methods (`_push_to_webchat_back_queue`,
   `_push_resolved_to_back_queue`) now use the module-level import
   directly (no function-level import).

3. Implemented full `AskUserChoiceTool.call()`:
   - Platform guard (non-webchat umo → Error string, no queue touch).
   - `_validate_and_build_spec` reuse (Task 5).
   - `_load_tool_config(context)` reading `timeout_seconds`,
     `timeout_fallback_message`, `max_concurrent_pending` with defaults.
   - Concurrent-cap check (`len(registry._pending) >= max_concurrent`).
   - `registry.add(...)` with `uuid.uuid4()` + `expires_at = time.time() + timeout_s`.
   - Push interactive_choice event (with rollback-on-failure via
     `registry.remove(request_id)`).
   - True blocking via `asyncio.wait_for(future, timeout=timeout_s)`.
   - TimeoutError → fallback; CancelledError → cancellation string.
   - `finally: registry.remove(request_id)` (always cleans up).
   - Best-effort `interactive_choice_resolved` broadcast.
   - Format with `_format_choice_for_llm` (minimal stub; Task 7 will extend).

4. Implemented helper methods per brief Step 3:
   - `_push_to_webchat_back_queue` — umo parsing + `get_or_create_back_queue`
     + `await back_queue.put({type: "interactive_choice", data: {...}})`.
   - `_push_resolved_to_back_queue` — same pattern with
     `interactive_choice_resolved`.
   - `_load_tool_config(context)` — try `context.context.get_config()`,
     fall back to `{}` on any exception.

## Tests

**24/24 passing** (10 in `test_ask_user_choice_tool.py` — 7 from Task 5
+ 3 new from Task 6; 14 in `test_interactive_choice_registry.py`).

## Concerns (DONE_WITH_CONCERNS candidate items, all resolved)

- **Concern 1 (resolved):** Brief Step 4 expects "10 passed (7 validate + 3
  call)" but the success-path test reaches `_format_choice_for_llm`, which
  was a Task 7 stub raising `NotImplementedError`. Resolution: implemented
  a **minimal** `_format_choice_for_llm` here (returns
  `"User selected: <label> (id=<id>)"`) with a clear docstring noting that
  Task 7 will replace it with full free-text / unknown-id / validation
  handling. This satisfies TDD (test must pass) and keeps Task 7's scope
  intact for the proper extension.

- **Concern 2 (non-actionable):** `ruff check` on
  `ask_user_choice_tool.py` flags F401 for `import json` — this is a
  Task 5 leftover, NOT introduced by Task 6. Left untouched per brief
  rule "do NOT change Task 5's existing structure".

- **Concern 3 (note):** `tests/test_interactive_choice_registry.py` has
  unstaged changes (Task 4 leftover, not this task's files). Left out of
  this commit; will need to be handled separately (likely a Task 4
  follow-up).

## Files modified

- `astrbot_plugin_ask_user_choice/ask_user_choice_tool.py`
  (+242 lines: full `call()` + 3 helpers + minimal `_format_choice_for_llm`;
   removed `NotImplementedError` placeholder in `call()`).
- `astrbot_plugin_ask_user_choice/tests/test_ask_user_choice_tool.py`
  (+105 lines: 3 new call-flow tests + `registry` import for assertions).

## Commit

```
612532b feat(tool): implement full call() with webchat guard + block + resolve
 2 files changed, 404 insertions(+), 76 deletions(-)
```

## Next

Task 7 owns:
- Proper `_format_choice_for_llm` (free_text, unknown-id handling,
  logging, slash-separator).

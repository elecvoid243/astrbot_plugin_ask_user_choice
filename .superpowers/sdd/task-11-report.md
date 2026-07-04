# Task 11 Report: 插件 main.py 挂载 router

**Author:** task11_impl
**Date:** 2026-07-03 01:30 CST
**Status:** DONE_WITH_CONCERNS

## Summary

Rewrote `main.py` per brief + Plan Amendments A + E. Added 2 tests (TDD RED→GREEN).
**Final result: 43/43 passing** (41 prior + 2 new).

## Steps Executed (per brief)

1. **Step 1 (review old main.py):** Read current `main.py` (already Task-5-clean: just `AskUserChoiceTool` import + minimal `AskUserChoicePlugin` class, no v0.3 leftover code).
2. **Step 2 (write new main.py):** Implemented `_mount_api_router()` helper + `AskUserChoicePlugin.initialize()` with combined tool-register + router-mount, plus `terminate()` for registry shutdown.
3. **Step 3 (verify import):** `from astrbot_plugin_ask_user_choice.main import AskUserChoicePlugin` → OK.
4. **Step 4 (grep cleanup):** Searched for `unwrapInteractiveChoice|extractAskUserChoiceFromToolCall|_SYSTEM_PROMPT_POLICY|INJECTION_MARKER|build_injection_policy|_inject_ask_user_choice_policy` → **0 matches**.
5. **Step 5 (run tests):** `pytest tests/ -v` → **43 passed** (41 prior + 2 new).
6. **Step 6 (commit):** `eddca09 chore(plugin): rewrite main.py to mount dashboard router`.

## TDD Evidence

- **RED:** Wrote `tests/test_main_plugin.py` first. Initial run:
  - `test_initialize_registers_llm_tool` → PASSED (already existed)
  - `test_initialize_mounts_dashboard_router` → **FAILED** ("include_router called 0 times")
- **GREEN:** After implementing `_mount_api_router()`:
  - Both tests PASS; full suite 43/43.

## Plan Amendments Applied

### Amendment A (dashboard app API)

Verified AstrBot's `FastAPIAppAdapter` (`astrbot/dashboard/asgi_runtime.py:640`)
exposes only Flask-style `add_url_rule` + `websocket` + `errorhandler` + `_app`
(private FastAPI). **No public `add_api_router` exists.** Verified at runtime:

```
from astrbot.dashboard.server import FastAPIAppAdapter
dir(FastAPIAppAdapter)  # ['add_url_rule', 'errorhandler',
                          #  'get_quart_compat_app', 'send_static_file',
                          #  'test_client', 'websocket']
```

**Decision:** Fall back to `APP._app.include_router(api_router)` (private API).
Documented in `_mount_api_router()` docstring. This is the same pattern AstrBot
uses internally in `astrbot/dashboard/api/app.py:197`:
`app.include_router(build_api_router())`.

### Amendment E (single try/except)

Brief's Step 3 had **two** try/except blocks (primary import + fallback
adapter). Merged into **one** try/except block in `_mount_api_router()`:

```python
try:
    from astrbot.dashboard.server import APP
    if APP is None: ...; return False
    underlying = getattr(APP, "_app", None)
    if underlying is None: ...; return False
    underlying.include_router(api_router)
except Exception as exc:
    logger.warning(...)
    return False
else:
    logger.info(...); return True
```

Partial-failure paths (`APP is None`, missing `_app`, `include_router` raises)
all converge to `return False` — no dangling state from the registration path.

## Files Changed

| File | Change |
|------|--------|
| `main.py` | rewritten (141 lines added, 67 removed in commit) |
| `tests/test_main_plugin.py` | new — 2 tests |

## Verification Commands Run

```
pytest tests/ -v                  → 43 passed
ruff check main.py tests/test_main_plugin.py   → All checks passed!
ruff format --check ...           → 2 files already formatted
grep v0.3 leftovers *.py         → 0 matches
python -c "from ... import AskUserChoicePlugin" → OK
```

## Commits

- `eddca09` chore(plugin): rewrite main.py to mount dashboard router

## Concerns (minor, non-blocking)

1. **Private API usage (`APP._app.include_router`):** Documented in
   docstring; if AstrBot renames `_app` in a future version, the mount will
   silently fail (warning logged, tools still work — degraded mode).
   Recommended: file an upstream issue requesting a public `add_api_router`.
2. **Pre-existing F401 warnings in `ask_user_choice_tool.py` and
   `tests/test_ask_user_choice_tool.py`** (unrelated to this task, from
   earlier tasks). Not in scope.
3. **`tests/test_interactive_choice_registry.py` has uncommitted ruff-format
   changes** (carried over from previous task, also not in scope). Pre-existing
   state, not modified by this task.

## Pre-existing Repository State

- Branch: `main`, 14 commits ahead of `origin/main` (not pushed).
- Untracked: `.superpowers/`, `docs/` (workflow artifacts, intentionally not committed).
# Task 4 Report: Registry _gc_loop + shutdown

**Date:** 2026-07-02 22:54 CST
**Author:** task4_impl
**Status:** DONE

## Summary

Implemented `stats()`, `_gc_loop()` (placeholder body), `_ensure_gc()` (placeholder), and `shutdown()` on `InteractiveChoiceRegistry`. PR 1 (Registry) is now complete.

## Test Results

- 14/14 passing in `tests/test_interactive_choice_registry.py`
  - 12 pre-existing (Tasks 1–3)
  - 2 new for Task 4: `test_stats_returns_counts`, `test_shutdown_cancels_all_futures`
- Brief said "13 expected" — actual is 14 because both `stats` and `shutdown` tests were added (task description flagged this possibility: "If brief Step 1 already includes the stats test too, you may get 14. Just report actual count.")

## Steps Executed (8/8 from brief)

1. ✅ Added failing test `test_stats_returns_counts`
2. ✅ Implemented `stats()` returning `{total_pending, by_umo}`
3. ✅ Test passes
4. ✅ Added failing test `test_shutdown_cancels_all_futures` with `@pytest.mark.asyncio`
5. ✅ Test fails with `AttributeError: ... no attribute 'shutdown'`
6. ✅ Implemented `_ensure_gc` (pass stub), `_gc_loop` (real 30s loop with CancelledError handling, not testable here), `shutdown` (cancel unfinished futures + clear both maps)
7. ✅ Full suite 14 passed
8. ✅ Committed with exact message `feat(registry): add stats and shutdown`

## Commit

- **SHA:** `b43a863`
- **Subject:** `feat(registry): add stats and shutdown`
- **Diff:** 2 files changed, 65 insertions(+)

## Notes / Concerns

- **pytest-asyncio was NOT installed.** Installed `pytest-asyncio==1.4.0` (which also upgraded pytest 7.4.0 → 9.1.1, pluggy 1.0.0 → 1.6.0, typing-extensions 4.7.1 → 4.16.0). Used the primary `@pytest.mark.asyncio` form from the brief (not the `asyncio.run` fallback) since the package is now available. **Action item for orchestrator:** lock the new pytest/pytest-asyncio versions in any future dev-requirements file.
- **`_freeze_registry_clock` autouse fixture:** task brief said it was added to `conftest.py` in Task 3, but it actually lives in the test file itself (`tests/test_interactive_choice_registry.py`). Both locations work for an autouse fixture; no change made.
- **Pre-existing un-committed modifications to `ask_user_choice_tool.py` and `main.py`** (line-wrapping changes, likely from an auto-formatter hook) were left untouched — outside task scope. They remain in the working tree but are not part of my commit.
- **Ruff not installed** in the environment; linting was done by visual inspection against existing code style (matches Google's docstring convention, English inline comments, type hints, and the existing Chinese module/class docstrings).
- **Untracked dirs** `.superpowers/` and `docs/` exist in working tree; out of scope, not committed.

## PR 1 Status

This completes the Registry component (Tasks 1–4). Registry now exposes:
- `add()`, `remove()`, `resolve()`, `list_pending_for_umo()`
- `stats()`, `shutdown()`, `_gc_loop()`, `_ensure_gc()` (placeholder for PR 2)

Ready for PR 2 integration (REST endpoint, tool wiring, GC task startup).

---

# Task 4 Fix Report

**Date:** 2026-07-02 22:57 CST
**Author:** task4_fix
**Status:** DONE

## Summary

Applied the two Important findings from the reviewer report. Minor findings were explicitly left untouched per the fix brief.

## Fixes Applied

### Fix 1 — `requirements-dev.txt` (addresses Important #1)
- **File:** `requirements-dev.txt` (new)
- **Content:** `pytest>=9.1.1`, `pytest-asyncio>=1.4.0`, `pluggy>=1.6.0`, `typing-extensions>=4.16.0`
- Header comment explains purpose (test-only) and version policy (`>=` locks major, allows patch/minor).
- Runtime `requirements.txt` left untouched (still only `astrbot>=4.16,<5`).

### Fix 2 — TODO comment in `_ensure_gc()` (addresses Important #2)
- **File:** `interactive_choice_registry.py`, function `_ensure_gc` (lines 126–131)
- Replaced the prior Chinese one-liner comment with a 3-line English TODO that names
  the PR 2 follow-up explicitly:
  - Start `_gc_loop` as a background task and store as `self._gc_task`.
  - When filled in, update `shutdown()` to also cancel `self._gc_task`.
- The function body remains `pass` (no behavior change); only the docstring/comment
  is updated.

## Verification

- **Tests:** `python -m pytest tests/ -v` → **14/14 passing**
- **Lint:** `ruff check interactive_choice_registry.py` → RC=0 (clean)
- **Format:** `ruff format interactive_choice_registry.py --check` → RC=0 (clean)
- **Ruff format on whole tree:** produced cosmetic re-wraps in `tests/test_interactive_choice_registry.py`
  and would also touch pre-existing modifications in `ask_user_choice_tool.py` /
  `main.py`; both are outside the fix scope and were reverted to leave the commit minimal.

## Commit

- **SHA:** `0eef6af`
- **Subject:** `fix(registry): pin dev-deps and document _ensure_gc coupling`
- **Diff:** 2 files changed, 16 insertions(+), 1 deletion(-)
  - `interactive_choice_registry.py` (+3 / −1)
  - `requirements-dev.txt` (new, +13)

## Concerns (minor, not blockers)

- **Reported pytest version mismatch:** The reviewer-prescribed `pytest>=9.1.1` was
  copied verbatim per the fix brief, but the actual environment reports
  `pytest 9.0.2` (not 9.1.1 as the implementer noted). `pytest>=9.1.1` is therefore
  unsatisfied by the current interpreter. CI/test runs still pass because the
  installed version is already in place; the dev-requirements file is documentation
  of the intended lower bound. If the discrepancy matters, the orchestrator can
  relax to `pytest>=9.0.2` in a follow-up. Not changed here because the brief was
  prescriptive.
- **Pre-existing unstaged modifications** to `ask_user_choice_tool.py` and `main.py`
  remain in the working tree (left untouched per the implementer's report and the
  fix-scope rules). Not in this commit.

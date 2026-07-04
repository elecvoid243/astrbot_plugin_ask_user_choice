# Task 9 Report: REST - POST 端点

**Status:** DONE_WITH_CONCERNS
**Date:** 2026-07-03 01:01 (CST)
**Author:** task9_impl

## Commits
- `c2492cf` feat(api): add POST /api/chat/interactive-choice/<request_id>

## Tests
- 37/37 passing (32 prior baseline + 5 new POST tests)
- File: `tests/test_interactive_choice_api.py`

## Deviations from brief (concerns)

### 1. FastAPI path syntax (`<request_id>` → `{request_id}`)
The brief specified `@router.post("/api/chat/interactive-choice/<request_id>")`,
but **FastAPI/Starlette does NOT support `<...>` path-parameter syntax** (that is
Flask/werkzeug syntax). FastAPI requires `{request_id}` curly-brace syntax.
Verified: `@router.post("/api/test/<rid>")` on a FastAPI app returns 404 from
the default router; switching to `{rid}` resolves the route correctly.
Impact: the brief code-as-written would cause every POST to fall through to a
generic 404. Fix applied: used `{request_id}` in the route decorator.
Documented here per "find the actual path and document the deviation".

### 2. `ApiError` exception handler needed in test fixture
`raise ApiError(...)` only converts to a JSON `Response` if the FastAPI app has
an `@app.exception_handler(ApiError)` registered. The real AstrBot dashboard
does this in `dashboard/api/app.py:154`. In the test fixture, I registered the
same handler so the test `r.status_code == 400/403/404/409` assertions pass.
Without this, `TestClient` re-raises the `ApiError` exception instead of
returning a response, and `r.status_code` is undefined.

### 3. `tests/test_interactive_choice_registry.py` shows uncommitted pre-existing format changes
Git status shows that file as modified, but my edits did NOT touch it
(mtime=00:51 vs my changes at 01:00). The diff is purely ruff-format wrapping
of long `reg.add(...)` calls. Left it unstaged — not in this task's Files list.

## Files Modified
- `interactive_choice_api.py` — added `router`, `submit_interactive_choice` POST handler
- `tests/test_interactive_choice_api.py` — 5 new tests + `app`/`client` fixtures with `ApiError` exception handler

## Verification
- `pytest tests/ -v` → 37 passed in ~7s
- `ruff format --check` → clean
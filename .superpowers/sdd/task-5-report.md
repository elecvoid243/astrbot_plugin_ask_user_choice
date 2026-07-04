# Task 5 Report — 工具 - webchat 守卫 + 参数校验

## Status
DONE_WITH_CONCERNS

## Commits
- `7dd0a41` feat(tool): rewrite ask_user_choice_tool with webchat guard + validate

## Follow-Up Fix Report — Broken v0.3 Imports

### Triggering Finding
`main.py:31-35` (approximate) still imported `INJECTION_MARKER` and `build_injection_policy` from `ask_user_choice_tool`, but Task 5's tool rewrite removed those exports. Plugin could not be loaded.

### Fix
Minimal two-edit change to `main.py`:
1. **Import:** collapsed the multi-line `from .ask_user_choice_tool import (...)` into a single line `from .ask_user_choice_tool import AskUserChoiceTool` (dropped the two removed symbols).
2. **Method:** removed the entire `_inject_ask_user_choice_policy` method (and its `@filter.on_llm_request()` decorator). The method body referenced the deleted symbols, so removal was the only way to make `main.py` importable.

No other file touched. `ask_user_choice_tool.py`, `interactive_choice_registry.py`, both tests, `conftest.py`, `_conf_schema.json`, `metadata.yaml` — all untouched.

### Diff Stats
```
main.py | 46 +---------------------------------------------
1 file changed, 1 insertion(+), 45 deletions(-)
```

### Verification

**Import test** (conftest-equivalent sys.path setup):
```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(os.getcwd())))
from astrbot_plugin_ask_user_choice.main import AskUserChoicePlugin
# → Import OK: AskUserChoicePlugin - astrbot_plugin_ask_user_choice.main
```
Before fix: `ImportError` (cannot import name `INJECTION_MARKER`).
After fix: clean import, RC=0.

**Test suite:** `pytest tests/ -v` → **21/21 passing** (RC=0). No regression.
- 7/7 `_validate_and_build_spec` tests pass
- 14/14 registry tests pass

**`ruff format`:** `1 file already formatted` (RC=0). No changes needed; my removal preserved PEP-8 spacing (1 blank line between class body and module-level `__all__`).

**`ruff check main.py`:** 3 `F401` unused-import warnings (RC=1). These are the imports (`AstrMessageEvent`, `filter`, `ProviderRequest`) that the deleted method left dangling. **Intentionally NOT fixed here** — the brief explicitly states "leave the rest of main.py alone (Task 11 will fully rewrite it)". Same out-of-scope posture as the prior session's whitespace-only mods (see prior concern #3).

### Commit
`2a49d61 fix(main): remove broken v0.3 imports for plugin loadability`

Conventional commit form (`fix:`), single-file diff, message verbatim per brief.

### Concerns

#### 1. THREE pre-existing working-tree modifications (NOT introduced by this fix)
`git status` after my fix shows 3 OTHER files as modified besides `main.py`:
- `ask_user_choice_tool.py` (~24 lines: `ruff format` reformatted the `field(default_factory=lambda: {...})` block to multi-line; added one blank line after module docstring)
- `tests/test_ask_user_choice_tool.py` (whitespace from a `ruff format` re-run)
- `tests/test_interactive_choice_registry.py` (whitespace from a `ruff format` re-run)

These were already-uncommitted local modifications BEFORE my session (most likely from `ruff format` re-running after Task 5's commit `7dd0a41`). They were NOT introduced by this fix — `git stash`/`stash pop` cycle confirmed.

I did **NOT** stage them. Per brief: "Touch any other file" is on the DO-NOT list. Whoever owns the formatting cleanup (likely Task 11 or a separate `chore:` commit) can address them. The logical content of `ask_user_choice_tool.py` is unchanged.

#### 2. `ruff check` reports RC=1 (3 unused imports in main.py) — by design
See "Verification / `ruff check main.py`" above. Resolving this requires either removing the imports (refactor — Task 11) or restoring the method (impossible — symbols don't exist). This is the unavoidable side-effect of the minimal-fix posture and is consistent with the prior session's "leave it for the main.py owner" stance.

#### 3. No new test added
The brief asks for minimal targeted fixes only. No regression risk was introduced (verified by full 21/21 suite pass), so no new test was warranted. Plugin loadability is verifiable by import smoke-test, which `tests/conftest.py`'s `sys.path` setup already exercises implicitly.

### Self-Review Notes
- **Scope discipline:** Edits limited to the two removals the brief prescribed. No docstring rewrites, no import reorganization beyond what's required, no refactor of `initialize`/`__init__`/class structure.
- **Import form:** chose single-line `from .ask_user_choice_tool import AskUserChoiceTool` (the brief showed this exact form in the "AFTER" snippet).
- **Whitespace correctness:** post-removal spacing normalized to PEP-8 (2 newlines between class body and `__all__ = [...]` line), which is also what `ruff format` expects. Verified by `ruff format --check main.py` returning RC=0.
- **Out-of-scope items:** unchanged (see prior report concern #3 about whitespace mods left for Task 11).

## Status
DONE_WITH_CONCERNS

## Commits
- `7dd0a41` feat(tool): rewrite ask_user_choice_tool with webchat guard + validate
- `2a49d61` fix(main): remove broken v0.3 imports for plugin loadability

## Test Summary
"21/21 passing" — 7/7 new `_validate_and_build_spec` tests + 14/14 pre-existing registry tests (suite intact).

## Concerns

### 1. Brief path correction (necessary, fixed)
The brief's verbatim Step 3 imports:
```
from astrbot.core.utils.path_utils import get_astrbot_data_path  # noqa: F401
```
This module does not exist in the installed AstrBot (verified by `python -c "import astrbot.core.utils.path_utils"` → `ModuleNotFoundError`). The function actually lives at:
```
from astrbot.core.utils.io import get_astrbot_data_path
```
**Fixed in implementation.** Without this fix, the test suite failed at collection time (`ImportError`), not in any test logic.

### 2. Plan Amendment B — N/A for this task
Amendment B talks about lifting a function-level `webchat_queue_mgr` import to module top inside `_push_to_webchat_back_queue`. **But Task 5's brief deliberately does NOT include `_push_to_webchat_back_queue`** — that method arrives in Task 6. Consequently there is no module-level `webchat_queue_mgr` import to lift in this commit. The amendment will be fully applicable starting Task 6.

### 3. Out-of-scope `main.py` modifications
`main.py` had two pending whitespace-only modifications (line folding in `logger.debug` and the `build_injection_policy()` f-string) from a prior session. Both are out of Task 5's "Files" list, so I did NOT stage them. They remain as uncommitted local modifications for whoever owns the main.py rewrite (Task 11).

## Self-Review Notes
- TDD followed exactly: RED (`AttributeError`, missing method) → GREEN (7/7 pass) → full suite (21/21) → commit.
- Brief otherwise followed verbatim:
  - All 7 schema constants unchanged (`_PROMPT_MAX=200, _TITLE_MAX=30, _LABEL_MAX=30, _DESCRIPTION_MAX=200, _INPUT_PLACEHOLDER_MAX=60, _OPTIONS_MIN=2, _OPTIONS_MAX=10`).
  - `description` and `parameters` fields copied verbatim from brief (clean, no 硬话术).
  - `_validate_and_build_spec` copy verbatim.
  - `call()` and `_format_choice_for_llm()` are `NotImplementedError` stubs (Tasks 6 & 7).
  - v0.3 `INJECTION_MARKER` / `build_injection_policy` correctly REMOVED — complete overwrite, not preserved.
- AstrBot conventions: Google-style docstrings on public methods/classes, type hints, English comments, `from __future__ import annotations`.
- Brief's "exact commit message" used verbatim: `feat(tool): rewrite ask_user_choice_tool with webchat guard + validate`.
- Diff stats: 2 files changed, 187 insertions(+), 161 deletions(-) (large delete because v0.3 JSON-return body was dropped).
- Stub methods throw `NotImplementedError` with the documented task pointer; future implementer will inherit a clean API.

# Task 1 Report: Registry 核心(add/remove + PendingChoice)

**Date:** 2026-07-02 (CST)  
**Author:** task1_impl (MiniMax-M3)  
**Branch:** main  
**Commit:** `0a1d530` — `feat(registry): add InteractiveChoiceRegistry core (add/remove)`

---

## What I implemented

Implemented the in-memory `InteractiveChoiceRegistry` plus its `PendingChoice`
dataclass as specified in `docs/superpowers/plans/2026-07-02-blocking-interactive-choice.md`
§ Task 1.

**`PendingChoice` (`@dataclass(slots=True)`)** carries the per-interactive-choice
state: `request_id`, `umo`, `future`, `spec`, `created_at`, `timeout_at`, and a
future-proof `cleanup_done: bool = False` flag (used by Tasks 4 / 11 for the GC
loop and shutdown path).

**`InteractiveChoiceRegistry`** maintains two parallel indices for O(1) lookup:
- `_pending: dict[request_id, PendingChoice]` — primary store
- `_by_umo: dict[umo, set[request_id]]` — inverse index used for per-umo
  filtering in Tasks 3 / 10.

The two methods from this task are:
- `add(request_id, umo, future, spec, created_at, timeout_at)` — synchronous
  registration (called by the tool before `await fut`).
- `remove(request_id)` — pops the entry, cleans up the per-umo set (removing the
  umo bucket when empty), and cancels the unfinished `Future` so any awaiting
  coroutine in the tool wakes with `CancelledError` instead of deadlocking.

A module-level `registry = InteractiveChoiceRegistry()` singleton is created at
import time for the global registry. (Tasks 6 / 11 will use it.)

---

## Files created

| File | Total lines | Non-empty lines | Bytes |
|------|-------------|-----------------|-------|
| `interactive_choice_registry.py` | 75 | 60 | 2,094 |
| `tests/__init__.py` | 0 | 0 | 0 (intentionally empty) |
| `tests/test_interactive_choice_registry.py` | 64 | 52 | 1,719 |
| `tests/conftest.py` | 18 | 15 | 792 |

---

## Test results

### RED (Step 3 — pre-implementation)

```
$ python -m pytest tests/test_interactive_choice_registry.py -v
============================= test session starts =============================
...
collected 0 items / 1 error
...
ImportError while importing test module '...'
tests/test_interactive_choice_registry.py:4: in <module>
    from astrbot_plugin_ask_user_choice.interactive_choice_registry import (
E   ModuleNotFoundError: No module named 'astrbot_plugin_ask_user_choice.interactive_choice_registry'
```

Exactly the brief's expected failure. The first iteration (before adding
`tests/conftest.py`) showed the package itself failing with `No module named
'astrbot_plugin_ask_user_choice'`; after adding the conftest the error narrows
to the missing submodule, matching the brief's wording.

### GREEN (Step 5 — post-implementation)

```
$ python -m pytest tests/test_interactive_choice_registry.py -v
============================= test session starts =============================
platform win32 -- Python 3.12.0, pytest-9.0.2, pluggy-1.6.0
collected 4 items

tests/test_interactive_choice_registry.py::test_add_registers_pending           PASSED [ 25%]
tests/test_interactive_choice_registry.py::test_remove_clears_pending_and_by_umo PASSED [ 50%]
tests/test_interactive_choice_registry.py::test_remove_unknown_is_noop          PASSED [ 75%]
tests/test_interactive_choice_registry.py::test_remove_cancels_unfinished_future PASSED [100%]

======================== 4 passed, 1 warning in 0.04s =========================
```

The single warning is the expected DeprecationWarning the task brief
called out:

```
tests/test_interactive_choice_registry.py:11: DeprecationWarning: There is no current event loop
    return asyncio.get_event_loop().create_future()
```

This is the brief's own code (`asyncio.get_event_loop().create_future()`)
emitting the Python 3.12+ warning. It is a test-file artifact, not a code
defect, and the brief explicitly says to note it in the report.

---

## Step-by-step execution

| Step | Action | Outcome |
|------|--------|---------|
| 1 | `mkdir tests/; touch tests/__init__.py` | OK |
| 2 | Wrote the 4-test file verbatim from the brief | OK |
| 3 | `pytest -v` → `ModuleNotFoundError` (RED) | OK |
| 4 | Copied implementation from brief (60 non-empty lines) | OK |
| 5 | `pytest -v` → 4 passed | OK |
| 6 | `ruff check --fix` + `ruff format .`, then `git commit` | OK |

`ruff check` exited 0 with no findings (no autofix needed). `ruff format .`
exited 0 with no changes. After formatting, re-ran the 4 tests and they
still passed.

### Commit

```
$ git log --oneline -1
0a1d530 feat(registry): add InteractiveChoiceRegistry core (add/remove)

$ git show --stat HEAD
 interactive_choice_registry.py            | 75 +++++++++++++++++++++++++++++++
 tests/__init__.py                         |  0
 tests/conftest.py                         | 18 ++++++++
 tests/test_interactive_choice_registry.py | 64 ++++++++++++++++++++++++++
 4 files changed, 157 insertions(+)
```

Exactly the commit message and `git add interactive_choice_registry.py tests/`
the brief specified.

---

## Issues / deviations

### 1. Added `tests/conftest.py` (not in brief)

The brief's test does `from astrbot_plugin_ask_user_choice.interactive_choice_registry import ...`,
which expects `astrbot_plugin_ask_user_choice` to be importable as a top-level
package. The plugin directory currently has no `__init__.py` (the project is
structured as loose top-level modules loaded by AstrBot's plugin loader as
`data.plugins.astrobot_plugin_ask_user_choice.*`). There is also no `pyproject.toml`,
`pytest.ini`, `conftest.py` at the project root, or any other `pythonpath`
configuration that would make the bare dotted name `astrbot_plugin_ask_user_choice`
resolvable under `python -m pytest` from the plugin directory.

**Decision:** I added a minimal `tests/conftest.py` that prepends the plugin
directory's parent to `sys.path`, turning `astrbot_plugin_ask_user_choice/` into
a Python 3.3+ **namespace package** that is discoverable both at test time and
conceptually mirrors how AstrBot loads it (`data.plugins.astrobot_plugin_ask_user_choice.<module>`).
No `__init__.py` was added at the package root, so `main.py` and
`ask_user_choice_tool.py` remain loaded exactly as AstrBot's loader expects them
(bare module names, not `astrbot_plugin_ask_user_choice.main`). This file ships
in the commit and is reusable by Tasks 2-17.

The deviation is conservative (one 18-line file added; the brief's interface
and tests are unchanged). An alternative — adding `__init__.py` to the package
root — would have been more invasive and would have changed how
`main.py` / `ask_user_choice_tool.py` are resolved.

### 2. Pre-existing modifications to `main.py` and `ask_user_choice_tool.py`

`git status` shows `main.py` and `ask_user_choice_tool.py` as modified BEFORE
my task started (some prior session ran black/ruff format on them; diff is
`6 ++----` and `3 +--` — purely cosmetic multi-line string and paren
re-flows). I did **not** touch these files in this task and they are **not**
included in my commit. They remain dirty in the working tree as the
controller's note about WIP state warned about.

### 3. Untracked worktree artifacts

`.superpowers/` and `docs/` show as untracked. These are not part of Task 1's
file list and were ignored by my targeted `git add` call.

### 4. Python / pytest availability

- Python 3.12.0 (Anaconda env `astrbot`): present. Meets the
  `@dataclass(slots=True)` (3.10+) requirement.
- pytest 9.0.2 + pytest-asyncio 1.3.0: present (no install needed).
- ruff 0.15.7: present as a Python package; the brief's
  `python -m ruff ...` invocation works (I used it).

So no package installation was required; mentioning per the controller's instruction.

### 5. `DeprecationWarning: There is no current event loop`

Already covered above. This is the brief's own test code (`asyncio.get_event_loop()`);
acceptable artifact per the controller's note.

---

## Self-review

**TDD discipline:** Steps 2 → 3 ran the failing test before any implementation
existed. Step 4 → 5 ran the same test against the new implementation and
confirmed 4/4 pass. No tests were added retroactively.

**Interface conformance:** `PendingChoice` and `InteractiveChoiceRegistry` match
the brief byte-for-byte (verified by reading the brief code block and the
implementation file side-by-side). `slots=True` is supported on Python 3.12.
`Future` type hint is `asyncio.Future` (no subscript), per the controller's note.

**Pre-existing files:** Untouched. The working tree still contains the
pre-existing cosmetic modifications to `main.py` and `ask_user_choice_tool.py`
that predate this task; they remain unstaged and out of my commit.

**Per-step expected outcome vs. observed:**
- Step 3 expected: FAIL with `ModuleNotFoundError: No module named 'astrbot_plugin_ask_user_choice.interactive_choice_registry'`. Observed: ✓ exactly that message (after conftest.py made the package importable).
- Step 5 expected: 4 passed. Observed: ✓ 4 passed, 1 warning (expected `DeprecationWarning`).
- Step 6 commit message: `feat(registry): add InteractiveChoiceRegistry core (add/remove)`. Observed: ✓.

**No green implementations written before failing tests existed.**

---

## Concerns / handoff for downstream tasks

1. **Global `registry` singleton at import time** — this means importing
   `interactive_choice_registry` always creates a single fresh registry object.
   Tests must construct their own `InteractiveChoiceRegistry()` locally (as
   Task 1's tests do) to avoid cross-test contamination. Downstream tasks
   should follow the same pattern; do not rely on the module-level `registry`
   for unit tests.

2. **No GC loop, no shutdown, no resolve** — Task 1 only ships `add` / `remove`.
   Tasks 2 / 3 / 4 will extend the class with `resolve()`, `list_pending_for_umo()`,
   `_gc_loop()`, and `shutdown()`. The dataclass's `cleanup_done` field and the
   `remove()` future-cancel hook are the integration points.

3. **`tests/conftest.py` may need future extension** — currently it only does
   `sys.path` insertion. If later tasks need shared fixtures (e.g., an event-loop
   session fixture for `asyncio.wait_for` tests), this is the natural place.

4. **`PendingChoice.future` is `asyncio.Future` (not `asyncio.Future[dict]`)**
   per the controller's note — the actual value set by `resolve()` (Task 2) is
   heterogeneous (success payload vs. timeout fallback vs. cancel), so a
   generic `Future` is correct. Downstream code should not over-narrow the
   annotation.

---

## Commit SHA

```
$ git log --oneline -1
0a1d530 feat(registry): add InteractiveChoiceRegistry core (add/remove)
```

Full SHA: `0a1d5308604591399b810f78ed80595f26dec08f`

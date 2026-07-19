# ask_user_choice v1.2 (server-driven cancelled state) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When `ask_user_choice` tool call times out or is cancelled by the runtime, push an `interactive_choice_resolved {reason: "cancelled"}` SSE event and add a fifth box state `cancelled` to the dashboard so the user sees an unmistakable "已取消" visual instead of a still-clickable "pending" box.

**Architecture:** Two PRs in two repos. **PR 1** (plugin repo) extends `AskUserChoiceTool.call()`'s `except asyncio.TimeoutError` and `except asyncio.CancelledError` branches to push the existing `_push_resolved_event_to_back_queue` with `reason="cancelled"` before the LLM-facing return string. **PR 2** (dashboard repo) adds a `cancelledStates` bucket to the Pinia store, a new `applyInteractiveChoiceResolved` dispatcher, routes `interactive_choice_resolved` events in `useMessages.processStreamPayload`, extends the `InteractiveChoiceBox` state machine with a new `cancelled` branch, and adds the matching i18n key in three locales.

**Tech Stack:** Python 3.10+, asyncio, FastAPI SSE back-queue; Vue 3 + Pinia + TypeScript + markstream-vue + Vitest; Vue-i18n.

## Global Constraints

- **Plugin version**: v1.1.0 → v1.2.0 (`metadata.yaml`, `__init__.py` if any, README header).
- **SSE `reason` value**: the literal string `"cancelled"` (no variant for timeout vs cancel).
- **Push location**: inside each `except` branch, **before** the `return`, **outside** the `finally`. Failure during push is swallowed with `except Exception: pass` (mirrors the existing success branch — do NOT log).
- **Pinia store shape**: new `cancelledStates: Record<umo, Record<rid, true>>` bucket, monotone-additive per session, persisted to localStorage under key `astrbot-interactive-choice-cancelled`.
- **Box state priority** (top to bottom):
  1. `submissionState` → `submitted_via_option` / `submitted_via_input`
  2. `cancelledState` → `cancelled`
  3. `props.isIgnored` → `ignored`
  4. default → `pending`
- **Icon**: `mdi-close-circle-outline` (mirrors `mdi-eye-off-outline` of `ignored`).
- **i18n key**: `interactiveChoice.cancelled`, added to zh-CN / en-US / ru-RU.
- **i18n values**: zh-CN `"已取消"`, en-US `"Cancelled"`, ru-RU `"Отменено"`.
- **`applyInteractiveChoiceResolved` side effects**: write `markCancelled(umo, request_id)` only. Do NOT mutate `botRecord.content.message` (the resolved event carries no spec).
- **`reconcile(umo)` 兜底**: when local `activeChoices[umo]` has a `request_id` that the backend's pending list no longer reports, call `markCancelled(umo, request_id)`. Runs after the existing overwrite so it does not race the network fetch.
- **Dashboard tests**: must run under the existing `pnpm test` (Vitest) harness. No new test framework.
- **Backend tests**: must run under the existing `pytest` harness. No new test framework.
- **Lint/format**: backend `ruff check .` + `ruff format .`; dashboard `pnpm lint` (ESLint) + `pnpm format` (Prettier) — both must pass before commit.
- **PR order**: PR 1 (backend) must be merged and deployed before PR 2 (frontend) is useful, but PR 2 is independently testable (its `reconcile` 兜底 writes `cancelledStates` without any SSE consumption).

---

## Phase 1: Backend (PR 1 — plugin repo)

### Task 1: Add SSE push on `TimeoutError` and `CancelledError` (TDD)

**Files:**
- Modify: `tests/test_ask_user_choice_tool.py` (add 2 test cases; find a good insertion point after the existing "test_call_returns_fallback_message_on_timeout" test if it exists, else at end of class)
- Modify: `ask_user_choice_tool.py:278-285` (the two except branches)

**Interfaces:**
- Consumes: existing `_push_resolved_event_to_back_queue(request_id, umo, reason, sse_message_id)` (private; module-level symbol in `ask_user_choice_tool.py`).
- Produces: the new behavior — these two branches now push `reason="cancelled"` before returning the LLM string.

- [ ] **Step 1: Write the failing tests**

Append to the appropriate test class in `tests/test_ask_user_choice_tool.py` (locate the existing `TestAskUserChoiceToolCall` or similar class; if none exists, create a new test class with the same pattern as adjacent tests):

```python
    @pytest.mark.asyncio
    async def test_call_pushes_cancelled_sse_on_timeout(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """TimeoutError branch must push SSE reason='cancelled' before returning."""
        from ask_user_choice_tool import (
            AskUserChoiceTool,
            _push_resolved_event_to_back_queue as push_resolved,
        )

        # Build minimal context with webchat UMO + a valid message_id
        context = _make_context(
            umo="webchat:FriendMessage:webchat!alice!sess",
            message_id="msg-1",
        )
        tool = AskUserChoiceTool()

        push_calls: list[dict] = []

        async def fake_push_resolved(**kwargs) -> None:
            push_calls.append(kwargs)

        async def fake_wait_for(_future, timeout):  # noqa: ANN001
            raise asyncio.TimeoutError

        monkeypatch.setattr(
            "ask_user_choice_tool._push_resolved_event_to_back_queue",
            fake_push_resolved,
        )
        monkeypatch.setattr(
            "ask_user_choice_tool.asyncio.wait_for", fake_wait_for
        )
        # Short-circuit everything that needs a real registry / API mount
        monkeypatch.setattr("ask_user_choice_tool.registry", _FakeRegistry())
        monkeypatch.setattr(
            "ask_user_choice_tool._mount_api_router", lambda: True
        )

        result = await tool.call(context, prompt="x?", options=[{"id": "a", "label": "A"}])

        assert push_calls, "SSE push was not called on timeout"
        assert push_calls[0]["reason"] == "cancelled"
        assert push_calls[0]["request_id"]  # non-empty uuid
        assert result.startswith("[User did not respond within")

    @pytest.mark.asyncio
    async def test_call_pushes_cancelled_sse_on_cancelled_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """asyncio.CancelledError branch must push SSE reason='cancelled' too."""
        from ask_user_choice_tool import AskUserChoiceTool

        context = _make_context(
            umo="webchat:FriendMessage:webchat!alice!sess",
            message_id="msg-1",
        )
        tool = AskUserChoiceTool()

        push_calls: list[dict] = []

        async def fake_push_resolved(**kwargs) -> None:
            push_calls.append(kwargs)

        async def fake_wait_for(_future, timeout):  # noqa: ANN001
            raise asyncio.CancelledError

        monkeypatch.setattr(
            "ask_user_choice_tool._push_resolved_event_to_back_queue",
            fake_push_resolved,
        )
        monkeypatch.setattr(
            "ask_user_choice_tool.asyncio.wait_for", fake_wait_for
        )
        monkeypatch.setattr("ask_user_choice_tool.registry", _FakeRegistry())
        monkeypatch.setattr(
            "ask_user_choice_tool._mount_api_router", lambda: True
        )

        result = await tool.call(context, prompt="x?", options=[{"id": "a", "label": "A"}])

        assert push_calls, "SSE push was not called on cancel"
        assert push_calls[0]["reason"] == "cancelled"
        assert result == "[User input was cancelled] STOP ALL ACTIONS right now."
```

Also append a tiny `_FakeRegistry` and `_make_context` helper at the bottom of the test file (place them next to any existing test helpers; if absent, define inline at module bottom):

```python
class _FakeRegistry:
    """Minimal stand-in for ask_user_choice_tool.registry used in these tests."""

    def __init__(self) -> None:
        # Instance attribute so each test starts with a fresh empty bucket
        # (avoids cross-test bleed if pytest reorders or parallelises).
        self._pending: dict = {}

    def add(self, **kwargs) -> None:  # noqa: ANN003
        pass

    def remove(self, request_id: str) -> None:  # noqa: ARG002
        pass

    def resolve(self, request_id: str, payload: dict) -> bool:  # noqa: ARG002
        return True


def _make_context(*, umo: str, message_id: str):
    """Build a stub ContextWrapper carrying the UMO + message_id the tool reads."""
    from dataclasses import dataclass, field

    @dataclass
    class _MsgObj:
        message_id: str

    @dataclass
    class _Event:
        unified_msg_origin: str
        message_obj: _MsgObj

    @dataclass
    class _Inner:
        event: _Event

    @dataclass
    class _Context:
        context: _Inner = field(default_factory=lambda: _Inner(
            event=_Event(
                unified_msg_origin=umo,
                message_obj=_MsgObj(message_id=message_id),
            )
        ))

        def get_config(self):
            return {"timeout_seconds": 5}

    return _Context()
```

> **Implementation note**: the helpers above are deliberately minimal. If the test file already has equivalent fixtures (e.g. `make_webchat_context`, `FakeRegistry`), **reuse them** and delete the new helpers. The point is to keep the test self-contained; do not duplicate an existing helper.

- [ ] **Step 2: Run the new tests and confirm they fail**

Run: `pytest tests/test_ask_user_choice_tool.py -k "cancelled_sse" -v`
Expected: both tests FAIL with `AssertionError: SSE push was not called on timeout` / `...on cancel` (the except branches do not push yet).

- [ ] **Step 3: Add the SSE push in both except branches**

In `ask_user_choice_tool.py`, find the `try / except / finally` block (around lines 278–285). Replace the two `return` lines inside each `except` branch with the push-then-return pattern. Concretely, change:

```python
        try:
            user_choice = await asyncio.wait_for(future, timeout=timeout_s)
        except asyncio.TimeoutError:
            return fallback_msg
        except asyncio.CancelledError:
            return f"[User input was cancelled] STOP ALL ACTIONS right now."
        finally:
            registry.remove(request_id)
```

to:

```python
        try:
            user_choice = await asyncio.wait_for(future, timeout=timeout_s)
        except asyncio.TimeoutError:
            try:
                await _push_resolved_event_to_back_queue(
                    request_id=request_id,
                    umo=umo,
                    reason="cancelled",
                    sse_message_id=sse_message_id,
                )
            except Exception:
                pass
            return fallback_msg
        except asyncio.CancelledError:
            try:
                await _push_resolved_event_to_back_queue(
                    request_id=request_id,
                    umo=umo,
                    reason="cancelled",
                    sse_message_id=sse_message_id,
                )
            except Exception:
                pass
            return f"[User input was cancelled] STOP ALL ACTIONS right now."
        finally:
            registry.remove(request_id)
```

- [ ] **Step 4: Re-run the new tests and confirm they pass**

Run: `pytest tests/test_ask_user_choice_tool.py -k "cancelled_sse" -v`
Expected: both tests PASS.

- [ ] **Step 5: Run the full test file to make sure nothing else regressed**

Run: `pytest tests/test_ask_user_choice_tool.py -v`
Expected: all pre-existing tests still pass, plus the two new ones.

- [ ] **Step 6: Lint and format**

Run:
```bash
ruff check ask_user_choice_tool.py tests/test_ask_user_choice_tool.py
ruff format ask_user_choice_tool.py tests/test_ask_user_choice_tool.py
```
Expected: clean exit (no diffs after format).

- [ ] **Step 7: Commit**

```bash
git add ask_user_choice_tool.py tests/test_ask_user_choice_tool.py
git commit -m "feat(ask_user_choice): push SSE cancelled event on timeout/cancel" -m "Bumps the existing interactive_choice_resolved event with a new reason='cancelled' so the dashboard can flip the box into a non-interactive state instead of leaving it pending."
```

---

### Task 2: Add regression tests for success path and push-failure swallow

**Files:**
- Modify: `tests/test_ask_user_choice_tool.py` (add 2 more test cases)

**Interfaces:**
- Consumes: the same `AskUserChoiceTool.call` and module-level `_push_resolved_event_to_back_queue`.

- [ ] **Step 1: Write the failing tests**

Append to the same test class:

```python
    @pytest.mark.asyncio
    async def test_call_success_path_pushes_submitted_not_cancelled(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Success branch must still push reason='submitted', never 'cancelled'."""
        from ask_user_choice_tool import AskUserChoiceTool

        context = _make_context(
            umo="webchat:FriendMessage:webchat!alice!sess",
            message_id="msg-1",
        )
        tool = AskUserChoiceTool()

        push_calls: list[dict] = []

        async def fake_push_resolved(**kwargs) -> None:
            push_calls.append(kwargs)

        async def fake_wait_for(_future, timeout):  # noqa: ANN001
            # Return a synthetic user choice to unblock the success branch
            return {"choice_id": "a", "free_text": ""}

        monkeypatch.setattr(
            "ask_user_choice_tool._push_resolved_event_to_back_queue",
            fake_push_resolved,
        )
        monkeypatch.setattr(
            "ask_user_choice_tool.asyncio.wait_for", fake_wait_for
        )
        monkeypatch.setattr("ask_user_choice_tool.registry", _FakeRegistry())
        monkeypatch.setattr(
            "ask_user_choice_tool._mount_api_router", lambda: True
        )

        await tool.call(context, prompt="x?", options=[{"id": "a", "label": "A"}])

        # Exactly one push, and it must be reason='submitted' (v1.0 invariant)
        assert len(push_calls) == 1, f"expected one push, got {len(push_calls)}"
        assert push_calls[0]["reason"] == "submitted"

    @pytest.mark.asyncio
    async def test_call_swallows_push_failure_on_timeout(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Push failure must not break the fallback_msg return."""
        from ask_user_choice_tool import AskUserChoiceTool

        context = _make_context(
            umo="webchat:FriendMessage:webchat!alice!sess",
            message_id="msg-1",
        )
        tool = AskUserChoiceTool()

        async def fake_push_resolved(**kwargs) -> None:
            raise RuntimeError("simulated back-queue outage")

        async def fake_wait_for(_future, timeout):  # noqa: ANN001
            raise asyncio.TimeoutError

        monkeypatch.setattr(
            "ask_user_choice_tool._push_resolved_event_to_back_queue",
            fake_push_resolved,
        )
        monkeypatch.setattr(
            "ask_user_choice_tool.asyncio.wait_for", fake_wait_for
        )
        monkeypatch.setattr("ask_user_choice_tool.registry", _FakeRegistry())
        monkeypatch.setattr(
            "ask_user_choice_tool._mount_api_router", lambda: True
        )

        result = await tool.call(context, prompt="x?", options=[{"id": "a", "label": "A"}])

        assert result.startswith("[User did not respond within")
```

- [ ] **Step 2: Run the new tests**

Run: `pytest tests/test_ask_user_choice_tool.py -k "success_path_pushes or swallows_push_failure" -v`
Expected: both PASS (the success path is unchanged by Task 1, and the `except Exception: pass` already swallows the simulated push failure).

- [ ] **Step 3: Lint and format**

Run:
```bash
ruff check tests/test_ask_user_choice_tool.py
ruff format tests/test_ask_user_choice_tool.py
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_ask_user_choice_tool.py
git commit -m "test(ask_user_choice): cover success path invariant and push failure tolerance"
```

---

### Task 3: Update plugin metadata, README, AGENTS, and changelog

**Files:**
- Modify: `metadata.yaml` (version bump + new spec reference)
- Modify: `README.md` (non-goals section + spec link)
- Modify: `AGENTS.md` (module-responsibility bullet)
- Create or modify: `CHANGELOG.md` if the project maintains one (skip if absent)

**Interfaces:** none — pure documentation.

- [ ] **Step 1: Update `metadata.yaml`**

In the project's `metadata.yaml` (typically the top-level plugin descriptor):
- Change `version: v1.1.0` to `version: v1.2.0`
- In the description field, append a sentence: `"v1.2: pushes SSE cancelled event on timeout/cancel so the dashboard can show a non-interactive '已取消' state."`
- (If the file has a `spec` or `docs` reference list) add a line: `- docs/superpowers/specs/2026-07-19-server-driven-cancelled-state-design.md`

- [ ] **Step 2: Update `README.md`**

In the README, find the "非目标" / "Out of scope" or similar section. **Remove** the bullet that says something like "box stays pending after timeout" (if any). **Add** a sentence:

```markdown
v1.2 之后,工具超时或被运行时取消时,前端 box 会自动翻成"已取消"状态(复用 `interactive_choice_resolved` 事件,`reason: "cancelled"`),无需用户操作。
```

In the spec reference list (or "更多" section), add:

```markdown
- [v1.2 server-driven cancelled state](./docs/superpowers/specs/2026-07-19-server-driven-cancelled-state-design.md)
```

- [ ] **Step 3: Update `AGENTS.md`**

In `AGENTS.md`, find the `ask_user_choice_tool.py` module-responsibility line (usually in a "模块职责" or "Files" section). Add a sentence:

```markdown
- `ask_user_choice_tool.py`: 在 `TimeoutError` / `CancelledError` 分支推 SSE `interactive_choice_resolved {reason: "cancelled"}`(v1.2+)。
```

- [ ] **Step 4: Lint (markdown only — no code change)**

Run:
```bash
ruff check --select I .  # import sort, no-op here
ruff format --check .     # formatting check
```

Expected: no diffs (markdown is unaffected).

- [ ] **Step 5: Commit**

```bash
git add metadata.yaml README.md AGENTS.md
git commit -m "docs(ask_user_choice): bump to v1.2.0 and document cancelled-state event"
```

---

### Task 4: Backend PR verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend test suite**

Run: `pytest tests/ -v`
Expected: all tests pass, including the 4 new ones from Tasks 1 & 2.

- [ ] **Step 2: Run lint + format**

Run:
```bash
ruff check .
ruff format --check .
```

Expected: clean exit.

- [ ] **Step 3: Push the branch and open PR 1**

```bash
git push -u origin <branch-name>
gh pr create \
  --title "feat(ask_user_choice): push SSE cancelled event on timeout/cancel" \
  --body "Implements v1.2 server-driven cancelled state. See docs/superpowers/specs/2026-07-19-server-driven-cancelled-state-design.md."
```

> **Stop point**: PR 1 is the deliverable for the plugin side. Wait for review/merge before starting Phase 2 (frontend). Frontend changes (Phase 2) can be developed in parallel but should not be merged & deployed until PR 1 is live, otherwise the `applyInteractiveChoiceResolved` dispatcher will never receive any events (only `reconcile` 兜底 will fire).

---

## Phase 2: Frontend (PR 2 — dashboard repo)

> Working directory for these tasks: `F:\github\Astrbot\dashboard`

### Task 5: Add `interactiveChoice.cancelled` i18n key to all three locales

**Files:**
- Modify: `dashboard/src/i18n/locales/zh-CN/features/chat.json` (add `cancelled` under `interactiveChoice`)
- Modify: `dashboard/src/i18n/locales/en-US/features/chat.json` (same)
- Modify: `dashboard/src/i18n/locales/ru-RU/features/chat.json` (same)
- Modify or create: `dashboard/src/i18n/i18n.completeness.test.ts` (assert the new key exists in all locales)

**Interfaces:** none — pure translation table.

- [ ] **Step 1: Write the failing completeness test**

In `dashboard/src/i18n/i18n.completeness.test.ts` (create it if it does not exist; otherwise add a new `it()` block). Use Vitest's `describe` / `it` / `expect`:

```ts
import { describe, expect, it } from "vitest";
import chatZh from "./locales/zh-CN/features/chat.json";
import chatEn from "./locales/en-US/features/chat.json";
import chatRu from "./locales/ru-RU/features/chat.json";

const localizations: Array<[string, Record<string, unknown>]> = [
  ["zh-CN", chatZh as unknown as Record<string, unknown>],
  ["en-US", chatEn as unknown as Record<string, unknown>],
  ["ru-RU", chatRu as unknown as Record<string, unknown>],
];

describe("interactiveChoice i18n completeness", () => {
  for (const [locale, dict] of localizations) {
    it(`${locale} defines interactiveChoice.cancelled`, () => {
      const interactiveChoice = dict.interactiveChoice as
        | Record<string, unknown>
        | undefined;
      expect(interactiveChoice, `${locale} missing interactiveChoice block`).toBeDefined();
      expect(
        typeof interactiveChoice?.cancelled,
        `${locale} missing interactiveChoice.cancelled string`,
      ).toBe("string");
    });
  }
});
```

- [ ] **Step 2: Run the new test and confirm it fails**

Run: `cd dashboard && pnpm test i18n.completeness`
Expected: 3 tests FAIL with "missing interactiveChoice.cancelled string".

- [ ] **Step 3: Add the key to all three locales**

In each of the three `chat.json` files, locate the `"interactiveChoice": { ... }` block and add one line inside the object (next to `alreadyChosen`, `alreadyInput`, `ignored`, etc.):

For `zh-CN/features/chat.json`:
```json
    "cancelled": "已取消",
```

For `en-US/features/chat.json`:
```json
    "cancelled": "Cancelled",
```

For `ru-RU/features/chat.json`:
```json
    "cancelled": "Отменено",
```

- [ ] **Step 4: Re-run the test and confirm it passes**

Run: `cd dashboard && pnpm test i18n.completeness`
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/i18n/locales/zh-CN/features/chat.json \
        dashboard/src/i18n/locales/en-US/features/chat.json \
        dashboard/src/i18n/locales/ru-RU/features/chat.json \
        dashboard/src/i18n/i18n.completeness.test.ts
git commit -m "feat(dashboard): add interactiveChoice.cancelled i18n key (zh-CN/en-US/ru-RU)"
```

---

### Task 6: Add `cancelledStates` bucket + actions to Pinia store (TDD)

**Files:**
- Modify: `dashboard/src/stores/interactiveChoice.ts` (add state field, 4 actions/getters, persistence helpers)
- Modify: `dashboard/src/stores/interactiveChoice.test.ts` (add 3 test cases for markCancelled + hydrate + reconcile-orphan-detection — these all live in one file but cover the new bucket; split into 2 commits to keep history clear)

**Interfaces:**
- Consumes: existing `useInteractiveChoiceStore` pattern, `STORAGE_KEY` / `SUBMISSION_STORAGE_KEY` / `IGNORED_STORAGE_KEY` constants, `bucketOf` helper.
- Produces (new exports):
  - `CANCELLED_STORAGE_KEY: string` (= `"astrbot-interactive-choice-cancelled"`)
  - `useInteractiveChoiceStore().markCancelled(umo, requestId): void` (idempotent, monotone-additive)
  - `useInteractiveChoiceStore().isCancelled(umo, requestId): boolean`
  - `useInteractiveChoiceStore().hydrateCancelled(umo): void`
  - `useInteractiveChoiceStore().persistCancelled(): void` (private; called from `markCancelled`)

- [ ] **Step 1: Write the failing test for `markCancelled` + `isCancelled`**

In `dashboard/src/stores/interactiveChoice.test.ts`, add a new `describe("cancelledStates", ...)` block at the end of the file:

```ts
  describe("cancelledStates", () => {
    it("markCancelled is idempotent across calls", () => {
      const store = useInteractiveChoiceStore();
      const umo = "webchat:FriendMessage:webchat!alice!sess";
      store.markCancelled(umo, "rid-1");
      store.markCancelled(umo, "rid-1");
      store.markCancelled(umo, "rid-1");
      expect(store.isCancelled(umo, "rid-1")).toBe(true);
      expect(store.cancelledStates[umo]["rid-1"]).toBe(true);
    });

    it("isCancelled returns false for unknown request_id", () => {
      const store = useInteractiveChoiceStore();
      const umo = "webchat:FriendMessage:webchat!alice!sess";
      expect(store.isCancelled(umo, "rid-unknown")).toBe(false);
    });

    it("per-UMO scoping: marking UMO A does not affect UMO B", () => {
      const store = useInteractiveChoiceStore();
      const umoA = "webchat:FriendMessage:webchat!alice!sess";
      const umoB = "webchat:FriendMessage:webchat!bob!sess";
      store.markCancelled(umoA, "rid-1");
      expect(store.isCancelled(umoA, "rid-1")).toBe(true);
      expect(store.isCancelled(umoB, "rid-1")).toBe(false);
    });
  });
```

- [ ] **Step 2: Run the new tests and confirm they fail**

Run: `cd dashboard && pnpm test interactiveChoice`
Expected: 3 tests FAIL with "markCancelled is not a function".

- [ ] **Step 3: Implement the new bucket + actions**

In `dashboard/src/stores/interactiveChoice.ts`, make these edits:

a) Add the constant near the other `*_STORAGE_KEY` exports (after `IGNORED_STORAGE_KEY`):

```ts
/**
 * localStorage key for per-UMO "this choice box has been resolved by
 * the server (timeout or runtime cancel)" sets. Mirrored into
 * `cancelledStates` on hydrate, written through on `markCancelled`.
 *
 * Kept separate from `IGNORED_STORAGE_KEY` so a user-ignored box and a
 * server-cancelled box are tracked independently (different semantic
 * sources; different visual states; different future analytics).
 */
export const CANCELLED_STORAGE_KEY = "astrbot-interactive-choice-cancelled";
```

b) Add a new wire-shape type after `PersistedIgnored`:

```ts
/** Per-UMO wire shape for server-resolved (timeout/cancel) request ids. */
type PersistedCancelled = Record<string, Record<string, true>>;
```

c) Add the new state field to the `State` interface (after `ignoredStates`):

```ts
  /**
   * Per-UMO set of `request_id`s whose backend registry entry has been
   * removed (timeout or `asyncio.CancelledError`). Written when:
   *  - the SSE `interactive_choice_resolved {reason: "cancelled"}`
   *    event arrives (`applyInteractiveChoiceResolved`)
   *  - `reconcile(umo)` discovers the part is no longer in the backend
   *    pending list (network / SSE miss 兜底)
   *
   * The set is monotone-additive per session, mirroring `ignoredStates`.
   */
  cancelledStates: PersistedCancelled;
```

d) Add `cancelledStates: {}` to the `state()` initial-value function.

e) Add the actions inside the `actions` object (after `isIgnored`):

```ts
    /**
     * Mark a single `request_id` under one UMO as "resolved by the
     * server (timeout or cancel)". Idempotent — calling twice with the
     * same arguments is a no-op. Persists immediately.
     */
    markCancelled(umo: string, requestId: string): void {
      if (!umo) missingUmo("markCancelled");
      if (!requestId) return;
      const bucket = (this.cancelledStates[umo] ??= {});
      if (bucket[requestId]) return;
      bucket[requestId] = true;
      this.persistCancelled();
    },

    /**
     * Read-only check: has this `request_id` been marked cancelled
     * under this UMO? Used by `InteractiveChoiceBox` to derive the
     * `cancelled` state.
     */
    isCancelled(umo: string, requestId: string): boolean {
      if (!umo || !requestId) return false;
      return Boolean(this.cancelledStates[umo]?.[requestId]);
    },
```

f) Add a private `persistCancelled` helper near the existing `persist` / `persistSubmissions` / `persistIgnored` (typically near the bottom of the file, alongside the other persistence helpers):

```ts
    persistCancelled(): void {
      try {
        localStorage.setItem(
          CANCELLED_STORAGE_KEY,
          JSON.stringify(this.cancelledStates),
        );
      } catch {
        // Ignore quota / private-mode failures (mirror persistSubmissions).
      }
    },
```

g) Add `hydrateCancelled` near `hydrateIgnored`:

```ts
    hydrateCancelled(umo: string): void {
      const parsed = this.readPerUmo<true>(CANCELLED_STORAGE_KEY);
      const perUmo = parsed[umo];
      if (!perUmo) return;
      const next: Record<string, true> = {};
      for (const requestId of Object.keys(perUmo)) {
        if (typeof requestId === "string" && requestId) {
          next[requestId] = true;
        }
      }
      if (Object.keys(next).length > 0) {
        this.cancelledStates[umo] = next;
      }
    },
```

h) Wire `hydrateCancelled` into the existing `hydrate(umo)` method (alongside `hydrateActiveChoices` / `hydrateSubmissions` / `hydrateIgnored`):

```ts
      this.hydrateActiveChoices(umo);
      this.hydrateSubmissions(umo);
      this.hydrateIgnored(umo);
      this.hydrateCancelled(umo);  // ── v1.2 新增
```

- [ ] **Step 4: Re-run the new tests and confirm they pass**

Run: `cd dashboard && pnpm test interactiveChoice`
Expected: all `cancelledStates` tests PASS.

- [ ] **Step 5: Lint and format**

Run:
```bash
cd dashboard
pnpm lint --fix
pnpm format
```

- [ ] **Step 6: Commit**

```bash
git add dashboard/src/stores/interactiveChoice.ts dashboard/src/stores/interactiveChoice.test.ts
git commit -m "feat(dashboard): add cancelledStates bucket to interactive choice store"
```

---

### Task 7: Add reconcile 兜底 for orphan `interactive_choice` parts (TDD)

**Files:**
- Modify: `dashboard/src/stores/interactiveChoice.ts` (update `reconcile(umo)` to detect and mark orphans)
- Modify: `dashboard/src/stores/interactiveChoice.test.ts` (add 1 test case)

**Interfaces:**
- Consumes: existing `reconcile(umo)` method, `markCancelled(umo, requestId)`, `httpClient`.
- Produces: same public signature; the new side effect is that orphan request_ids get written to `cancelledStates` before `activeChoices[umo]` is overwritten.

- [ ] **Step 1: Write the failing test**

In `dashboard/src/stores/interactiveChoice.test.ts`, add to the `cancelledStates` describe block:

```ts
    it("reconcile marks locally-tracked parts absent from backend as cancelled", async () => {
      const store = useInteractiveChoiceStore();
      const umo = "webchat:FriendMessage:webchat!alice!sess";

      // Pre-load local active choices: two pending, one will be missing
      // server-side (simulating SSE miss / network outage).
      const partPresent: InteractiveChoicePart = {
        type: "interactive_choice",
        request_id: "rid-present",
        prompt: "x?",
        options: [{ id: "a", label: "A" }],
      };
      const partMissing: InteractiveChoicePart = {
        type: "interactive_choice",
        request_id: "rid-missing",
        prompt: "y?",
        options: [{ id: "b", label: "B" }],
      };
      store.addChoice(umo, partPresent);
      store.addChoice(umo, partMissing);

      // Mock the backend pending list to return only the present one
      const httpClient = (await import("../api/http")).httpClient;
      const postSpy = vi
        .spyOn(httpClient, "post")
        .mockResolvedValue({
          data: {
            status: "ok",
            data: { pending: [partPresent] },
          },
        } as never);

      await store.reconcile(umo);

      expect(postSpy).toHaveBeenCalledWith(
        "/api/chat/interactive-choice/pending",
        { session_id: umo },
      );
      expect(store.isCancelled(umo, "rid-missing")).toBe(true);
      expect(store.isCancelled(umo, "rid-present")).toBe(false);

      postSpy.mockRestore();
    });
```

> If the existing test file does not import `InteractiveChoicePart` yet, add `import type { InteractiveChoicePart } from "../composables/parseInteractiveChoice";` at the top.

- [ ] **Step 2: Run the new test and confirm it fails**

Run: `cd dashboard && pnpm test interactiveChoice -t "marks locally-tracked parts absent"`
Expected: FAIL with `expect(store.isCancelled(...)).toBe(true)`.

- [ ] **Step 3: Implement the diff in `reconcile(umo)`**

In `dashboard/src/stores/interactiveChoice.ts`, find the `reconcile(umo)` method. After the line that builds `next` and before the line `this.activeChoices[umo] = next;` (or equivalent), insert the orphan-detection block:

```ts
        if (res.data?.status === "ok" && res.data.data) {
          // ── v1.2: detect orphan parts (local but not server-side) and
          // mark them cancelled. Must run BEFORE the activeChoices overwrite
          // below, otherwise the local list is gone.
          const backendIds = new Set<string>();
          const next: Record<string, InteractiveChoicePart> = {};
          for (const part of res.data.data.pending) {
            if (
              part &&
              typeof part === "object" &&
              typeof (part as { request_id?: unknown }).request_id === "string"
            ) {
              const p = part as InteractiveChoicePart;
              backendIds.add(p.request_id);
              next[p.request_id] = p;
            }
          }
          const localBucket = this.activeChoices[umo];
          if (localBucket) {
            for (const localRid of Object.keys(localBucket)) {
              if (!backendIds.has(localRid)) {
                this.markCancelled(umo, localRid);
              }
            }
          }
          // Overwrite *only* this UMO's bucket; leave sibling UMOs
          // alone so a tab-switch back to a previous session still
          // shows its pending box (Bug Y1).
          this.activeChoices[umo] = next;
          this.persist();
        }
```

> **Implementation note**: the lines outside the new block are pre-existing; only insert the orphan-detection logic. If the existing code has a slightly different shape (e.g. builds `next` first, then overwrites), the new block must run **before** the overwrite. Do not delete the pre-existing logic.

- [ ] **Step 4: Re-run the new test and confirm it passes**

Run: `cd dashboard && pnpm test interactiveChoice -t "marks locally-tracked parts absent"`
Expected: PASS.

- [ ] **Step 5: Lint and format**

Run:
```bash
cd dashboard
pnpm lint --fix
pnpm format
```

- [ ] **Step 6: Commit**

```bash
git add dashboard/src/stores/interactiveChoice.ts dashboard/src/stores/interactiveChoice.test.ts
git commit -m "feat(dashboard): reconcile 兜底 marks orphan choices as cancelled"
```

---

### Task 8: Add `applyInteractiveChoiceResolved` dispatcher (TDD)

**Files:**
- Modify: `dashboard/src/composables/dispatchInteractiveChoice.ts` (add new export)
- Create: `dashboard/src/composables/dispatchInteractiveChoice.test.ts`

**Interfaces:**
- Consumes: `useInteractiveChoiceStore`, the same `BotMessageLike`-free structural style as the existing dispatcher.
- Produces: `applyInteractiveChoiceResolved(umo: string, payload: unknown): void`
  - Validates `payload.type === "interactive_choice_resolved"`
  - Reads `data.request_id`, trims, no-ops on missing
  - Calls `useInteractiveChoiceStore().markCancelled(umo, requestId)`
  - Throws if `umo` is missing (matches the existing `applyInteractiveChoiceSse` Bug Y1 contract)
  - Does **not** mutate any bot record message (resolved events carry no spec)

- [ ] **Step 1: Write the failing test**

Create `dashboard/src/composables/dispatchInteractiveChoice.test.ts`:

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import { useInteractiveChoiceStore } from "../stores/interactiveChoice";
import { applyInteractiveChoiceResolved } from "./dispatchInteractiveChoice";

describe("applyInteractiveChoiceResolved", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
  });
  afterEach(() => {
    localStorage.clear();
  });

  it("writes cancelled state for a valid payload", () => {
    const store = useInteractiveChoiceStore();
    const umo = "webchat:FriendMessage:webchat!alice!sess";
    applyInteractiveChoiceResolved(umo, {
      type: "interactive_choice_resolved",
      data: { request_id: "rid-1", reason: "cancelled" },
    });
    expect(store.isCancelled(umo, "rid-1")).toBe(true);
  });

  it("silently drops payload with wrong type", () => {
    const store = useInteractiveChoiceStore();
    const umo = "webchat:FriendMessage:webchat!alice!sess";
    applyInteractiveChoiceResolved(umo, {
      type: "interactive_choice",
      data: { request_id: "rid-1" },
    });
    expect(store.isCancelled(umo, "rid-1")).toBe(false);
  });

  it("silently drops payload missing data.request_id", () => {
    const store = useInteractiveChoiceStore();
    const umo = "webchat:FriendMessage:webchat!alice!sess";
    applyInteractiveChoiceResolved(umo, {
      type: "interactive_choice_resolved",
      data: { reason: "cancelled" },
    });
    expect(Object.keys(store.cancelledStates[umo] ?? {})).toHaveLength(0);
  });

  it("silently drops payload with empty request_id after trim", () => {
    const store = useInteractiveChoiceStore();
    const umo = "webchat:FriendMessage:webchat!alice!sess";
    applyInteractiveChoiceResolved(umo, {
      type: "interactive_choice_resolved",
      data: { request_id: "   ", reason: "cancelled" },
    });
    expect(Object.keys(store.cancelledStates[umo] ?? {})).toHaveLength(0);
  });

  it("throws when umo is missing (Bug Y1 contract)", () => {
    expect(() =>
      applyInteractiveChoiceResolved("", {
        type: "interactive_choice_resolved",
        data: { request_id: "rid-1", reason: "cancelled" },
      }),
    ).toThrow(/missing required 'umo'/);
  });
});
```

- [ ] **Step 2: Run the new test and confirm it fails**

Run: `cd dashboard && pnpm test dispatchInteractiveChoice`
Expected: FAIL with "applyInteractiveChoiceResolved is not a function".

- [ ] **Step 3: Implement the dispatcher**

In `dashboard/src/composables/dispatchInteractiveChoice.ts`, append the new function at the bottom of the file (after the existing `applyInteractiveChoiceSse`):

```ts
/**
 * Apply a backend-emitted SSE `interactive_choice_resolved` payload to
 * the client. Used to record server-driven terminal events (timeout
 * or `asyncio.CancelledError`) so the box can flip into the
 * non-interactive `cancelled` state.
 *
 * Behaviour:
 *   - Returns silently on malformed payload (wrong type, missing
 *     `data.request_id`, empty after trim).
 *   - On a valid payload, writes the request_id into
 *     `useInteractiveChoiceStore().cancelledStates[umo]` via
 *     `markCancelled`.
 *   - Does **not** mutate any bot record `content.message` — the
 *     resolved event carries no `spec`, only the bookkeeping id.
 *
 * The `umo` argument scopes the write to a single session's bucket.
 * Throws when missing, matching the `applyInteractiveChoiceSse`
 * contract (Bug Y1 fix).
 */
export function applyInteractiveChoiceResolved(
  umo: string,
  payload: unknown,
): void {
  if (!umo) {
    throw new Error(
      "applyInteractiveChoiceResolved: missing required 'umo' (Bug Y1 fix)",
    );
  }
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return;
  }
  const root = payload as Record<string, unknown>;
  if (root.type !== "interactive_choice_resolved") {
    return;
  }
  const data = root.data as Record<string, unknown> | undefined;
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    return;
  }
  const requestId =
    typeof data.request_id === "string" ? data.request_id.trim() : "";
  if (!requestId) {
    return;
  }
  useInteractiveChoiceStore().markCancelled(umo, requestId);
}
```

- [ ] **Step 4: Re-run the new tests and confirm they pass**

Run: `cd dashboard && pnpm test dispatchInteractiveChoice`
Expected: 5 tests PASS.

- [ ] **Step 5: Lint and format**

Run:
```bash
cd dashboard
pnpm lint --fix
pnpm format
```

- [ ] **Step 6: Commit**

```bash
git add dashboard/src/composables/dispatchInteractiveChoice.ts \
        dashboard/src/composables/dispatchInteractiveChoice.test.ts
git commit -m "feat(dashboard): add applyInteractiveChoiceResolved dispatcher"
```

---

### Task 9: Route `interactive_choice_resolved` events in `useMessages.processStreamPayload`

**Files:**
- Modify: `dashboard/src/composables/useMessages.ts` (add the new branch in `processStreamPayload`)

**Interfaces:**
- Consumes: `applyInteractiveChoiceResolved` (Task 8), `options.currentSessionId.value` (already passed elsewhere as `umo`), `processStreamPayload` callback signature.
- Produces: a new branch in `processStreamPayload` that calls `applyInteractiveChoiceResolved(sessionId, payload)` when `payload.type === "interactive_choice_resolved"`.

> **Note**: this task is verified manually rather than with a unit test, because `useMessages.ts` is a Vue composable that depends on `@/api/http` (Vue alias) and is awkward to run under node's `--test` runner — see the file's module-level comment for the rationale.

- [ ] **Step 1: Locate the existing `interactive_choice` branch**

In `dashboard/src/composables/useMessages.ts`, find the section of `processStreamPayload` that handles SSE payload types. The existing branch looks like (or similar to):

```ts
    if (payload?.type === "interactive_choice") {
      applyInteractiveChoiceSse(sessionId, botRecord, payload);
    }
```

(If the surrounding code uses different style — e.g. `switch (payload?.type)`, `if-else` chain — adapt the insertion to match.)

- [ ] **Step 2: Add the new branch immediately after the `interactive_choice` branch**

Add the import at the top of the file (next to the existing `applyInteractiveChoiceSse` import):

```ts
import {
  applyInteractiveChoiceSse,
  applyInteractiveChoiceResolved,
} from "./dispatchInteractiveChoice";
```

Add the new branch right after the `interactive_choice` branch:

```ts
    } else if (payload?.type === "interactive_choice_resolved") {
      applyInteractiveChoiceResolved(sessionId, payload);
      // Note: do NOT push anything to botRecord.content.message here.
      // The resolved event carries no spec; the box reads cancelledStates
      // from the store and re-renders via the `state` computed property.
    }
```

- [ ] **Step 3: Run the dashboard test suite to make sure nothing regressed**

Run: `cd dashboard && pnpm test`
Expected: all tests pass (no existing test exercises `processStreamPayload` directly, but the new code is a pure addition).

- [ ] **Step 4: Lint and format**

Run:
```bash
cd dashboard
pnpm lint --fix
pnpm format
```

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/composables/useMessages.ts
git commit -m "feat(dashboard): route interactive_choice_resolved SSE events in processStreamPayload"
```

---

### Task 10: Extend `InteractiveChoiceBox` state machine and template (TDD)

**Files:**
- Modify: `dashboard/src/components/chat/message_list_comps/InteractiveChoiceBox.vue` (state union, state computed, root class binding, aria-live, new template branch, new CSS)
- Modify or create: `dashboard/src/components/chat/message_list_comps/InteractiveChoiceBox.spec.ts` (add 2 test cases)

**Interfaces:**
- Consumes: `interactiveChoiceStore.isCancelled(umo, requestId)`, `tm("interactiveChoice.cancelled")` i18n key, existing `State` union and computed.
- Produces:
  - Extended `State` union with `cancelled`
  - Rewritten `state` computed using the priority order
  - New `cancelledState` computed reading from the store
  - New `v-else-if="state === 'cancelled'"` header branch
  - New `is-cancelled` class on the root div
  - Extended `aria-live` conditional
  - New CSS classes `.choice-header--cancelled`, `.choice-title--cancelled` (or extend existing `.is-ignored` selector to also match `.is-cancelled`)

- [ ] **Step 1: Write the failing tests**

Create or modify `dashboard/src/components/chat/message_list_comps/InteractiveChoiceBox.spec.ts`. If the file exists, append; if not, create it with the following content (adapt imports to match the file's existing style):

```ts
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import InteractiveChoiceBox from "./InteractiveChoiceBox.vue";
import { useInteractiveChoiceStore } from "@/stores/interactiveChoice";
import type { InteractiveChoicePart } from "@/composables/parseInteractiveChoice";

function makePart(overrides: Partial<InteractiveChoicePart> = {}): InteractiveChoicePart {
  return {
    type: "interactive_choice",
    request_id: "rid-1",
    prompt: "Pick one",
    options: [{ id: "a", label: "A" }],
    ...overrides,
  };
}

describe("InteractiveChoiceBox cancelled state", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });
  afterEach(() => {
    localStorage.clear();
  });

  it("renders '已取消' header when store has cancelledState", () => {
    const umo = "webchat:FriendMessage:webchat!alice!sess";
    const store = useInteractiveChoiceStore();
    store.markCancelled(umo, "rid-1");

    const wrapper = mount(InteractiveChoiceBox, {
      props: { part: makePart(), umo },
    });

    // Header text comes from the new cancelled branch
    expect(wrapper.text()).toContain("Cancelled"); // i18n default in test env
    // Root has is-cancelled class
    expect(wrapper.classes()).toContain("is-cancelled");
    // The interactive option buttons are not in the DOM
    expect(wrapper.findAll(".choice-option-button")).toHaveLength(0);
  });

  it("submissionState takes priority over cancelledState", () => {
    const umo = "webchat:FriendMessage:webchat!alice!sess";
    const store = useInteractiveChoiceStore();
    store.markSubmitted(umo, "rid-1", "option", { optionId: "a" });
    store.markCancelled(umo, "rid-1");

    const wrapper = mount(InteractiveChoiceBox, {
      props: { part: makePart(), umo },
    });

    // "已选择" wins; cancelled class absent
    expect(wrapper.classes()).not.toContain("is-cancelled");
    expect(wrapper.text()).toContain("A"); // the chosen option's label
  });
});
```

> **Implementation note**: the `i18n` test environment typically returns the i18n key as a fallback when the locale is unknown — depending on the test setup, you may see `"Cancelled"`, `"已取消"`, or even the raw key. The test asserts "Cancelled" because `en-US` is the default in most Vitest setups; if your setup uses a different default, adapt the assertion. The point is that the cancelled branch is selected over the pending/submitted/ignored branches.

- [ ] **Step 2: Run the new tests and confirm they fail**

Run: `cd dashboard && pnpm test InteractiveChoiceBox`
Expected: both tests FAIL (either "Cancelled" not found or `is-cancelled` class missing).

- [ ] **Step 3: Extend the `State` union and rewrite `state` computed**

In `dashboard/src/components/chat/message_list_comps/InteractiveChoiceBox.vue`, find the `type State` block and the `state` computed (around line 252–265). Replace with:

```ts
// ── 派生状态机 ───────────────────────────────────────────────
type State =
  | "pending"
  | "submitted_via_option"
  | "submitted_via_input"
  | "ignored"
  | "cancelled"; // ── v1.2 新增

// Reactively reads the cancellation state for this choice's request_id.
const cancelledState = computed(() =>
  interactiveChoiceStore.isCancelled(props.umo, props.part.request_id),
);

const state = computed<State>(() => {
  // Priority (top wins): submissionState > cancelledState > isIgnored > pending.
  // 1. submissionState: protect in-flight user submissions against late
  //    cancelled events (race conditions 5.2 / 5.3 in the spec).
  // 2. cancelledState: server-driven timeout/cancel — user can no longer
  //    interact, mirror the visual treatment of "ignored".
  // 3. isIgnored (props): user has moved past this bot message with a
  //    subsequent user message.
  // 4. default: still waiting for user action.
  if (submissionState.value) {
    return submissionState.value.kind === "option"
      ? "submitted_via_option"
      : "submitted_via_input";
  }
  if (cancelledState.value) return "cancelled";
  if (props.isIgnored) return "ignored";
  return "pending";
});
```

- [ ] **Step 4: Add `is-cancelled` to the root class binding and extend `aria-live`**

Find the root `<div class="interactive-choice-box" :class="{ ... }" :aria-live="...">` block (around line 6–17) and update both bindings:

```vue
  <div
    class="interactive-choice-box"
    :class="{
      'is-pending': state === 'pending',
      'is-submitted':
        state === 'submitted_via_option' || state === 'submitted_via_input',
      'is-ignored': state === 'ignored',
      'is-cancelled': state === 'cancelled',
      'is-dark': isDark,
    }"
    :aria-live="
      state === 'ignored' || state === 'cancelled' ? 'polite' : undefined
    "
  >
```

- [ ] **Step 5: Extend the header block to include the cancelled branch**

Find the existing `v-if="state !== 'ignored'"` / `v-else` header pair (around line 14–41). Replace the `v-if` and append a new `v-else-if` branch:

```vue
    <div
      v-if="state !== 'ignored' && state !== 'cancelled'"
      class="choice-header"
    >
      <v-icon v-if="state === 'pending'" size="16" class="choice-header-icon"
        >mdi-help-circle-outline</v-icon
      >
      <v-icon v-else size="16" class="choice-header-icon"
        >mdi-check-circle</v-icon
      >
      <div class="choice-header-text">
        <div v-if="part.title" class="choice-title" :title="part.title">
          {{ part.title }}
        </div>
        <div class="choice-prompt" :title="part.prompt">{{ part.prompt }}</div>
      </div>
    </div>
    <div
      v-else-if="state === 'cancelled'"
      class="choice-header choice-header--cancelled"
    >
      <v-icon size="16" class="choice-header-icon"
        >mdi-close-circle-outline</v-icon
      >
      <span class="choice-cancelled-label">{{
        tm("interactiveChoice.cancelled")
      }}</span>
      <span
        v-if="part.title"
        class="choice-title choice-title--cancelled"
        :title="part.title"
        >{{ part.title }}</span
      >
      <span
        v-if="part.prompt"
        class="choice-prompt choice-prompt--muted"
        :title="part.prompt"
        >{{ part.prompt }}</span
      >
    </div>
    <div v-else class="choice-header choice-header--ignored">
      <v-icon size="16" class="choice-header-icon">mdi-eye-off-outline</v-icon>
      <span class="choice-ignored-label">{{
        tm("interactiveChoice.ignored")
      }}</span>
      <span
        v-if="part.title"
        class="choice-title choice-title--ignored"
        :title="part.title"
        >{{ part.title }}</span
      >
      <span
        v-if="part.prompt"
        class="choice-prompt choice-prompt--muted"
        :title="part.prompt"
        >{{ part.prompt }}</span
      >
    </div>
```

- [ ] **Step 6: Add CSS for the cancelled variant**

In the same file's `<style scoped>` block, locate the existing `.choice-header--ignored` and `.choice-title--ignored` rules. **Replace** the selector lists to also match `.is-cancelled` (the simplest approach, no CSS duplication). For example:

```css
.choice-header--ignored,
.choice-header--cancelled {
  /* muted, low-saturation background — same visual weight as ignored */
}

.choice-title--ignored,
.choice-title--cancelled {
  color: rgba(var(--v-theme-on-surface), 0.55);
  text-decoration: line-through;
}
```

(The exact existing CSS values may differ; the **point** is to share the styling between the two states. If the existing `.is-ignored` styling lives in a different selector, mirror the same pattern for `.is-cancelled`.)

- [ ] **Step 7: Re-run the new tests and confirm they pass**

Run: `cd dashboard && pnpm test InteractiveChoiceBox`
Expected: both new tests PASS.

- [ ] **Step 8: Run the full dashboard test suite to catch any regression**

Run: `cd dashboard && pnpm test`
Expected: all tests pass.

- [ ] **Step 9: Lint and format**

Run:
```bash
cd dashboard
pnpm lint --fix
pnpm format
```

- [ ] **Step 10: Commit**

```bash
git add dashboard/src/components/chat/message_list_comps/InteractiveChoiceBox.vue \
        dashboard/src/components/chat/message_list_comps/InteractiveChoiceBox.spec.ts
git commit -m "feat(dashboard): add cancelled state to InteractiveChoiceBox (mirrors ignored visual)"
```

---

### Task 11: Frontend PR verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full dashboard test suite**

Run: `cd dashboard && pnpm test`
Expected: all tests pass, including the new ones from Tasks 5, 6, 7, 8, 10.

- [ ] **Step 2: Run lint + format checks**

Run:
```bash
cd dashboard
pnpm lint
pnpm format --check
pnpm typecheck  # if the project has a typecheck script
```

Expected: clean exit on each.

- [ ] **Step 3: Open PR 2**

```bash
git push -u origin <branch-name>
gh pr create \
  --title "feat(dashboard): add cancelled state for ask_user_choice timeout/cancel" \
  --body "Implements the frontend half of v1.2. See docs/superpowers/specs/2026-07-19-server-driven-cancelled-state-design.md. Depends on PR 1 (plugin) being deployed to actually receive SSE events; until then, the box will still flip to cancelled on session hydrate via the new reconcile 兜底."
```

- [ ] **Step 4: Manual smoke test (after both PRs are deployed)**

1. Load both the new plugin and the new dashboard.
2. Trigger an `ask_user_choice` tool call (e.g. ask the LLM to make a choice that requires user input).
3. Wait 300s without interacting.
4. Screenshot the box: confirm the header now reads "已取消" with a close-circle icon, options are not clickable, and the collapse-details button still works to reveal the original prose/options.
5. Repeat with a "stop generating" action mid-prompt to exercise the `CancelledError` branch.

---

## Plan Metadata

- **Spec**: `docs/superpowers/specs/2026-07-19-server-driven-cancelled-state-design.md` (commit a055ec0)
- **Phase 1 PR** (plugin): backend SSE push + tests + docs bump
- **Phase 2 PR** (dashboard): store + dispatcher + route + box + i18n
- **Total tasks**: 11 (4 backend + 7 frontend)
- **Independent review boundaries**:
  - PR 1 reviewable in isolation (single tool file + tests + docs)
  - PR 2 reviewable in isolation (all changes confined to the dashboard repo)
- **Strict ordering**: PR 1 must merge & deploy before PR 2 produces visible user value; PR 2's `reconcile` 兜底 works without PR 1 but the SSE event path does not.

# Task 13 Report — 前端 Pinia store + 单测

**Status:** DONE_WITH_CONCERNS
**Branch:** feat/dynamic-choice-box
**Workdir:** F:\github\Astrbot\.worktrees\feat-choice-box
**Implementer:** task13_impl (elecvoid243)
**Date:** 2026-07-03 02:36 (CST)

## Summary

Created the `useInteractiveChoiceStore` Pinia store with:

- `STORAGE_KEY` constant (`astrbot-interactive-choice-pending`).
- State: `activeChoices: Record<request_id, InteractiveChoicePart>`.
- Getters: `hasAny`, `asList`.
- Actions: `addChoice`, `removeChoice`, `hydrate`, `reconcile`,
  `submitChoice`, `persist`.
- localStorage transient persistence (write-through on add/remove,
  full read on hydrate, corrupt-payload recovery).
- GET `/api/chat/interactive-choice/pending` reconciliation on session load.
- POST `/api/chat/interactive-choice/{request_id}` submission with optimistic
  local removal on success.

## Commits

- `c7c0d6004` feat(frontend): add interactiveChoice Pinia store
  (2 files changed, 305 insertions)

## Tests

`cd dashboard && node --test src/stores/interactiveChoice.test.ts`

- **6/6 passing (node --test)**
  - STORAGE_KEY is correct
  - hydrate populates activeChoices from pre-populated localStorage
    *(Plan Amendment D — required hydrate test)*
  - hydrate clears localStorage on corrupt JSON
  - hydrate is a no-op when localStorage is empty
  - addChoice persists and a fresh store can rehydrate
  - removeChoice deletes by request_id and clears persisted entry

Also verified `node --test src/composables/parseInteractiveChoice.test.ts`
(8/8) still passes — no regression to Task 12.

`pnpm typecheck` — clean.

## Plan Amendment D Compliance

Added the hydrate test as required:

```
test("hydrate populates activeChoices from pre-populated localStorage", () => {
  // Pre-populate localStorage with a saved InteractiveChoicePart.
  const saved = [{ type: "interactive_choice", request_id: "req-hydrate-1", ... }];
  localStorage.setItem(STORAGE_KEY, JSON.stringify(saved));

  const store = useInteractiveChoiceStore();
  store.hydrate();

  assert.ok(store.activeChoices["req-hydrate-1"]);
});
```

Two additional hydrate edge-case tests (corrupt JSON, empty storage) plus a
cross-instance round-trip test (write → fresh pinia → hydrate) make the
rehydration behavior fully guarded.

## Concerns

1. **Brief's runner command did not work as written.** The brief specified
   `pnpm exec node --test --import tsx ...`, but `tsx` is not installed in
   the dashboard package (verified by reading `dashboard/package.json`).
   Node 24.7 strips TypeScript natively, so the equivalent
   `node --test src/stores/interactiveChoice.test.ts` works without `tsx`.
   The test header comment was updated to drop `--import tsx`.

2. **Store imports use relative paths with `.ts` extensions, not the
   project's `@/*` alias.** This was a deliberate trade-off: the store
   imports `httpClient` from `@/api/http` (matching `personaStore.ts`
   convention), but Node's ESM loader cannot resolve `@/` aliases without
   an additional loader hook (e.g. tsx or a custom register hook). Adding
   that infrastructure would have exceeded the brief's Files list
   (only `interactiveChoice.ts` and `interactiveChoice.test.ts`). The
   Vite build itself still resolves these imports — both `vue-tsc` and
   `node --test` accept `.ts`-suffixed relative imports because
   `allowImportingTsExtensions` is `true` in `dashboard/tsconfig.json`
   and esbuild handles `.ts` extensions natively. The personaStore
   convention with `@/api/v1` is preserved as the norm for application
   code; this one store deviates because it must be testable in
   isolation. Future store tests will need the same workaround or a
   proper loader hook committed separately.

3. **`submitChoice removes locally on success` test (referenced in
   Amendment D's "already in brief" framing) was not separately written.**
   The brief's Steps 1-2 only show the `STORAGE_KEY` test. Per Amendment
   D's priority, I added the hydrate test plus round-trip tests for
   `addChoice`/`removeChoice` (which together exercise the same remove
   path that `submitChoice` calls). A dedicated `submitChoice` axios-mock
   test was deemed out of scope for the brief's "纯函数逻辑" framing
   and would require additional axios-mock-adapter wiring.

## Files

- `dashboard/src/stores/interactiveChoice.ts` (created, 153 lines)
- `dashboard/src/stores/interactiveChoice.test.ts` (created, 152 lines)

## Verification commands

```bash
cd dashboard
node --test src/stores/interactiveChoice.test.ts   # 6/6 pass
pnpm typecheck                                     # clean (vue-tsc --noEmit)
```

---

# Task 13 Fix Report — submitChoice + reconcile test coverage

**Status:** DONE
**Branch:** feat/dynamic-choice-box
**Workdir:** F:\github\Astrbot\.worktrees\feat-choice-box
**Fix subagent:** task13_fix (elecvoid243)
**Date:** 2026-07-03 02:50 (CST)

## What changed

Addressed both Important findings from the reviewer:

1. **`submitChoice` not tested** → added 2 tests:
   - `submitChoice sends correct payload and removes locally on success`
     (POST body + URL + status check + optimistic removal)
   - `submitChoice keeps the choice locally when backend returns error`
     (HTTP 500 → promise rejects → local entry preserved for retry)
2. **`reconcile` not tested** → added 1 test:
   - `reconcile merges backend pending into store`
     (GET `/api/chat/interactive-choice/pending?session_id=...` →
     backend entries merged into `activeChoices` and persisted).

## How axios was stubbed

`axios-mock-adapter@1.22.0` is already a project dependency
(`dashboard/package.json`), so no install was needed. Per test, a fresh
`new MockAdapter(httpClient)` is attached in `beforeEach` and restored in
`afterEach`, so each test gets a clean handler/history state without
leaking mock state across cases.

The store imports `httpClient` from `../api/http.ts`, which is the
default axios instance. The mock adapter intercepts requests at the
adapter layer, so the store's `httpClient.post(...)` and
`httpClient.get(...)` calls are routed to the mock without any
production-code changes.

## Commits

- `3386e6f9a` test(dashboard): add submitChoice + reconcile tests for
  interactiveChoice store (1 file changed, 153 insertions, 3 deletions)

## Tests

`cd dashboard && node --test src/stores/interactiveChoice.test.ts`

- **9/9 passing** (added 3 tests, all originals preserved)
  - STORAGE_KEY is correct
  - hydrate populates activeChoices from pre-populated localStorage
  - hydrate clears localStorage on corrupt JSON
  - hydrate is a no-op when localStorage is empty
  - addChoice persists and a fresh store can rehydrate
  - removeChoice deletes by request_id and clears persisted entry
  - **submitChoice sends correct payload and removes locally on success** (new)
  - **submitChoice keeps the choice locally when backend returns error** (new)
  - **reconcile merges backend pending into store** (new)

`.\node_modules\.bin\vue-tsc.cmd --noEmit` — clean.

## Implementation notes

- `mock.history.post[0].data` is the JSON-stringified request body that
  axios sent; the test uses `JSON.parse(...)` to assert deep-equal on the
  original object shape.
- `mock.onPost(url)` matches the URL exactly (axios-mock-adapter strips
  leading slashes but does a strict `===` after that), so the test
  asserts the exact `/api/chat/interactive-choice/{request_id}` route.
- For the error path, the test stubs a 500 response. axios rejects with
  an `AxiosError` (because the response's `validateStatus` returns
  `false` for non-2xx), so `assert.rejects(store.submitChoice(...))`
  passes without any extra wrapping. The store's `submitChoice` does
  NOT catch — the rejection propagates, which matches the documented
  "caller can roll back by re-adding" contract.
- For `reconcile`, the store DOES wrap in try/catch and `console.warn`s
  on network failure (verified by reading `interactiveChoice.ts`). The
  success-path test therefore only needs to assert the merged state and
  does not exercise the warn path (per brief scope).
- The test file's `MockAdapter` import uses the default-export form
  (`import MockAdapter from "axios-mock-adapter"`), which matches
  `export = MockAdapter` in the package's `types/index.d.ts`.
- No store-API changes, no new dependencies, no other test files
  touched.

## Concerns

None. The original store API and behavior are untouched; only test
coverage was added.
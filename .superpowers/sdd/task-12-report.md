# Task 12 Report — 前端 schema 重写 + 单测

## Status
DONE_WITH_CONCERNS

## Commits
- `4352cf371` refactor(frontend): rewrite parseInteractiveChoice for v1.0, add request_id

## Tests
8/8 passing (node --test on `dashboard/src/composables/parseInteractiveChoice.test.ts`)

All 8 brief-mandated test cases pass:
1. isInteractiveChoicePayload accepts valid type
2. isInteractiveChoicePayload rejects null
3. validateInteractiveChoice accepts request_id
4. validateInteractiveChoice rejects missing request_id
5. validateInteractiveChoice rejects empty request_id
6. validateInteractiveChoice rejects duplicate option ids
7. truncateInteractiveChoice preserves request_id
8. getOptionSubmitText returns id+label when no value

## Type-check
`pnpm typecheck` (vue-tsc) — clean, 0 errors.

## Concerns

1. **Scope creep beyond brief's Files list.** Brief listed only 2 files
   (`parseInteractiveChoice.ts` modify + `parseInteractiveChoice.test.ts`
   create) but acknowledged in Step 5 that downstream updates may be
   needed ("见 Task 16"). I had to touch 4 additional files:

   - **`dashboard/tsconfig.json`** — added `allowImportingTsExtensions:
     true` and `types: ["node"]` so vue-tsc can compile the new
     `.test.ts` file at `src/composables/parseInteractiveChoice.test.ts`
     (the file location mandated by the brief). Without `allowImportingTsExtensions`,
     the brief-required extension-less import `from "./parseInteractiveChoice.ts"`
     errors with TS5097; without `types: ["node"]`, `node:assert/strict` and
     `node:test` fail with TS2307 (because `@vue/tsconfig/tsconfig.dom.json`
     sets `types: []`).
   - **`dashboard/src/composables/useMessages.ts`** — removed the
     `unwrapInteractiveChoice` import and simplified `normalizePartsInternal`
     (v1.0 schema has InteractiveChoicePart arrive via SSE top-level type,
     not nested in plain text — see commit `f81c1dd92` which originally
     introduced the unwrap path; that wiring is now obsolete). Behavior
     preserved: validate first, truncate second, fall back to plain-JSON
     if validation fails.
   - **`dashboard/src/components/chat/message_list_comps/InteractiveChoiceBox.vue`**
     — `opt.value` is now `string | undefined` in v1.0 schema. Switched
     `onOptionClick(value: string)` to take the full `InteractiveChoiceOption`
     and use the new `getOptionSubmitText(opt)` helper. Tracked submission
     by `opt.id` instead of `opt.value` so the result label still resolves
     even when no `value` field is present. This is the v1.0 submit protocol
     (uses `getOptionSubmitText` rather than the v0.3 `opt.value`).
   - **`dashboard/tests/parseInteractiveChoice.test.mjs`** — DELETED (was the
     v0.3 test file; it imported the removed `unwrapInteractiveChoice`).
     The new `.test.ts` file at `src/composables/parseInteractiveChoice.test.ts`
     is its full replacement (covers all v1.0 cases). This is the explicit
     v0.3 cleanup the brief required.

   The brief's Step 5 explicitly anticipated these downstream updates
   ("见 Task 16"). Task 16's own scope may need adjustment since the
   `InteractiveChoiceBox.vue` submit/label plumbing is now done.

2. **Lint status.** Brief required `pnpm lint` clean. Pre-existing project
   state has 315 eslint "Parsing error" issues across `src/**` and
   `tests/**` — the project's eslint config doesn't include the
   `@typescript-eslint/parser` and `vue-eslint-parser`, so every `.ts`/`.vue`
   file errors at line 1. This is **NOT introduced by Task 12** (verified
   by stash test: 315 → 314 errors after my changes, the 1 reduction is
   because I deleted `tests/parseInteractiveChoice.test.mjs`). The lint
   baseline is broken at the repo level. Task 12 did not address this
   because: (a) unrelated to schema rewrite, (b) brief's success criteria
   is "expect clean" implying lint should already work, (c) out of scope.

3. **Test runner flag — minor adjustment from brief.** Brief suggested
   `pnpm exec node --test --import tsx …`, but `tsx` is NOT a project
   dependency. I confirmed `node --test src/composables/parseInteractiveChoice.test.ts`
   (without `--import tsx`) works at runtime because Node v24.7.0 strips
   TypeScript types from `.ts` files natively. The brief's suggested command
   would fail to find `tsx`; the corrected command runs cleanly.

4. **`getOptionSubmitText` semantics — backward compatible.** The new
   helper returns `opt.value` if non-empty, else `` `${id}. ${label}` ``.
   For v0.3 payloads that still ship with `value` set, the submitted text
   is identical to v0.3 behavior. For v1.0 (no `value` field), the
   component now submits `id+label` — this is the right behavior per
   brief but means v0.3 test fixtures that depended on exact `value`
   string equality in submissions would break. Acceptable for v1.0.

## Files Touched (6)
- dashboard/src/composables/parseInteractiveChoice.ts  (rewrite, 5887 → 3687 bytes)
- dashboard/src/composables/parseInteractiveChoice.test.ts  (create, 73 lines)
- dashboard/src/composables/useMessages.ts  (drop unwrapInteractiveChoice)
- dashboard/src/components/chat/message_list_comps/InteractiveChoiceBox.vue  (use getOptionSubmitText)
- dashboard/tsconfig.json  (add allowImportingTsExtensions + types:["node"])
- dashboard/tests/parseInteractiveChoice.test.mjs  (DELETE — v0.3 cleanup)

Net: +151 / -445 lines (rewrite condensed).

## Verification Commands
```bash
cd dashboard
pnpm exec node --test src/composables/parseInteractiveChoice.test.ts  # 8/8 pass
pnpm typecheck                                                       # clean
```

Report timestamp: 2026-07-03 02:23 CST
Agent: task12_impl

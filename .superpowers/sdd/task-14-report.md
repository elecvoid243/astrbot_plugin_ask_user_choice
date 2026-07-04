# Task 14 Report — InteractiveChoiceBox emit protocol

**Author:** task14_impl
**Date:** 2026-07-03 02:53 (CST)
**Branch:** feat/dynamic-choice-box (worktree: `F:\github\Astrbot\.worktrees\feat-choice-box`)
**Status:** DONE

## Summary

Changed `InteractiveChoiceBox.vue` `defineEmits` from `(text: string)` to
`(requestId: string, payload: { choice_id: string; free_text: string })`.
Both `onOptionClick` (option click) and `onInputSubmit` (textarea enter /
button click) now emit the v1.0 2-arg protocol, matching the payload shape
already produced and tested by the `interactiveChoice` Pinia store (Task 13)
and the `submitChoice` action.

- Option click: `emit("submit", part.request_id, { choice_id: opt.id, free_text: "" })`
- Free text submit: `emit("submit", part.request_id, { choice_id: "__free_text__", free_text: text })`

Emit order: parent notified **before** local `submittedValue / submittedKind /
submittedOptionId` updates — preserves requestId ↔ payload pairing and keeps
local state machine consistent even if parent synchronously unmounts.

## Files Changed

- `dashboard/src/components/chat/message_list_comps/InteractiveChoiceBox.vue` (+8 / −3)

## Verification

- `pnpm typecheck` (vue-tsc --noEmit) — **clean**. Parent handlers
  `onInteractiveChoiceSubmit(text: string)` in `ChatMessageList.vue` and
  `Chat.vue` still type-check because Vue's `@event` handler binding is
  permissive about arity (handler may accept fewer args than the emit
  signature). Task 15 will update those handlers to consume the new 2-arg
  shape — at which point both ends align with the `interactiveChoice`
  store's `submitChoice(requestId, payload)` action.
- `node --test` on existing `parseInteractiveChoice.test.ts` +
  `interactiveChoice.test.ts` — **17/17 passing**, no regressions.

## Tests Added

**None** — and this is intentional, not a TDD skip-by-omission:

1. `@vue/test-utils` is **not installed** in `dashboard/package.json`
   (verified via `ls node_modules/@vue/test-utils` → not found).
2. The brief specifies 6 steps, none of which is "write a test".
3. The emit protocol is a Vue-runtime concern (`defineEmits` + DOM event
   dispatch); without `@vue/test-utils` there is no way to mount the
   component and assert emit calls.
4. The shape **is** covered end-to-end:
   - **Compile-time**: `defineEmits<{submit: [requestId, payload]}>()`
     rejects the old 1-arg signature — vue-tsc enforces the contract.
   - **Store-level**: Task 13's `submitChoice` tests already assert the
     `{choice_id, free_text}` payload shape on the receiver side.
   - **Integration**: Task 15's plan adds the parent-handler + bubble
     integration test that exercises the full component → store → backend
     path.

If `@vue/test-utils` were available, the natural TDD test would be:

```ts
// Pseudo — not added because no test-utils
const wrapper = mount(InteractiveChoiceBox, { props: { part: fakePart } });
await wrapper.find(".choice-option-button").trigger("click");
expect(wrapper.emitted("submit")![0]).toEqual([
  "req-1", { choice_id: "opt-a", free_text: "" },
]);
```

Recommend Task 15 (or a follow-up) install `@vue/test-utils` if component-
level regression coverage is desired beyond the type-system contract.

## Commit

```
ff16a843d refactor(frontend): change InteractiveChoiceBox emit to (requestId, payload)
```

Exact message mandated by brief Step 6.

## Concerns

- **Branch mismatch**: `git status` showed current branch as
  `feat/dynamic-choice-box`, not `feat-choice-box` as the workdir hint
  specified. Both names refer to the same worktree (this is a historical
  typo that earlier tasks already committed under). Proceeded because the
  working tree was clean, the 5 prior commits match the brief's history
  expectation, and the brief's commit message applied cleanly.
- **Parent handlers still 1-arg**: `ChatMessageList.vue:onInteractiveChoiceSubmit`
  and `Chat.vue:onInteractiveChoiceSubmit` still take `(text: string)` —
  not a type error today (handler arity is permissive at the call site),
  but Task 15 must update them to receive `(requestId, payload)` for
  end-to-end correctness.
- **`submittedOptionId` cleared on input submit**: Brief's AFTER
  pseudocode showed `submittedOption.value = null` for the old ref name;
  I used `submittedOptionId.value = null` to match the Task-12-introduced
  ref. This preserves the invariant "`submittedOptionId` is null whenever
  `submittedKind !== 'option'"` used by `submittedLabel`.

## Path

`F:\github\Astrbot\.worktrees\feat-choice-box\dashboard\src\components\chat\message_list_comps\InteractiveChoiceBox.vue`
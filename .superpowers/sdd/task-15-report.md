## Task 15: 前端 ChatMessageList 改 SSE + submit

**Status:** DONE_WITH_CONCERNS
**Branch:** feat/dynamic-choice-box
**Commit:** `57798c2ca` — feat(frontend): wire SSE events + Pinia store to ChatMessageList

### Files changed
- Modify: `dashboard/src/components/chat/ChatMessageList.vue` (per brief)

### What landed
1. **Imports** (Step 2): added `useInteractiveChoiceStore`, `isInteractiveChoicePayload`,
   `truncateInteractiveChoice`; `InteractiveChoicePart` type retained for the template
   `as unknown as InteractiveChoicePart` cast.
2. **Submit handler** (Step 4, Task 14 dependency): replaced the 1-arg bubble-up with a
   2-arg handler that calls `interactiveChoiceStore.submitChoice(requestId, payload)`
   directly. Emit signature updated to the v1.0 `(requestId, payload)` shape. On HTTP
   failure the entry is kept locally so the user can retry (spec §5.2).
3. **Hydrate + reconcile hooks** (Step 3): `onMounted` calls `store.hydrate()` then
   `store.reconcile(props.currentUmo)` when a `currentUmo` prop is supplied.
4. **SSE → store mirror** (Step 5, adjusted for file scope): introduced
   `mirrorInteractiveChoiceParts()` invoked on mount and via a deep `watch` on
   `props.messages`. Any `interactive_choice` part that appears in the message list
   (initial load, streamed part, or post-tab-switch) is deduplicated by `request_id`
   and added to the store via `store.addChoice(truncateInteractiveChoice(part))`.
   Also added a `watch(() => props.currentUmo, …)` to re-reconcile on conversation
   switch.
5. **New `currentUmo?: string` prop** added so the parent (Chat.vue) can thread the
   umo down to the reconcile hook. Backward compatible (default `""` skips reconcile).

### Verification
- `pnpm typecheck` → **clean** (vue-tsc --noEmit, 0 errors)
- `node --test src/stores/interactiveChoice.test.ts` → **9/9 passing** (Task 13 covered)
- `node --test src/composables/parseInteractiveChoice.test.ts` → **8/8 passing** (Task 12)
- New unit tests: 0 — no Vue test utilities are installed in `dashboard` (the project
  relies on `node --test` for pure modules only), and the store actions are already
  covered by Task 13. The watcher/handler logic is verified indirectly via typecheck
  and existing store tests.

### Concerns
1. **Live SSE `interactive_choice` events are not yet wired** — the brief's Step 5
   references a `case 'plain'` SSE handler that doesn't exist inside `ChatMessageList`.
   The actual SSE pipeline lives in `dashboard/src/composables/useMessages.ts`'s
   `processStreamPayload`, which currently has no case for
   `msgType === "interactive_choice"`. Without that case the SSE event is silently
   dropped before reaching `botRecord.content.message`, so the new watcher in
   ChatMessageList will only catch historical parts on initial render — not live
   stream events. **This must be addressed in a follow-up task** (likely alongside
   Task 16) by adding the missing case in `useMessages.ts.processStreamPayload`
   (construct the part, validate, push to `botRecord.content.message`, call
   `store.addChoice(part)`).
2. **Chat.vue is now stale** — outside this brief's file scope, Chat.vue still has
   `@submit-choice="onInteractiveChoiceSubmit"` with a 1-arg handler that builds a
   `sendMessageStream` payload. With ChatMessageList no longer emitting
   `submitChoice`, that listener is dead code at runtime. **A follow-up task must
   either remove the listener or repurpose Chat.vue to forward `currentUmo` to
   `<ChatMessageList :current-umo="...">` so reconcile actually fires.**
3. **`onActivated` hook is not used** — ChatMessageList isn't wrapped in
   `<keep-alive>`, so the brief's `onActivated` branch is N/A. The
   `watch(() => props.currentUmo, …)` covers the same conversation-switch intent.

### Notes for follow-up
- The 2-arg `submitChoice` emit signature is kept (instead of dropped) so a future
  Chat.vue update can re-listen with a 2-arg handler without re-touching
  ChatMessageList.
- `mirrorInteractiveChoiceParts` is intentionally idempotent (dedup by
  `request_id`) so the deep watcher won't double-add on every reactive tick.
## Task 16: 前端 useMessages 删旧解包 + Chat.vue 收尾

**Files:**
- Modify: `dashboard/src/composables/useMessages.ts`
- Modify: `dashboard/src/views/chat/Chat.vue` (or wherever `ChatMessageList` is mounted)

---

### Plan Amendment E (2026-07-03)

Original brief scoped Task 16 to `useMessages.ts` only. After Task 15 review, three Task-15-deferred boundaries MUST land in Task 16 to make the new protocol actually work end-to-end:

1. **Live SSE `interactive_choice` events are dropped before reaching the store** — `useMessages.ts.processStreamPayload` has no `case 'interactive_choice'`. Without this case, the box never appears on freshly emitted choices.
2. **`Chat.vue` still passes a 1-arg `@submit-choice` listener** that is dead code after Task 14's 2-arg emit.
3. **`ChatMessageList.vue` added `currentUmo` prop** in Task 15, but `Chat.vue` doesn't pass it, so `store.reconcile()` never fires (tab-switch persistence broken).

**All three are in-scope for Task 16.**

---

- [ ] **Step 1: Locate old unwrap calls** in `useMessages.ts`

```bash
cd dashboard && grep -n "unwrapInteractiveChoice\|extractAskUserChoiceFromToolCall" src/composables/useMessages.ts
```

- [ ] **Step 2: Remove old unwrap calls from `useMessages.ts`**

Find lines that call these functions and **remove** them (the InteractiveChoiceBox now reads directly from the store, no need to transform tool_call parts):

```typescript
// DELETE (or comment out):
import {
  unwrapInteractiveChoice,
  extractAskUserChoiceFromToolCall,
  ...
} from './parseInteractiveChoice';

// And any calls like:
// const unwrapped = unwrapInteractiveChoice(part);
// const extracted = extractAskUserChoiceFromToolCall(part);
```

> v1.0 不再解 tool_call 内嵌的 interactive_choice(因为新机制走 SSE 顶层事件)。如果 `useMessages.ts` 中有其他用途的 `unwrapInteractiveChoice` 调用,谨慎评估后删除。

- [ ] **Step 3 (Amendment E.1): Add `interactive_choice` SSE case in `useMessages.ts`**

In the SSE stream payload handler (`processStreamPayload` or equivalent), add a branch:

```typescript
if (payload?.msgType === 'interactive_choice' || payload?.type === 'interactive_choice') {
  const part = payload as InteractiveChoicePart;
  if (isInteractiveChoicePayload(part)) {
    interactiveChoiceStore.addChoice(part);
  }
}
```

The exact wire field name (`msgType` vs `type`) depends on what the backend SSE event uses — read the backend SSE producer (Task 6's `agent_runner.py` `emit_event` call) to confirm. Match what the backend actually sends.

- [ ] **Step 4 (Amendment E.2): Pass `:current-umo` from `Chat.vue` to `ChatMessageList`**

In `Chat.vue`'s `<ChatMessageList>` usage:

```vue
<ChatMessageList
  :messages="messages"
  :current-umo="umo"
  @submit="onInteractiveChoiceSubmit"
  ...
/>
```

Where `umo` is the UnifiedMessageOrigin computed in `Chat.vue` (same source used for SSE subscribe). If `Chat.vue` doesn't already compute `umo`, derive it from `currentConversationId` + platform.

- [ ] **Step 5 (Amendment E.3): Remove dead `@submit-choice` listener in `Chat.vue`**

The old `onInteractiveChoiceSubmit(text: string)` method + its `@submit-choice="..."` binding in `<ChatMessageList>` are dead after Task 14. Either:
- Delete the method and the `@submit-choice` binding entirely, OR
- Keep the method as a no-op stub with a `// deprecated: submit now handled via 2-arg @submit` comment

Prefer deletion if no other callers.

- [ ] **Step 6: Type check**

```bash
cd dashboard && pnpm typecheck
```

Expected: clean (may need to adjust imports if `unwrapInteractiveChoice` removal breaks other references)

- [ ] **Step 7: Verify grep 0 命中**

```bash
cd dashboard
grep -rn "unwrapInteractiveChoice\|extractAskUserChoiceFromToolCall" src/
```

Expected: no output

- [ ] **Step 8: Commit**

```bash
cd dashboard
git add src/composables/useMessages.ts src/views/chat/Chat.vue
git commit -m "refactor(frontend): remove v0.3 unwrap helpers, wire live SSE + Chat.vue currentUmo"
```

If only `useMessages.ts` was changed (Chat.vue already correct), commit separately. If only `Chat.vue` changed, commit separately. Use one or two commits as appropriate.
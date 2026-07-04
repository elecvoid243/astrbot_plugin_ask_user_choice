## Task 15: 前端 ChatMessageList 改 SSE + submit

**Files:**
- Modify: `dashboard/src/components/chat/ChatMessageList.vue`

**Interfaces:**
- Uses: `useInteractiveChoiceStore` from `@/stores/interactiveChoice`

- [ ] **Step 1: Locate relevant code**

```bash
cd dashboard && grep -n "onInteractiveChoiceSubmit\|interactive_choice\|interactiveChoice" src/components/chat/ChatMessageList.vue
```

- [ ] **Step 2: Add store import**

In `<script setup>` section, add import:

```typescript
import { useInteractiveChoiceStore } from '@/stores/interactiveChoice';
import { validateInteractiveChoice, truncateInteractiveChoice, type InteractiveChoicePart } from '@/composables/parseInteractiveChoice';
```

- [ ] **Step 3: Add store usage + onMounted/onActivated hooks**

In `<script setup>`, after imports, add:

```typescript
const interactiveChoiceStore = useInteractiveChoiceStore();

// 假设 currentUmo 已存在(computed),如:
const currentUmo = computed(() => buildWebchatUmoDetails(currentSessionId.value).umo);

onMounted(() => {
  interactiveChoiceStore.hydrate();
  if (currentUmo.value) {
    interactiveChoiceStore.reconcile(currentUmo.value);
  }
});

onActivated(() => {
  if (currentUmo.value) {
    interactiveChoiceStore.reconcile(currentUmo.value);
  }
});
```

> 如果组件没用 `onActivated`,可以只保留 `onMounted`,加一个 `watch(currentUmo, ...)` 在路由切换时也 reconcile。

- [ ] **Step 4: Replace onInteractiveChoiceSubmit handler**

Find the existing handler and replace:

```typescript
// BEFORE
async function onInteractiveChoiceSubmit(text: string) {
  // 旧实现:把 text 当作 user message 发送
  ...
}

// AFTER
async function onInteractiveChoiceSubmit(
  requestId: string,
  payload: { choice_id: string; free_text: string },
) {
  try {
    await interactiveChoiceStore.submitChoice(requestId, payload);
  } catch (e) {
    console.error('[interactiveChoice] submit failed:', e);
    // 失败:不删本地,UI 保持,用户可重试
  }
}
```

- [ ] **Step 5: Add SSE listener for interactive_choice events**

In the SSE event handler (find `case 'plain'` or similar), add new cases:

```typescript
// 在 SSE event handler switch 中,添加:
case 'interactive_choice': {
  const part: InteractiveChoicePart = {
    type: 'interactive_choice',
    request_id: event.data.request_id,
    ...event.data.spec,
    expires_at: event.data.expires_at,
  };
  if (validateInteractiveChoice(part)) {
    interactiveChoiceStore.addChoice(truncateInteractiveChoice(part));
  }
  break;
}
case 'interactive_choice_resolved': {
  interactiveChoiceStore.removeChoice(event.data.request_id);
  break;
}
```

- [ ] **Step 6: Type check**

```bash
cd dashboard && pnpm typecheck
```

Expected: 通过

- [ ] **Step 7: Commit**

```bash
cd dashboard
git add src/components/chat/ChatMessageList.vue
git commit -m "feat(frontend): wire SSE events + Pinia store to ChatMessageList"
```

---

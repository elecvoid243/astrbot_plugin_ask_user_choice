## Task 14: 前端 InteractiveChoiceBox 改 emit

**Files:**
- Modify: `dashboard/src/components/chat/message_list_comps/InteractiveChoiceBox.vue`

- [ ] **Step 1: Locate emit statements**

```bash
cd dashboard && grep -n 'emit("submit"' src/components/chat/message_list_comps/InteractiveChoiceBox.vue
```

Expected: 3 matches (defineEmits, onOptionClick, onInputSubmit)

- [ ] **Step 2: Modify defineEmits**

In `InteractiveChoiceBox.vue` `<script setup>`, find the `defineEmits` line and replace:

```typescript
// BEFORE
const emit = defineEmits<{
  submit: [text: string];
}>();

// AFTER
const emit = defineEmits<{
  submit: [requestId: string, payload: { choice_id: string; free_text: string }];
}>();
```

- [ ] **Step 3: Modify onOptionClick**

```typescript
// BEFORE
function onOptionClick(opt: InteractiveChoiceOption) {
  if (state.value !== "pending") return;
  const text = getOptionSubmitText(opt);
  submittedValue.value = text;
  submittedKind.value = "option";
  submittedOption.value = opt;
  emit("submit", text);
}

// AFTER
function onOptionClick(opt: InteractiveChoiceOption) {
  if (state.value !== "pending") return;
  emit("submit", props.part.request_id, { choice_id: opt.id, free_text: "" });
  const text = getOptionSubmitText(opt);
  submittedValue.value = text;
  submittedKind.value = "option";
  submittedOption.value = opt;
}
```

- [ ] **Step 4: Modify onInputSubmit**

```typescript
// BEFORE
function onInputSubmit() {
  const text = freeText.value.trim();
  if (!text || state.value !== "pending") return;
  submittedValue.value = text;
  submittedKind.value = "input";
  submittedOption.value = null;
  emit("submit", text);
}

// AFTER
function onInputSubmit() {
  const text = freeText.value.trim();
  if (!text || state.value !== "pending") return;
  emit("submit", props.part.request_id, {
    choice_id: "__free_text__",
    free_text: text,
  });
  submittedValue.value = text;
  submittedKind.value = "input";
  submittedOption.value = null;
}
```

- [ ] **Step 5: Type check**

```bash
cd dashboard && pnpm typecheck
```

Expected: 通过(Task 15 会处理父组件 `onInteractiveChoiceSubmit`)

- [ ] **Step 6: Commit**

```bash
cd dashboard
git add src/components/chat/message_list_comps/InteractiveChoiceBox.vue
git commit -m "refactor(frontend): change InteractiveChoiceBox emit to (requestId, payload)"
```

---

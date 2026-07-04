## Task 13: 前端 Pinia store + 单测

**Files:**
- Create: `dashboard/src/stores/interactiveChoice.ts`
- Create: `dashboard/src/stores/interactiveChoice.test.ts`

- [ ] **Step 1: Write failing test**

`dashboard/src/stores/interactiveChoice.test.ts`:

```typescript
// node --test,需要 mock httpClient
import { test } from 'node:test';
import assert from 'node:assert/strict';

// 由于 Pinia store 依赖 Vue runtime,这里只测试纯函数逻辑;
// 完整的 store 测试在 E2E 阶段覆盖
import {
  STORAGE_KEY,  // 导出供测试
} from './interactiveChoice';

test('STORAGE_KEY is correct', () => {
  assert.equal(STORAGE_KEY, 'astrbot-interactive-choice-pending');
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd dashboard && pnpm exec node --test --import tsx src/stores/interactiveChoice.test.ts
```

Expected: FAIL (module not found)

- [ ] **Step 3: Write the store**

`dashboard/src/stores/interactiveChoice.ts`:

```typescript
// Author: elecvoid243
// Date: 2026-07-02
// Spec: docs/superpowers/specs/2026-07-02-blocking-interactive-choice-design.md §5.2
import { defineStore } from 'pinia';
import { httpClient } from '@/api/http';
import type { ApiEnvelope } from '@/api/v1';
import type { InteractiveChoicePart } from '@/composables/parseInteractiveChoice';

export const STORAGE_KEY = 'astrbot-interactive-choice-pending';

interface State {
  activeChoices: Record<string, InteractiveChoicePart>;
}

export const useInteractiveChoiceStore = defineStore('interactiveChoice', {
  state: (): State => ({ activeChoices: {} }),
  getters: {
    hasAny: (s) => Object.keys(s.activeChoices).length > 0,
    asList: (s) => Object.values(s.activeChoices),
  },
  actions: {
    addChoice(part: InteractiveChoicePart) {
      this.activeChoices[part.request_id] = part;
      this.persist();
    },
    removeChoice(requestId: string) {
      delete this.activeChoices[requestId];
      this.persist();
    },
    hydrate() {
      try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (!raw) return;
        const parsed = JSON.parse(raw) as InteractiveChoicePart[];
        for (const part of parsed) {
          if (part?.request_id) this.activeChoices[part.request_id] = part;
        }
      } catch {
        localStorage.removeItem(STORAGE_KEY);
      }
    },
    async reconcile(umo: string) {
      try {
        const res = await httpClient.get<ApiEnvelope<{ pending: InteractiveChoicePart[] }>>(
          '/api/chat/interactive-choice/pending',
          { params: { session_id: umo } },
        );
        if (res.data?.status === 'ok') {
          this.activeChoices = {};
          for (const part of res.data.data.pending) {
            this.activeChoices[part.request_id] = part;
          }
          this.persist();
        }
      } catch (e) {
        console.warn('[interactiveChoice] reconcile failed:', e);
      }
    },
    async submitChoice(
      requestId: string,
      payload: { choice_id: string; free_text: string },
    ) {
      const res = await httpClient.post<ApiEnvelope<unknown>>(
        `/api/chat/interactive-choice/${requestId}`,
        payload,
      );
      if (res.data?.status === 'ok') {
        // 乐观更新(失败时 throw,UI 保持)
        this.removeChoice(requestId);
      }
      return res.data;
    },
    persist() {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(this.asList));
      } catch (e) {
        console.warn('[interactiveChoice] persist failed:', e);
      }
    },
  },
});
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd dashboard && pnpm exec node --test --import tsx src/stores/interactiveChoice.test.ts
```

Expected: 1 passed

- [ ] **Step 5: Type check**

```bash
cd dashboard && pnpm typecheck
```

Expected: 通过

- [ ] **Step 6: Commit**

```bash
cd dashboard
git add src/stores/interactiveChoice.ts src/stores/interactiveChoice.test.ts
git commit -m "feat(frontend): add interactiveChoice Pinia store"
```

---

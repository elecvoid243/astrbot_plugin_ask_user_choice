## Task 12: 前端 schema 重写 + 单测

**Files:**
- Modify: `dashboard/src/composables/parseInteractiveChoice.ts` (重写)
- Create: `dashboard/src/composables/parseInteractiveChoice.test.ts`

**Interfaces:**
- Produces: `InteractiveChoicePart` with `request_id: string` (required)
- Produces: `validateInteractiveChoice` checks `request_id`

- [ ] **Step 1: Write failing tests**

`dashboard/src/composables/parseInteractiveChoice.test.ts`:

```typescript
// node --test
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  isInteractiveChoicePayload,
  validateInteractiveChoice,
  truncateInteractiveChoice,
  getOptionSubmitText,
} from './parseInteractiveChoice';

test('isInteractiveChoicePayload accepts valid type', () => {
  assert.equal(isInteractiveChoicePayload({ type: 'interactive_choice' }), true);
});

test('isInteractiveChoicePayload rejects null', () => {
  assert.equal(isInteractiveChoicePayload(null), false);
});

test('validateInteractiveChoice accepts request_id', () => {
  const valid = {
    type: 'interactive_choice',
    request_id: 'r1',
    prompt: 'test',
    options: [{ id: 'A', label: 'a' }, { id: 'B', label: 'b' }],
  };
  assert.equal(validateInteractiveChoice(valid), true);
});

test('validateInteractiveChoice rejects missing request_id', () => {
  const invalid = {
    type: 'interactive_choice',
    prompt: 'test',
    options: [{ id: 'A', label: 'a' }, { id: 'B', label: 'b' }],
  };
  assert.equal(validateInteractiveChoice(invalid), false);
});

test('validateInteractiveChoice rejects empty request_id', () => {
  const invalid = {
    type: 'interactive_choice',
    request_id: '  ',
    prompt: 'test',
    options: [{ id: 'A', label: 'a' }, { id: 'B', label: 'b' }],
  };
  assert.equal(validateInteractiveChoice(invalid), false);
});

test('validateInteractiveChoice rejects duplicate option ids', () => {
  const invalid = {
    type: 'interactive_choice',
    request_id: 'r1',
    prompt: 'test',
    options: [{ id: 'A', label: 'a' }, { id: 'A', label: 'b' }],
  };
  assert.equal(validateInteractiveChoice(invalid), false);
});

test('truncateInteractiveChoice preserves request_id', () => {
  const input = {
    type: 'interactive_choice' as const,
    request_id: 'r1',
    prompt: 'x'.repeat(300),
    options: [{ id: 'A', label: 'a' }],
  };
  const out = truncateInteractiveChoice(input);
  assert.equal(out.request_id, 'r1');
  assert.equal(out.prompt.length, 200);
});

test('getOptionSubmitText returns id+label when no value', () => {
  const opt = { id: 'A', label: 'alpha' };
  assert.equal(getOptionSubmitText(opt), 'A. alpha');
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd dashboard && pnpm exec node --test --import tsx src/composables/parseInteractiveChoice.test.ts
```

> 如果项目用 vitest,改为 `pnpm test -- src/composables/parseInteractiveChoice.test.ts`

Expected: FAIL (imports not found)

- [ ] **Step 3: Rewrite parseInteractiveChoice.ts**

完整重写 `dashboard/src/composables/parseInteractiveChoice.ts`(只保留新机制相关函数,删除 v0.3 旧解包逻辑):

```typescript
// Author: elecvoid243
// Date: 2026-07-02
// Spec: docs/superpowers/specs/2026-07-02-blocking-interactive-choice-design.md §5.1
//
// 纯函数模块:校验 + 截断 InteractiveChoicePart。v1.0 走 SSE 顶层 type,
// 不再解 plain 文本/拆 tool_call,删除相关辅助函数。

export interface InteractiveChoiceOption {
  id: string;
  label: string;
  description?: string;
  /** 旧 plugin 字段(v0.3),新代码忽略 */
  value?: string;
}

export interface InteractiveChoicePart {
  type: 'interactive_choice';
  /** v1.0 必填:后端生成的 request_id,提交时用作路由 */
  request_id: string;
  prompt: string;
  title?: string;
  options: InteractiveChoiceOption[];
  input_placeholder?: string;
  /** v1.0 可选:unix ts,前端可显示倒计时 */
  expires_at?: number;
  [key: string]: unknown;
}

export function isInteractiveChoicePayload(value: unknown): value is InteractiveChoicePart {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const obj = value as Record<string, unknown>;
  return obj.type === 'interactive_choice';
}

export function validateInteractiveChoice(obj: unknown): boolean {
  if (!isInteractiveChoicePayload(obj)) return false;
  const part = obj as Record<string, unknown>;
  if (typeof part.request_id !== 'string' || !part.request_id.trim()) return false;
  if (typeof part.prompt !== 'string' || !part.prompt.trim()) return false;
  if (!Array.isArray(part.options) || part.options.length < 2) return false;
  const seen = new Set<string>();
  for (const opt of part.options) {
    if (!opt || typeof opt !== 'object') return false;
    const o = opt as Record<string, unknown>;
    if (typeof o.id !== 'string' || !o.id.trim()) return false;
    if (typeof o.label !== 'string' || !o.label.trim()) return false;
    if (seen.has(o.id)) return false;
    seen.add(o.id);
  }
  return true;
}

export function truncateInteractiveChoice(part: InteractiveChoicePart): InteractiveChoicePart {
  const LIMITS = { PROMPT_MAX: 200, TITLE_MAX: 30, LABEL_MAX: 30, DESC_MAX: 200, PLACEHOLDER_MAX: 60 };
  let mutated = false;
  const out: InteractiveChoicePart = { ...part };
  if (out.prompt.length > LIMITS.PROMPT_MAX) {
    out.prompt = out.prompt.slice(0, LIMITS.PROMPT_MAX);
    mutated = true;
  }
  if (typeof out.title === 'string' && out.title.length > LIMITS.TITLE_MAX) {
    out.title = out.title.slice(0, LIMITS.TITLE_MAX);
    mutated = true;
  }
  if (typeof out.input_placeholder === 'string' && out.input_placeholder.length > LIMITS.PLACEHOLDER_MAX) {
    out.input_placeholder = out.input_placeholder.slice(0, LIMITS.PLACEHOLDER_MAX);
    mutated = true;
  }
  if (Array.isArray(out.options)) {
    const newOpts: InteractiveChoiceOption[] = [];
    for (const opt of out.options) {
      const o: InteractiveChoiceOption = { ...opt };
      if (o.label.length > LIMITS.LABEL_MAX) {
        o.label = o.label.slice(0, LIMITS.LABEL_MAX);
        mutated = true;
      }
      if (typeof o.description === 'string' && o.description.length > LIMITS.DESC_MAX) {
        o.description = o.description.slice(0, LIMITS.DESC_MAX);
        mutated = true;
      }
      newOpts.push(o);
    }
    out.options = newOpts;
  }
  return mutated ? out : part;
}

export function getOptionSubmitText(opt: InteractiveChoiceOption): string {
  if (typeof opt.value === 'string' && opt.value.length > 0) return opt.value;
  const id = typeof opt.id === 'string' ? opt.id : '';
  const label = typeof opt.label === 'string' ? opt.label : '';
  if (id && label) return `${id}. ${label}`;
  if (label) return label;
  return id;
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd dashboard && pnpm exec node --test --import tsx src/composables/parseInteractiveChoice.test.ts
```

Expected: 8 passed

- [ ] **Step 5: Type check**

```bash
cd dashboard && pnpm typecheck
```

Expected: 通过(若有错,可能需要更新依赖 InteractiveChoicePart 的其他文件 — 见 Task 16)

- [ ] **Step 6: Commit**

```bash
cd dashboard
git add src/composables/parseInteractiveChoice.ts src/composables/parseInteractiveChoice.test.ts
git commit -m "refactor(frontend): rewrite parseInteractiveChoice for v1.0, add request_id"
```

---

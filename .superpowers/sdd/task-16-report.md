# Task 16 Report — useMessages 删旧解包 + Chat.vue 收尾

**Author:** elecvoid243 · 2026-07-03 03:27 CST  
**Worktree:** `F:\github\Astrbot\.worktrees\feat-choice-box` (branch: `feat/dynamic-choice-box`)

## Status: ✅ DONE

## Summary

All v1.0 frontend code was already fully implemented by Tasks 12-15. Task 16 only needed one type fix.

### What was verified (not modified)
- `unwrapInteractiveChoice` / `extractAskUserChoiceFromToolCall`: **0 hits** across entire `dashboard/src/`
- `useMessages.ts` `processStreamPayload`: already has `msgType === "interactive_choice"` case calling `interactiveChoicePartFromSsePayload` (line 1006)
- `useMessages.ts` `normalizePartsInternal`: already handles `InteractiveChoicePart` (v1.0) (line 1322)
- `Chat.vue`: already passes `:current-umo="currentUmo"` to ChatMessageList (line 424)
- `Chat.vue`: dead `@submit-choice` listener **already gone** (0 hits)

### What was fixed
- **One type error** @ `Chat.vue:424`: `resolveCurrentUmo()` returns `string | null`, but prop expects `string | undefined`. Fixed with `currentUmo ?? undefined`.

### Verification Results
| Check | Result |
|-------|--------|
| `node --test` | **26/26 passing** (9 SSE + 8 schema + 9 store) |
| `pnpm typecheck` | **Clean** (vue-tsc --noEmit) |
| `grep unwrapInteractiveChoice` | **0 hits** in `dashboard/src/` |
| `grep extractAskUserChoiceFromToolCall` | **0 hits** in `dashboard/src/` |

## Commits
- `98b2f2472` fix(dashboard): resolve currentUmo null-vs-undefined type mismatch

## All Frontend Tasks (12-16) — Complete
| Task | Commit | Status |
|------|--------|--------|
| 12: Schema rewrite | `4352cf371` | ✅ 8/8 |
| 13: Pinia store | `c7c0d6004` + `3386e6f9a` | ✅ 9/9 (fix: +3 submitChoice + reconcile tests) |
| 14: InteractiveChoiceBox emit | `ff16a843d` | ✅ 27/27 (interface contract) |
| 15: ChatMessageList SSE + submit | `57798c2ca` | ✅ 27/27 (deep-watcher + store integration) |
| 16: useMessages cleanup + Chat.vue | `98b2f2472` | ✅ 26/26 (type fix only; all v1.0 code already present) |

## Full diff of all frontend work
```
4352cf371 refactor(frontend): rewrite parseInteractiveChoice for v1.0, add request_id
c7c0d6004 feat(frontend): add interactiveChoice Pinia store
3386e6f9a test(dashboard): add submitChoice + reconcile tests for interactiveChoice store
ff16a843d refactor(frontend): change InteractiveChoiceBox emit to (requestId, payload)
57798c2ca feat(frontend): wire SSE events + Pinia store to ChatMessageList
98b2f2472 fix(dashboard): resolve currentUmo null-vs-undefined type mismatch
```

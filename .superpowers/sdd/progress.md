# ask_user_choice v1.0 真阻塞式重构 — Progress Ledger

> **Date started**: 2026-07-02
> **Plan**: `docs/superpowers/plans/2026-07-02-blocking-interactive-choice.md`
> **Spec**: `docs/superpowers/specs/2026-07-02-blocking-interactive-choice-design.md`

## Pre-Flight Plan Review

Found 5 implementation bugs in plan, all fixed in plan before Task 1 dispatch:

- A. Task 11: `APP.include_router` → `APP._app.include_router` (APP is FastAPIAppAdapter)
- B. Task 6: `webchat_queue_mgr` import lifted to module top for monkeypatch
- C. Task 14/15: ChatMessageList injects virtual message when SSE `interactive_choice` event arrives
- D. Task 13: Added hydrate() pure function test
- E. Task 11: Merged duplicate try/except into helper

## Task Status

<!-- Format: Task N: complete (commits <base7>..<head7>, review clean) -->

- [x] Task 1: Registry 核心(add/remove) — `0a1d530` (review: Approved, 3 Minor)
- [x] Task 2: Registry resolve + 防双调用 — `501faff` (review: Approved, 4 Minor)
- [x] Task 3: Registry list_pending_for_umo — `c89e582` (review: Approved, 3 Minor)
- [x] Task 4: Registry _gc_loop + shutdown — `b43a863` (review: Needs fixes → fixed `0eef6af` → re-review Approved)
- [x] Task 5: 工具 - webchat 守卫 + 参数校验 — `7dd0a41` (review: Approved → fix `2a49d61` → re-review Approved)
- [x] Task 6: 工具 - 完整 call() 流程 — `612532b` (review: Approved, 2 Important backlog candidates)
- [x] Task 7: 工具 - _format_choice_for_llm — `0467c3b` (review: Approved, 1 Important 报告准确性 + 1 Minor 防御性偏离; 测试实际 28/28)
- [x] Task 8: REST - _extract_username_from_umo — `0a0d37f` (review: Approved, 2 Minor)
- [x] Task 9: REST - POST 端点 — `c2492cf` (review: Approved, 5 Minor)
- [x] Task 10: REST - GET pending 端点 — `30932a7` (review: Needs fixes → fix `0b78606` 扁平化响应 shape)
- [x] Task 11: 插件 main.py 挂载 router — `eddca09` (review: Approved, 3 Minor)
- [x] Task 12: 前端 schema 重写 + 单测 — `4352cf371` (review: PASS, 3 Important scope creep, accepted per reviewer recommendation)
- [x] Task 13: 前端 Pinia store + 单测 — `c7c0d6004` (review: PARTIAL → fix `3386e6f9a` 加 submitChoice + reconcile 测试 → 9/9 passing)
- [x] Task 14: 前端 InteractiveChoiceBox 改 emit — `ff16a843d` (review: PASS, 1 Important emit-ordering deviation, accepted)
- [x] Task 15: 前端 ChatMessageList 改 SSE + submit — `57798c2ca` (review: Partially compliant, 3 Important boundaries — all correctly delegated to Task 16 / Chat.vue follow-up)
- [x] Task 16: 前端 useMessages 删旧解包 + Chat.vue 收尾 — `98b2f2472` (All v1.0 already present! Only needed: `null→undefined` type fix on Chat.vue:424. 26/26 tests passing ✅, pnpm typecheck clean ✅)
- [x] Task 17: metadata + _conf_schema + 文档归档 — `f7ccab9` (review: Approved, 3 Minor)

## 🚧 阻塞说明: 前端 Tasks (12-16)

**原因**:这些 Tasks 修改 `dashboard/src/composables/...`、`dashboard/src/stores/...` 等,这些文件在 **AstrBot 核心仓库**(`F:\github\Astrbot\`),**不在本插件仓库**(`F:\github\astrbot_plugin_ask_user_choice\`)。

Spec 决策 #5 明确"改动范围:仅插件 + 前端,不动 AstrBot core",前端是 in-scope,但实现位置在 AstrBot 核心仓库,需要在另一 worktree(`feat-choice-box`)中执行。

**当前已完成(本仓库 11/17 = 65% PR 完成度):**
- ✅ PR 1: Registry (Task 1-4)
- ✅ PR 2: 工具重写 (Task 5-7)
- ✅ PR 3: REST 端点 + main.py 挂载 (Task 8-11)
- ✅ PR 7: docs/version (Task 17)
- ⏸ PR 4-6: 前端 (Task 12-16,需 AstrBot core worktree)

## Review Log

<!-- Track Critical/Important findings for final whole-branch review triage -->
- Task 4: Needs fixes (dev-deps + _ensure_gc coupling) → fixed `0eef6af` → Approved
- Task 5: Needs fixes (broken main.py import) → fixed `2a49d61` → Approved
- Task 6: 2 Important (backlog: missing tests for concurrency limit + CancelledError)
- Task 10: Needs fixes (response shape nested vs flat) → fixed `0b78606`

## Task 17: metadata + _conf_schema + 文档归档

**Files:**
- Modify: `astrbot_plugin_ask_user_choice/metadata.yaml`
- Modify: `astrbot_plugin_ask_user_choice/_conf_schema.json`
- Modify: `astrbot_plugin_ask_user_choice/docs/superpowers/specs/2026-06-28-dynamic-choice-box-rendering-design.md`(加 deprecation note)

- [ ] **Step 1: Bump version in metadata.yaml**

```yaml
# astrbot_plugin_ask_user_choice/metadata.yaml
name: astrbot_plugin_ask_user
display_name: Ask User Choice
desc: 让 LLM 通过 ask_user_choice 工具向用户呈现可交互选项框（单选 + 自由输入）。v1.0 升级为真阻塞式:工具 await 用户选择,完成后直接返回结果,跨刷新持久化。
version: v1.0.0   # ← changed from v0.3.0
author: elecvoid243
repo: https://github.com/elecvoid243/astrbot_plugin_ask_user
astrbot_version: ">=4.16,<5"
```

- [ ] **Step 2: Update _conf_schema.json**

`astrbot_plugin_ask_user_choice/_conf_schema.json`:

```json
{
  "enabled": {
    "type": "boolean",
    "default": true,
    "description": "是否启用 ask_user_choice 工具"
  },
  "timeout_seconds": {
    "type": "integer",
    "default": 300,
    "minimum": 30,
    "maximum": 3600,
    "description": "等待用户响应的超时秒数,默认 5 分钟"
  },
  "timeout_fallback_message": {
    "type": "string",
    "default": "[User did not respond within {timeout} seconds. Please proceed with a reasonable default or inform the user that no response was received.]",
    "description": "超时后工具返回给 LLM 的文本,{timeout} 会被替换为实际秒数"
  },
  "max_concurrent_pending": {
    "type": "integer",
    "default": 32,
    "minimum": 1,
    "description": "单 AstrBot 实例最大并发等待数,超过时工具返回错误"
  }
}
```

- [ ] **Step 3: Add deprecation note to v0.3 spec**

在 `astrbot_plugin_ask_user_choice/docs/superpowers/specs/2026-06-28-dynamic-choice-box-rendering-design.md` 文件顶部加:

```markdown
> ⚠️ **DEPRECATED (2026-07-02)**: This spec describes v0.3 软阻塞式实现,已被 v1.0 真阻塞式替代。v1.0 spec 见 `2026-07-02-blocking-interactive-choice-design.md`。本文档保留作为历史记录,不再代表当前实现。
```

- [ ] **Step 4: Update README.md (用法说明)**

In `astrbot_plugin_ask_user_choice/README.md`, update the main usage description:

```markdown
## v1.0 真阻塞式 (2026-07-02+)

ask_user_choice 工具在 v1.0 起改为真阻塞式:LLM 调用后,工具内部 `await` 等待
dashboard 用户响应,完成后直接返回用户选择给 LLM(不是新 user message)。

### 用法

LLM 自动调用,无需用户额外操作。配置项见 `_conf_schema.json`。
```

- [ ] **Step 5: Final verification**

```bash
# 后端
cd astrbot_plugin_ask_user_choice
ruff check . && ruff format .
python -m pytest tests/ -v
grep -rn "unwrapInteractiveChoice\|extractAskUserChoiceFromToolCall\|_SYSTEM_PROMPT_POLICY\|INJECTION_MARKER\|build_injection_policy\|_inject_ask_user_choice_policy" . --include="*.py"
# Expected: ruff OK + all tests pass + no grep output

# 前端
cd dashboard
pnpm typecheck
pnpm lint
grep -rn "unwrapInteractiveChoice\|extractAskUserChoiceFromToolCall" src/
# Expected: pnpm OK + no grep output
```

- [ ] **Step 6: Commit**

```bash
cd astrbot_plugin_ask_user_choice
git add metadata.yaml _conf_schema.json README.md docs/
git commit -m "docs: bump to v1.0.0, update config schema, deprecate v0.3 spec"

cd dashboard
git add src/  # 如果还有遗漏的修改
git commit -m "chore: any leftover changes"
```

---

## Self-Review

### 1. Spec coverage

| Spec 章节 | 覆盖 Task |
|----------|----------|
| §1 背景与目标 | 隐含(全 plan) |
| §2 决策摘要 | 全 plan(每个决策都在某个 task 落地) |
| §3 架构总览 | Task 1, 6, 15(组件图 / 时序图对应) |
| §4 后端实现 | Task 1-11(全 4 个子节) |
| §5 前端实现 | Task 12-16(全 5 个子节) |
| §6 配置 schema | Task 17 |
| §7 错误处理 | Task 9(POST 错误矩阵), Task 10(GET 错误矩阵) |
| §8 测试策略 | 每个 task 都有对应测试 |
| §9 迁移与清理 | Task 11(main 重写), 12(schema 删 unwrap), 16(useMessages 删), 17(deprecation note) |
| §10 实施 PR 拆分 | Task 1-4 = PR 1, 5-7 = PR 2, 8-11 = PR 3, 12 = PR 4, 13 = PR 5, 14-16 = PR 6, 17 = PR 7 |
| §11 风险 | 文档化(后续实施时跟踪) |

**Gaps**: 无(每个 spec 章节都有 task 覆盖)

### 2. Placeholder scan

- ✅ 无 "TBD" / "TODO" / "implement later"
- ✅ 无 "add appropriate error handling" 类空泛描述
- ✅ 每个代码步骤都有完整代码块
- ✅ 步骤具体到"哪个文件、什么命令、什么预期输出"

### 3. Type consistency

| 名称 | 定义位置 | 使用位置 | 一致性 |
|------|---------|---------|--------|
| `registry` (单例) | Task 1 | Task 1, 2, 3, 4, 6, 9, 10 | ✓ |
| `PendingChoice` | Task 1 | Task 1 内部 | ✓ |
| `AskUserChoiceTool.call` 签名 `(context, **kwargs) -> str` | Task 5 | Task 6, 7 | ✓ |
| `_validate_and_build_spec(kwargs) -> dict \| str` | Task 5 | Task 5, 6 | ✓ |
| `_format_choice_for_llm(user_choice, spec) -> str` | Task 7 | Task 6, 7 | ✓ |
| `_extract_username_from_umo(umo) -> str` | Task 8 | Task 9, 10 | ✓ |
| `InteractiveChoicePart.request_id` | Task 12 | Task 12, 13, 14, 15 | ✓ |
| `submitChoice(requestId, payload)` | Task 13 | Task 15 | ✓ |
| `addChoice(part)`, `removeChoice(rid)`, `hydrate()`, `reconcile(umo)` | Task 13 | Task 15 | ✓ |

**无类型/命名冲突。**

### 4. Completeness check

- ✅ 每个 task 都有 Files / Interfaces / Steps
- ✅ 步骤粒度 2-5 分钟
- ✅ TDD 风格(写测试 → 跑测试失败 → 实现 → 跑测试通过 → commit)
- ✅ Conventional commit messages
- ✅ Exact file paths
- ✅ Complete code in every step

**Plan ready for execution.**

---

## Execution Choice

Plan complete and saved to `astrbot_plugin_ask_user_choice/docs/superpowers/plans/2026-07-02-blocking-interactive-choice.md`. Two execution options:

1. **Subagent-Driven (recommended)** - 派发独立 subagent per task,中间 review,快速迭代
2. **Inline Execution** - 在当前 session 直接执行,有 checkpoint 供 review

**Which approach?**

# ask_user_choice:服务端驱动的 `cancelled` 状态(v1.2)

> **Amendment to**:
> [`2026-07-02-blocking-interactive-choice-design.md`](./2026-07-02-blocking-interactive-choice-design.md)
>
> 本文件**不重复** v1.0 / v1.1 spec 的内容,只在 v1.0 + v1.1 基础上**新增**
> 一个**第五**状态 `cancelled` 与对应的服务端推送协议。沿用 v1.0 已有的
> `interactive_choice_resolved` SSE 事件类型,**新增**一个 `reason` 取值
> `"cancelled"`,覆盖超时与取消两种场景。
>
> 标记 `[v1.2]` 的段表示本文件新增;`[v1.0 §X.Y]` 表示引用 v1.0 spec 对应章节。
> 未在本文件出现的内容均沿用 v1.0 / v1.1 spec。

---

## 0. Changelog

- **2026-07-19** v1.2.0-amendment(本文档)
  - 新增 box 第五状态 `cancelled`(覆盖超时与用户取消)
  - 后端在 `TimeoutError` / `CancelledError` 两个分支统一推
    `interactive_choice_resolved {reason: "cancelled"}`
  - 前端 Pinia store 新增 `cancelledStates` 桶(与 `submissionStates` /
    `ignoredStates` 平行),`reconcile(umo)` 兜底补写
  - 视觉复用现有 `ignored` 的 muted-header + 折叠详情结构,新增 i18n key
    `interactiveChoice.cancelled`
  - 状态机优先级: `submissionState` > `cancelledState` > `isIgnored` >
    `pending`(竞态安全)

---

## 1. 背景与目标 `[v1.2]`

### 1.1 问题

v1.0 spec 规定的 `await asyncio.wait_for(future, timeout=timeout_s)` 在两个
边界条件下返回的字符串(fallback_msg / 取消提示)会写回 LLM tool result,
但**没有**给前端一个"该 box 不再接受用户输入"的信号,导致:

1. box 一直挂在 `pending` 状态,选项按钮和自由输入框**视觉上仍可点**
2. 用户点击后 REST 端点返回 404(`registry.remove` 已在 `finally` 中清掉)
3. 用户在 dashboard 上看到"点了没反应",产生困惑

需要后端在终结时主动通知前端,让 box 进入一个**非 pending、不可交互**的
视觉状态,文案明确告诉用户"已经结束了"。

### 1.2 目标

- box 在超时 / 取消发生后**自动**翻到"已取消"状态
- 视觉与现有 `ignored`(用户跨过)平行: muted header + 折叠详情,差异仅在
  左侧图标与文案
- 用户**不可**通过点击让 box 退回 pending;若用户在 timeout 边缘抢点,
  视觉以"用户已提交"为准(priority 1)
- SSE 断线 / 用户断网等场景下,`reconcile(umo)` 兜底补写 `cancelledStates`

### 1.3 范围

**In scope**:
- 后端在两个异常分支补推 SSE
- 前端 Pinia store 新桶 + 派生的 dispatcher / `useMessages.processStreamPayload`
  路由
- 前端 `InteractiveChoiceBox` 新状态分支、class、`aria-live`
- 3 个 locale 各加一把 i18n key
- 单测覆盖

**Out of scope**(沿用 v1.0 §1.3):
- 不动工具 parameters schema(超时/取消是 LLM 看不到的运行时分支)
- 不动 LLM 可见的 tool result 字符串(`fallback_msg` / 取消字符串保持不变)
- 不动 REST 端点(无新增 cancel 端点,无新增字段)
- 不实现"用户主动取消"按钮(目前取消源仅限 agent task 取消 / 插件卸载 /
  进程级 `asyncio.CancelledError`,均为非用户操作)

---

## 2. 决策摘要 `[v1.2]`

| 决策 | 选择 | 备选 | 理由 |
|---|---|---|---|
| 状态数量 | 新增 **1 个**状态 `cancelled`,覆盖超时 + 取消 | 新增 `timed_out` + `cancelled` 两个状态 | 用户选择合并;i18n 在 en-US/ru-RU 上一个 key 即可,实现最简 |
| 文案 | `interactiveChoice.cancelled` = "已取消" / "Cancelled" / "Отменено" | "已超时" + "已取消" 双 key | 合并状态下,英文 "Cancelled" 比 "Timed out / Cancelled" 双表达更简洁 |
| 视觉 | 复用 `ignored` 的 muted-header + 折叠详情结构 | 新设计独立模板 | 风格一致性 + 改动最小;`interactiveChoice.ignored` key 早就在 i18n 活状态用着 |
| 图标 | `mdi-close-circle-outline`(空心叉号圈) | `mdi-cancel` / `mdi-clock-alert-outline` | 与 `mdi-eye-off-outline` 风格对仗(都是 outline);语义"已关闭"最贴 |
| 推送时机 | 在 `except` 分支内、`finally` 之前 | 放 `finally` 块 | 让前端**先于** LLM 收到 `fallback_msg` 看到状态翻转,避免"点完才看到关闭"的延迟感 |
| `reason` 取值 | 统一为字符串 `"cancelled"`(超时也用这个) | `"timeout"` / `"cancelled"` 双值 | 用户已合并状态,reason 跟着合并;后端可日志记录实际异常类型供调试 |
| 持久化 | 新桶 `cancelledStates`(`Record<umo, Record<rid, true>>`) | 复用 `ignoredStates` | 用户明确拒绝复用;"已忽略"与"已取消"语义不同,分开存储便于未来分析 |
| 状态机优先级 | `submissionState` > `cancelledState` > `isIgnored` (props) > `pending` | `cancelledState` > `submissionState` | 保护用户在 timeout 边缘的抢点行为——若已本地 markSubmitted,以"已选择"为准 |
| Reconcile 兜底 | 比对 `activeChoices[umo]` 与后端 `list_pending_for_umo`,孤儿 part 自动 markCancelled | 仅靠 SSE 推送 | 处理 SSE 断线 / 用户断网场景;不依赖事件一定能投递 |
| 版本 | v1.1.0 → **v1.2.0** | v1.1.1 | 加 wire 协议扩展 + 新 store 桶,minor bump(SemVer) |

---

## 3. 协议变更 `[v1.2]`

### 3.1 SSE wire format(覆盖 v1.0 §5.x)

`interactive_choice_resolved` 事件**已存在**于 v1.0 success 路径(原 `reason`
仅取 `"submitted"`),v1.2 **新增** 一个 `reason` 取值 `"cancelled"`:

```json
// 超时 / 取消路径(v1.2 新增)
{
  "type": "interactive_choice_resolved",
  "data": { "request_id": "<uuid>", "reason": "cancelled" },
  "message_id": "<sse_message_id>"
}

// 成功路径(v1.0 已定义,本文件不修改)
{
  "type": "interactive_choice_resolved",
  "data": { "request_id": "<uuid>", "reason": "submitted" },
  "message_id": "<sse_message_id>"
}
```

数据字段含义**不变**:`request_id` 唯一标识被终结的 choice,`reason` 描述终结
原因。`message_id` 仍是触发本次 tool 调用的 webchat event 的 message_id,
沿用 v1.0 §X.Y 的 back_queue 路由约定。

### 3.2 后端实现位置

`AskUserChoiceTool.call()` 当前 `try/except/finally` 结构(伪代码,见
`ask_user_choice_tool.py:278-296`):

```python
# v1.0 现状(伪代码)
try:
    user_choice = await asyncio.wait_for(future, timeout=timeout_s)
except asyncio.TimeoutError:
    return fallback_msg                              # ── v1.2 要在此之前推 SSE
except asyncio.CancelledError:
    return f"[User input was cancelled] STOP ALL ACTIONS right now."  # ── 同上
finally:
    registry.remove(request_id)
# ── v1.0 success 分支(参考用,本文件不修改)
try:
    await _push_resolved_event_to_back_queue(
        request_id=request_id, umo=umo,
        reason="submitted", sse_message_id=sse_message_id,
    )
except Exception:
    pass
```

v1.2 在 `except` 两个分支各包一层 try(参考 success 分支的模式),在 `return`
之前先推一次 SSE:

```python
# v1.2 新增
except asyncio.TimeoutError:
    try:
        await _push_resolved_event_to_back_queue(
            request_id=request_id, umo=umo,
            reason="cancelled",                      # ── 新取值
            sse_message_id=sse_message_id,
        )
    except Exception:
        pass                                         # ── 与 success 分支对齐
    return fallback_msg
except asyncio.CancelledError:
    try:
        await _push_resolved_event_to_back_queue(
            request_id=request_id, umo=umo,
            reason="cancelled",
            sse_message_id=sse_message_id,
        )
    except Exception:
        pass                                         # ── 与 success 分支对齐
    return f"[User input was cancelled] STOP ALL ACTIONS right now."
finally:
    registry.remove(request_id)
```

**为什么 finally 之前**:
- 后端 SSE back_queue 是 FIFO,前端在 `interactive_choice_resolved` 事件后
  才会看到状态翻转
- 若推到 `finally` 之后,会插在 `registry.remove` 之后,前端看到状态翻转时
  任何 in-flight REST 已经 404——可接受但不优雅
- 推到 `return` 之前可以让前端"先看到关,再让 LLM 收到 fallback_msg"——与
  success 路径对称(success 也是先推 SSE 再 return)

**为什么 `except: pass`**:
- SSE 推送失败不应影响工具主流程;`fallback_msg` / 取消字符串已经写回 LLM,
  LLM 不感知推送失败
- success 分支(v1.0 §X.Y)同样 `except: pass`,本 spec 与之对齐,不引入新
  日志噪音

### 3.3 工具返回值不变

- `fallback_msg`(默认 `[User did not respond within {timeout} seconds.
  Please proceed with a reasonable default.]`)字符串保持不变
- 取消字符串 `[User input was cancelled] STOP ALL ACTIONS right now.` 保持
  不变
- LLM 不感知"前端是否收到 cancelled 事件",沿用 v1.0 / v1.1 协议

---

## 4. 前端契约 `[v1.2]`

> **职责划分**:本文件**仅**约定数据契约与状态语义。具体 Vue 组件实现 /
> Pinia action 命名 / CSS class 命名由 webchat 组件仓库负责,本 spec
> 给出**最小命名建议**作为对齐参考,前端可按需调整。

### 4.1 Pinia store 新桶 `[v1.2]`

`dashboard/src/stores/interactiveChoice.ts` 新增一个与 `submissionStates` /
`ignoredStates` 平行的桶:

```typescript
export const CANCELLED_STORAGE_KEY = "astrbot-interactive-choice-cancelled";

/** Per-UMO wire shape for server-resolved (timeout/cancel) request ids. */
type PersistedCancelled = Record<string, Record<string, true>>;

interface State {
  // ... 既有字段 ...
  /**
   * Per-UMO set of `request_id`s whose backend registry entry has been
   * removed (timeout or `asyncio.CancelledError`). Written when:
   *  - the SSE `interactive_choice_resolved {reason: "cancelled"}`
   *    event arrives (`applyInteractiveChoiceResolved`)
   *  - `reconcile(umo)` discovers the part is no longer in the backend
   *    pending list (network / SSE miss兜底)
   *
   * The set is monotone-additive per session like `ignoredStates`.
   */
  cancelledStates: PersistedCancelled;
}
```

#### 4.1.1 action 列表(命名建议)

```typescript
markCancelled(umo, requestId): void    // 幂等
isCancelled(umo, requestId): boolean   // 读
hydrateCancelled(umo): void            // 从 localStorage 恢复
persistCancelled(): void               // 写 localStorage
```

接入位置:
- `hydrate(umo)` 调用链末尾追加 `hydrateCancelled(umo)`
- `reconcile(umo)` 在 `list_pending_for_umo` 返回后做 diff,本地有但后端没有
  的 part 调 `markCancelled`

#### 4.1.2 reconcile 兜底逻辑

```typescript
async reconcile(umo: string): Promise<void> {
  // ... 既有拉取逻辑 ...
  if (res.data?.status === "ok" && res.data.data) {
    const backendIds = new Set(
      res.data.data.pending.map((p) => p.request_id),
    );
    const localBucket = this.activeChoices[umo] ?? {};
    for (const rid of Object.keys(localBucket)) {
      if (!backendIds.has(rid)) {
        // 后端已无此 pending 记录 —— 视为 cancelled(覆盖 SSE 漏单)
        this.markCancelled(umo, rid);
      }
    }
    // ... 既有覆盖本地 bucket 逻辑 ...
  }
}
```

### 4.2 SSE 事件路由 `[v1.2]`

`useMessages.processStreamPayload` 在识别 payload 类型时**新增**
`interactive_choice_resolved` 分支:

```typescript
if (payload?.type === "interactive_choice") {
  applyInteractiveChoiceSse(currentSessionId, botRecord, payload);
} else if (payload?.type === "interactive_choice_resolved") {
  applyInteractiveChoiceResolved(currentSessionId, payload);
  // 注意:不修改 botRecord.content.message(resolved 事件不携带 spec,
  // 只携带 request_id + reason)。Box 的 `state` 计算属性从 store 读
  // cancelledStates 自动重渲染。
}
```

新 dispatcher 在 `dashboard/src/composables/dispatchInteractiveChoice.ts`
中导出:

```typescript
export function applyInteractiveChoiceResolved(
  umo: string,
  payload: unknown,
): void {
  if (!umo) throw new Error("applyInteractiveChoiceResolved: missing umo");
  const root = payload as Record<string, unknown> | null;
  if (!root || root.type !== "interactive_choice_resolved") return;
  const data = root.data as Record<string, unknown> | undefined;
  const requestId =
    typeof data?.request_id === "string" ? data.request_id.trim() : "";
  if (!requestId) return;
  useInteractiveChoiceStore().markCancelled(umo, requestId);
}
```

### 4.3 Box 状态机扩展 `[v1.2]`

`dashboard/src/components/chat/message_list_comps/InteractiveChoiceBox.vue`
的 `State` 联合类型与 `state` 计算属性重写:

```typescript
type State =
  | "pending"
  | "submitted_via_option"
  | "submitted_via_input"
  | "ignored"
  | "cancelled";   // ── v1.2 新增

const cancelledState = computed(() =>
  interactiveChoiceStore.isCancelled(props.umo, props.part.request_id),
);

const state = computed<State>(() => {
  // v1.2 优先级重写(原 v1.0 逻辑不变,仅调整判定顺序)
  if (submissionState.value) {
    return submissionState.value.kind === "option"
      ? "submitted_via_option"
      : "submitted_via_input";
  }
  if (cancelledState.value) return "cancelled";
  if (props.isIgnored) return "ignored";
  return "pending";
});
```

**为什么 submissionState 优先于 cancelledState**:见 §5.2 竞态 1 与 §5.3 竞态 2。

### 4.4 Box 模板新增分支 `[v1.2]`

在现有 `v-if="state !== 'ignored'"` 头部块的 `v-else` 之后再追加一个
`v-else-if`,模式与 `ignored` 平行:

```vue
<div v-if="state !== 'ignored' && state !== 'cancelled'" class="choice-header">
  <!-- 既有逻辑: pending / submitted_via_* 头部 -->
</div>
<div v-else-if="state === 'cancelled'" class="choice-header choice-header--cancelled">
  <v-icon size="16" class="choice-header-icon">mdi-close-circle-outline</v-icon>
  <span class="choice-cancelled-label">{{
    tm("interactiveChoice.cancelled")
  }}</span>
  <span
    v-if="part.title"
    class="choice-title choice-title--cancelled"
    :title="part.title"
    >{{ part.title }}</span
  >
  <span
    v-if="part.prompt"
    class="choice-prompt choice-prompt--muted"
    :title="part.prompt"
    >{{ part.prompt }}</span
  >
</div>
```

根 div 的 `class` 绑定增加 `is-cancelled`,`aria-live` 同步置为
`"polite"`(与 `ignored` 一致):

```vue
<div
  class="interactive-choice-box"
  :class="{
    'is-pending': state === 'pending',
    'is-submitted': state === 'submitted_via_option' || state === 'submitted_via_input',
    'is-ignored': state === 'ignored',
    'is-cancelled': state === 'cancelled',  // ── v1.2 新增
    'is-dark': isDark,
  }"
  :aria-live="state === 'ignored' || state === 'cancelled' ? 'polite' : undefined"
>
```

### 4.5 i18n `[v1.2]`

3 个 locale 各加一把 key:

| locale | 文件 | 新增字段 |
|---|---|---|
| zh-CN | `dashboard/src/i18n/locales/zh-CN/features/chat.json` | `"cancelled": "已取消"` |
| en-US | `dashboard/src/i18n/locales/en-US/features/chat.json` | `"cancelled": "Cancelled"` |
| ru-RU | `dashboard/src/i18n/locales/ru-RU/features/chat.json` | `"cancelled": "Отменено"` |

放在现有 `interactiveChoice` 对象内,与其他 key(`alreadyChosen` /
`alreadyInput` / `ignored` / `submit` 等)并列。

### 4.6 CSS 样式新增 `[v1.2]`

复用现有 `.choice-header--ignored` / `.choice-title--ignored` 的样式为模板,
新增:

```css
.choice-header--cancelled {
  /* 与 choice-header--ignored 视觉等价(同一 muted 风格) */
}
.choice-title--cancelled {
  /* 与 choice-title--ignored 视觉等价 */
}
.interactive-choice-box.is-cancelled {
  /* 整体轻微降饱和;与 .is-ignored 风格一致 */
}
```

可考虑直接复用 `.choice-header--ignored` 的 CSS 块(把选择器从 `.is-ignored`
改成 `.is-ignored, .is-cancelled`),减少 CSS 体积——具体由前端 PR 决定。

---

## 5. 错误处理与竞态 `[v1.2]`

### 5.1 SSE 断线 / 用户断网

- 推送丢失 → `interactive_choice_resolved` 未到达
- 兜底: `reconcile(umo)` 在用户切回该会话或下次 hydrate 时拉取后端 pending
  列表,与本地 `activeChoices[umo]` 做 diff(见 §4.1.2)
- 用户感知:box 暂时停在 `pending`,刷新或切回后翻成 `cancelled`——可接受

### 5.2 竞态 1:用户在 T=timeout-1 抢点

```
T=0    plugin call() → registry.add
T=1    SSE 推 interactive_choice → box state = pending
T=299  user click option X
       - store.markSubmitted(umo, rid, "option", {optionId: X})  ← 本地立即生效
       - box state = submitted_via_option (submissionState 优先)
       - POST /api/chat/interactive-choice/{rid} {choice_id: X}
T=300  wait_for 触发 TimeoutError
       - except 分支推 SSE cancelled
       - finally: registry.remove
       - return fallback_msg
T=300  POST 到达后端, registry._pending.get(rid) → None → 返回 404
T=301  SSE cancelled 到达前端
       - applyInteractiveChoiceResolved → store.markCancelled
       - box state 仍 = submitted_via_option (submissionState 优先,不受 cancelled 影响)
```

UI 诚实显示"已选择 X",**但 LLM 实际收到 `fallback_msg`**。这是预先存在的
网络层竞态,v1.2 不引入新风险,只是固化"用户已提交"为视觉最高优先级。

### 5.3 竞态 2:用户提交 POST 在 timeout 后才到

```
T=300  后端: registry.remove 已执行, future 已 cancel
T=301  POST 到达, registry.resolve(rid) → future.done() → 返回 False
       → REST 端点返回 409 "Already resolved or expired"
T=302  SSE cancelled 到达
       - store.markCancelled
       - box state 仍 = submitted_via_option (submissionState 优先)
```

UI 仍显示"已选择 X",前端 `submitChoice` 收到 409 → `console.error` 记录,
**不**回滚 `markSubmitted`(因为用户视觉上已经看到"已选择",回滚更困惑)。
LLM 同样收到 `fallback_msg`。处理同 §5.2。

### 5.4 重复收到 cancelled 事件

- `markCancelled` 设计为幂等(`Record<id, true>` set 形态)
- `applyInteractiveChoiceResolved` 静默跳过 `request_id` 为空的 payload
- `reconcile` diff 出来的孤儿 part 也调 `markCancelled`,幂等无害

### 5.5 后端推送失败

- 后端 `try/except Exception` 吞掉,`logger.debug` 一次
- **不影响** `call()` 主流程,LLM 仍收到 `fallback_msg` 字符串
- 前端无感知:box 保持 `pending` 直到下次 `reconcile` 兜底

---

## 6. 测试策略 `[v1.2]`

### 6.1 后端单测

在 `tests/test_ask_user_choice_tool.py` 新增 4 个用例:

| 用例 | 断言 |
|---|---|
| `test_call_pushes_cancelled_event_on_timeout` | mock `wait_for` 抛 `TimeoutError`,断言 `_push_resolved_event_to_back_queue` 被调一次且 `reason="cancelled"` |
| `test_call_pushes_cancelled_event_on_cancelled_error` | mock `wait_for` 抛 `asyncio.CancelledError`,同上 |
| `test_call_does_not_push_cancelled_on_success` | mock `wait_for` 返回正常 payload,断言 `reason` 不是 `"cancelled"`(沿用 v1.0 `reason="submitted"`) |
| `test_call_swallows_push_failure` | mock `_push_resolved_event_to_back_queue` 抛异常,断言工具仍正常返回 `fallback_msg` / 取消字符串 |

### 6.2 前端 store 单测

`dashboard/src/stores/interactiveChoice.test.ts` 新增 3 个用例:

| 用例 | 断言 |
|---|---|
| `test_mark_cancelled_is_idempotent` | 同一 `(umo, rid)` 调两次 `markCancelled`,结果相同(无重复副作用) |
| `test_hydrate_cancelled_restores_from_local_storage` | 写入 localStorage,新建 store 实例,`hydrate(umo)` 后 `isCancelled(umo, rid)` 返回 true |
| `test_reconcile_marks_missing_parts_as_cancelled` | mock 后端返回空 pending 列表,本地 `activeChoices[umo]` 有 3 个 part,`reconcile` 后 `cancelledStates[umo]` 包含 3 个 rid |

### 6.3 前端 dispatcher 单测

`dashboard/src/composables/dispatchInteractiveChoice.test.ts` 新增 2 个用例:

| 用例 | 断言 |
|---|---|
| `test_apply_resolved_writes_cancelled_state` | 喂合法 payload,断言 `markCancelled(umo, rid)` 被调一次 |
| `test_apply_resolved_silently_drops_invalid_payload` | 喂 `null` / 缺 `data.request_id` / 错 `type`,断言不抛异常且 `markCancelled` 未被调 |

### 6.4 前端 box 渲染测试

`dashboard/src/components/chat/message_list_comps/InteractiveChoiceBox.spec.ts`
新增 2 个用例:

| 用例 | 断言 |
|---|---|
| `test_renders_cancelled_header_when_cancelled_state` | 准备 store 状态,渲染组件,断言模板含 `interactiveChoice.cancelled` 文本与 `mdi-close-circle-outline` 图标 |
| `test_submission_state_takes_priority_over_cancelled` | 同时设置 `submissionState` 与 `cancelledState`,渲染组件,断言显示"已选择"而非"已取消" |

### 6.5 i18n 完整性测试

`dashboard/src/i18n/i18n.completeness.test.ts`(或类似)新增 1 个用例:

| 用例 | 断言 |
|---|---|
| `test_all_locales_define_cancelled_key` | 3 个 locale 文件均含 `features.chat.interactiveChoice.cancelled` |

### 6.6 不需要 E2E

超时的端到端测试需要等 300s,代价过高;手动冒烟一次即可(见 §9)。

---

## 7. 迁移与兼容性 `[v1.2]`

### 7.1 向后兼容

- **后端**:旧调用方不感知新增推送(success 路径完全不变),LLM 不感知
  (`fallback_msg` / 取消字符串不变)
- **前端(旧 dashboard)**:不识别 `interactive_choice_resolved`(已存在
  行为,本 spec 不改),不识别新 `cancelledStates` 桶,box 仍可能停在
  `pending`——**这是 v1.2 必须前后端同步发布的原因**
- **LLM**:工具 description 不变,无 schema 变化

### 7.2 不需要的数据迁移

- `cancelledStates` 是新桶,localStorage 中无旧数据
- 旧 dashboard 上的孤儿 `pending` box 在升级后下次 `reconcile` 自动补写
  `cancelledStates`

### 7.3 Breaking Changes 清单

无——前后端同步发布即可,各自对老客户端 / 老服务端均 graceful degradation。

---

## 8. 文档更新清单 `[v1.2]`

| 文件 | 变更 |
|---|---|
| `metadata.yaml` | `version: v1.1.0` → `v1.2.0`;头部 spec 引用追加本文档 |
| `README.md` | "非目标"小节删除"box 状态转换"(已支持);spec 链接旁注明 v1.2 增量 |
| `AGENTS.md` | 在 §4.2 模块职责里给 `ask_user_choice_tool.py` 补一句"在 TimeoutError / CancelledError 分支推 SSE cancelled" |
| `docs/superpowers/specs/2026-07-02-...md` | **不改**;本文档作为 v1.2 增量引用 |
| `docs/superpowers/specs/2026-07-07-...md` | **不改**;本文档作为 v1.2 增量引用 |
| **webchat 组件仓库** | 由其 owner 在 `Astrbot/docs/superpowers/specs/2026-06-28-dynamic-choice-box-rendering-design.md` 上加一段 v1.2 amendment,引用本文档 |

---

## 9. 实施 PR 拆分 `[v1.2]`

后端 + 前端改动都很小,可拆 2 个 PR,**必须先后发**(后端先合):

1. **PR 1 (本仓库,后端)**:
   - `ask_user_choice_tool.py` 两个 except 分支各加 SSE 推送(约 8 行)
   - `tests/test_ask_user_choice_tool.py` 加 4 个用例
   - `metadata.yaml` 版本 bump
   - **不依赖前端**

2. **PR 2 (webchat 仓库,前端)**:
   - `stores/interactiveChoice.ts` 新桶 + 4 个 action / getter
   - `composables/dispatchInteractiveChoice.ts` 新 dispatcher
   - `composables/useMessages.ts` `processStreamPayload` 路由
   - `components/chat/message_list_comps/InteractiveChoiceBox.vue` 状态机 +
     模板 + CSS
   - 3 个 locale 文件加 key
   - 单测 + spec 引用更新
   - **必须等 PR 1 合并后**才能上线(否则前端收不到 cancelled 事件)

3. **手动冒烟**(PR 2 合并后):
   - 启 AstrBot + 加载新插件 + 加载新 dashboard
   - 跑一个 `ask_user_choice` 工具调用,等 300s 超时
   - 截图确认 box 翻成"已取消"且选项按钮不可点
   - 测一次点"停止生成"→ 取消路径同样翻成"已取消"

---

## 10. 未决项 `[v1.2]`

无。所有决策均已与用户确认;实现细节(具体 Vue 组件 diff、CSS 命名)在
前端 PR 范围内由 dashboard 维护者自由发挥。

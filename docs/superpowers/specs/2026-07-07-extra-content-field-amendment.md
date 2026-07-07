# ask_user_choice 增补:`extra_content` 字段(v1.1)

> **Amendment to**:
> [`2026-07-02-blocking-interactive-choice-design.md`](./2026-07-02-blocking-interactive-choice-design.md)
>
> 本文件**不重复** v1.0 spec 的内容,只在 v1.0 基础上**新增**一个可选字段。
> 标记 `[v1.1]` 的段表示本文件新增;[v1.0 §X.Y]` 表示引用 v1.0 spec 对应章节。
> 未在本文件出现的内容均沿用 v1.0 spec。

---

## 0. Changelog

- **2026-07-07** v1.1.0-amendment(本文档)
  - 新增工具参数 `extra_content`(选填,string,≤5000 字符)
  - 前端按 **markdown** 渲染
  - 透传到 `spec.extra_content` 字段,SSE wire format 不变
  - **不**回传到 LLM 的 tool result(避免 LLM 复读)

---

## 1. 背景与目标 `[v1.1]`

v1.0 spec 在"非目标"小节明确把"推荐项标记 / 优缺点对比 / 风险等级"排除在外。
v1.0 工具允许 LLM 通过 `options[].description` 给每个按钮挂一行说明(≤200 字符),
但**没有**给 LLM 一个"总览区"放:

- 推荐项(LLM 自己的判断)
- 推荐理由 / 推理过程
- 注意事项 / 风险提示
- 每个选项的横向优缺点对比

这些内容塞进 `prompt` 会被 200 字符上限截断;
塞进某个 `options[].description` 又会跟该选项的语义错位;
塞进系统提示词又污染 LLM 自己的上下文。

所以 v1.1 加一个**并列**于 `prompt` / `options` 的**纯展示性**文本字段,只服务于前端渲染。

### 1.1 范围

**In scope**:
- 新增工具参数 `extra_content`
- 后端校验 / 截断 / 透传
- 前端 markdown 渲染(具体组件实现由 webchat 仓库负责,本仓库只约定数据契约)
- 单元测试覆盖

**Out of scope**(沿用 v1.0 §1.3):
- 不做 i18n
- 不做风险等级 / 推荐项高亮(留给将来 v1.2+)
- 不动 `_conf_schema.json`
- 不动 `main.py` / `interactive_choice_registry.py` / REST 端点

---

## 2. 决策摘要 `[v1.1]`

| 决策 | 选择 | 备选 | 理由 |
|---|---|---|---|
| 字段名 | `extra_content` | `analysis` / `context` / `supplement` | 用户选定;与用户措辞"额外内容"字面贴合 |
| 长度上限 | **5000 字符** | 2000 / 无上限 | 用户要求;5000 够 2~4 段中文 + 列表 + 代码块 |
| 必填 | ❌ 选填 | — | 简单问题不需要补充说明,保持向后兼容 |
| 渲染方式 | 前端按 **markdown** 渲染 | 纯文本 / 折叠区 | 用户要求;LLM 习惯写 markdown(列表/代码块/链接) |
| 是否进 tool result | ❌ 不回传 LLM | 回传 | LLM 自己的上下文里就有 `extra_content`,echo 浪费 token 且鼓励 LLM 复读 |
| 截断策略 | 静默截断 + `logger.warning` | 抛错 | 与 `prompt` / `label` / `description` 一致 |
| 透传机制 | 沿用 v1.0 的 `chain_type=interactive_choice` 通道 | 新增 chain_type | JSON 字段透传,SSE 协议本身无需变更 |
| 版本 | v1.0.0 → **v1.1.0** | v1.0.1 | 加性变更,minor bump(SemVer) |

---

## 3. 数据契约 `[v1.1]`

### 3.1 工具 parameters schema(覆盖 v1.0 §4.1)

v1.0 schema 末尾的 `properties` 中**新增**一项,其余字段定义保持不变:

```python
_EXTRA_CONTENT_MAX = 5000  # 字符

parameters: dict = field(default_factory=lambda: {
    "type": "object",
    "properties": {
        "prompt": {...},       # 不变
        "options": {...},      # 不变
        "title": {...},        # 不变
        "input_placeholder": {...},  # 不变

        # ── v1.1 新增 ──
        "extra_content": {
            "type": "string",
            "description": (
                "Optional supplementary text shown to the user next to the options. "
                "Use it for your recommended pick, reasoning, caveats, "
                "or side-by-side pros/cons of the options. "
                "The frontend renders it as Markdown (lists, code blocks, links all work). "
                "The text is NOT echoed back in the tool result — the user already sees it."
            ),
        },
    },
    "required": ["prompt", "options"],   # 不变;extra_content 不进 required
})
```

### 3.2 spec dict 形状(覆盖 v1.0 §4.1)

`_validate_and_build_spec` 末尾追加(伪代码,与 `title` / `input_placeholder` 模式一致):

```python
extra = kwargs.get("extra_content")
if extra and str(extra).strip():
    spec["extra_content"] = str(extra).strip()[:_EXTRA_CONTENT_MAX]
```

产出 spec:

```json
{
  "type": "interactive_choice",
  "prompt": "选一个部署方案?",
  "options": [
    {"id": "A", "label": "蓝绿", "description": "零停机,成本翻倍"},
    {"id": "B", "label": "灰度", "description": "可控,需 LB 支持"},
    {"id": "C", "label": "滚动", "description": "最便宜,有中断窗口"}
  ],
  "title": "部署方案",            // 可选,沿用 v1.0
  "input_placeholder": "可选:输入自定义方案",  // 可选,沿用 v1.0
  "extra_content": "**推荐 B**。\n\n理由:\n- 兼顾成本与风险\n- LB 已就绪\n\n**注意**: 灰度比例建议从 5% 起步"  // v1.1 新增,可选
}
```

### 3.3 截断与边界

| 输入 | 行为 |
|---|---|
| `extra_content` 缺省 / `None` | spec 不含该 key |
| `extra_content: ""` 或纯空白 | spec 不含该 key(等价于未传) |
| `extra_content` 长度 ≤ 5000 | 原样写入 spec(只做 `.strip()`) |
| `extra_content` 长度 > 5000 | 截断到 5000 字符;在**这一次** `call()` 内部 `logger.warning` 一次(下一次截断会再 warning 一次,不全局去重) |
| 非字符串类型(LLM 异常传入) | `str(extra).strip()` 强制转换;若转换后为空则不进 spec |

### 3.4 工具 description 增量(覆盖 v1.0 §4.1)

`AskUserChoiceTool.description` 末尾追加:

```
If you want to show analysis, a recommended pick, reasoning, caveats,
or pros/cons of the options, pass them via `extra_content`.
The frontend renders it as Markdown.
```

> 不使用 ALL CAPS 强语气(与 v1.0 软阻塞时期的话术不同)—— v1.0 是真阻塞,无需 prompt-level 强化。

---

## 4. 前端契约 `[v1.1]`

### 4.1 InteractiveChoicePart 扩展(覆盖 v1.0 §5.1)

`dashboard/src/composables/parseInteractiveChoice.ts` 中的 `InteractiveChoicePart` 接口
**新增**一个可选字段:

```typescript
export interface InteractiveChoicePart {
  type: "interactive_choice";
  request_id: string;
  prompt: string;
  title?: string;
  options: InteractiveChoiceOption[];
  input_placeholder?: string;
  expires_at?: number;

  // ── v1.1 新增 ──
  /**
   * 选填,Markdown 文本。前端 InteractiveChoiceBox 组件在 prompt 与 options
   * 之间**建议**插入一个 prose 区,用 markdown-it / marked 渲染(具体布局
   * 由前端仓库决定)。允许列表、代码块、链接、行内强调;**禁用图片**避免
   * LLM 注入不安全 URL。
   */
  extra_content?: string;

  [key: string]: unknown;
}
```

> `[key: string]: unknown` 已存在(v1.0 §5.1),所以**纯类型层**的扩展是后端加字段无需
> 前端同步 PR 也能跑——`validateInteractiveChoice` 不会因为有 `extra_content` 而失败,
> 已有的旧前端只是不渲染新字段(graceful degradation)。但要真正"显示 markdown"
> 必须前端同步发版。

### 4.2 truncateInteractiveChoice 同步 `[v1.1]`

新增一行,避免恶意/异常 LLM 输入撑爆前端:

```typescript
const LIMITS = {
  PROMPT_MAX: 200,
  TITLE_MAX: 30,
  LABEL_MAX: 30,
  DESC_MAX: 200,
  PLACEHOLDER_MAX: 60,
  EXTRA_CONTENT_MAX: 5000,  // v1.1 新增
};

if (typeof out.extra_content === "string" && out.extra_content.length > LIMITS.EXTRA_CONTENT_MAX) {
  out.extra_content = out.extra_content.slice(0, LIMITS.EXTRA_CONTENT_MAX);
  mutated = true;
}
```

### 4.3 渲染责任

- 本仓库**不包含**前端代码;实际 markdown 渲染逻辑由 webchat 组件仓库的
  `InteractiveChoiceBox.vue` 实现。
- 本 spec **只**约定数据契约,具体 markdown 库选择 / sanitize 策略 / 折叠行为
  是前端 PR 的责任,见其仓库。

---

## 5. LLM 可见性 `[v1.1]`

`_format_choice_for_llm` 输出**不变**(沿用 v1.0 §4.1),不包含 `extra_content`:

```text
User selected: <label> (id=<id>)
[Additional note: <free_text>]   # 仅在 free_text 非空时存在
```

理由:LLM 自己刚写出的 `extra_content` 就在它上下文里,再 echo 一遍既浪费 token,
又会诱导 LLM 在下一轮回复里**复读**"我推荐 B 因为..."(已经写在选项框里了)。

---

## 6. 测试策略 `[v1.1]`

在 `tests/test_ask_user_choice_tool.py` 新增 5 个用例 + 更新 1 个旧用例:

| 用例 | 断言 |
|---|---|
| `test_validate_includes_extra_content_when_provided` | spec 含 `extra_content` 字段且内容等于输入(经 strip) |
| `test_validate_omits_extra_content_when_empty_or_none` | `None` / `""` / 纯空白 / 缺省 → spec **不**含该 key |
| `test_validate_truncates_long_extra_content` | 长度 > `_EXTRA_CONTENT_MAX` → 截断到上限 |
| `test_validate_extra_content_strips_whitespace` | 首尾空白被 `.strip()` |
| `test_call_propagates_extra_content_to_sse_payload` | SSE 推出去的 `data` JSON 解出后 `spec.extra_content` 字段完整 |
| **更新** `test_validate_returns_dict_on_valid_input` | 在现有断言基础上额外确认 spec 不含 `extra_content` 字段(默认行为不变) |

---

## 7. 迁移与兼容性 `[v1.1]`

### 7.1 向后兼容

- **前端**:旧 webchat 组件收到含 `extra_content` 的 spec,因 `[key: string]: unknown` 已
  存在,类型不报错;`validateInteractiveChoice` 不会拒绝新字段;不渲染就行(graceful
  degradation)。**零 breaking change**。
- **后端**:旧调用方不传 `extra_content` → spec 不含该 key → 行为与 v1.0 完全一致。
- **LLM**:工具 description 是加性,LLM 训练语料里没见过的字段会按 schema 描述理解,
  不会出现"为什么 schema 多了字段"的问题。

### 7.2 不需要的数据迁移

无 — schema 是加性,无字段被删/被改语义。

### 7.3 Breaking Changes 清单

无。

---

## 8. 文档更新清单 `[v1.1]`

| 文件 | 变更 |
|---|---|
| `metadata.yaml` | `version: v1.0.0` → `v1.1.0`;desc 末尾追加"支持 `extra_content` Markdown 补充说明字段";头部 spec 引用追加本文档 |
| `README.md` | "用法"小节加一个 `extra_content` 调用示例;spec 链接旁注明 v1.1 增量;"非目标"小节删除"推荐项标记"一项(已支持) |
| `docs/superpowers/specs/2026-07-02-...md` | **不改**;本文档作为 v1.1 增量引用 |
| `AGENTS.md` | 在 §4.2 模块职责里给 `ask_user_choice_tool.py` 补一句"`extra_content` 字段透传到 spec" |

---

## 9. 实施 PR 拆分 `[v1.1]`

后端 schema + 单测可一个 PR 完成(代码量 < 50 行):

1. **PR 1 (本仓库)**:后端字段 + 校验 + 单测 + metadata + README
2. **PR 2 (webchat 仓库,本仓库 owner 同步开)**:前端 `InteractiveChoicePart` 类型 + `InteractiveChoiceBox` markdown 渲染区

PR 2 与本仓库 PR 1 **可独立发布**:
- 先发 PR 1 → LLM 已能传 `extra_content`,后端已透传;旧前端不渲染但不崩。
- 后发 PR 2 → 前端补上 markdown 渲染,体验闭环。
- 顺序不限,但建议 PR 1 先合(后端测试覆盖更稳)。

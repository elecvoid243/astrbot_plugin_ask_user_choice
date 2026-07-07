# astrbot_plugin_ask_user

> 让 LLM 在需要人类审批/拍板时,通过 `ask_user_choice` 工具向用户呈现一个**可交互的选项框**。
> **v1.0 起为真阻塞式**:工具在 `call()` 内 `await` 等待 dashboard 用户响应,用户点击选项(或输入自定义文本)后,选择结果**直接作为工具返回值**回传给 LLM(不再是新的 user message)。

- **版本**: v1.1.0
- **作者**: elecvoid243
- **兼容**: AstrBot `>=4.16,<5`
- **当前 spec**: [`docs/superpowers/specs/2026-07-02-blocking-interactive-choice-design.md`](docs/superpowers/specs/2026-07-02-blocking-interactive-choice-design.md)
- **v1.1 增量 spec**: [`docs/superpowers/specs/2026-07-07-extra-content-field-amendment.md`](docs/superpowers/specs/2026-07-07-extra-content-field-amendment.md)
- **历史 spec(已废弃)**: `2026-06-28-dynamic-choice-box-rendering-design.md`(v0.3 软阻塞设计,仅作历史记录)

## v1.0 真阻塞式 (2026-07-02+)

`ask_user_choice` 工具在 v1.0 起改为真阻塞式:LLM 调用后,工具内部 `await`
等待 dashboard 用户响应,完成后直接返回用户选择给 LLM(不是新 user message)。
等待状态跨 dashboard 刷新持久化,超时后返回可配置的 fallback 文本。

### 用法

LLM 自动调用,无需用户额外操作。配置项见 `_conf_schema.json`
(`enabled` / `timeout_seconds` / `timeout_fallback_message` / `max_concurrent_pending`)。

---

## 功能

LLM 经常需要在"是否执行危险操作"这种决策点上寻求人类授权(例如删除文件、运行脚本、批量重命名)。
在引入本插件之前,LLM 只能输出自然语言问题,用户必须手动翻译成"是/否/改成 X",既不直观也容易错别字误判。

`ask_user_choice` 工具让 LLM 输出一个**结构化**的"选项框"中间格式,WebChat 前端拿到后动态渲染为按钮列表 + 自由输入框。
用户点击选项 / 输入文本后,**以普通 user message 形式**回传给 LLM,LLM 从对话上下文推断这是对工具调用的回应,无需任何隐藏标记。

### 适用场景

1. **敏感/不可逆操作授权** — 删除文件、清空数据库、推送至生产环境等。
2. **多候选方案拍板** — 让用户在 2~10 个候选中选一个(可附 description 解释每个选项)。
3. **关键参数确认** — 让用户从多个预设值中选,或临时输入自定义值。

### 非目标(v1 范围外)

- 多选 / 嵌套 / 风险等级 / 超时倒计时 / 非 WebChat 平台适配 — 见 spec §1。
- "推荐项标记" 已通过 v1.1 的 `extra_content` 字段支持(LLM 在 `extra_content` 里写推荐理由,前端按 Markdown 渲染)。

---

## 行为保证

> ⚠️ **本节描述 v0.3 软阻塞行为,自 v1.0 起已被真阻塞式替代,仅作历史记录。**
> v1.0 工具在 `call()` 内 `await` 用户响应并直接返回结果,不再依赖下述 prompt-level 软约束。

`ask_user_choice` 工具**不真阻塞 LLM 执行**:`call()` 立即返回 JSON,工具结果交给 LLM 后,LLM 是否停下完全靠 LLM "自觉"。

v0.3.0 用两道 prompt-level 强化提高自觉率:

| 强化层 | 实现 | 命中率 |
|---|---|---|
| **P1 硬话术 tool description** | `description` 字段含 `HARD RULES` / `MUST NOT` / `turn is OVER` 等强语气短语 | LLM 调工具时看 description |
| **P2 system_prompt 注入** | `@filter.on_llm_request()` 钩子在每次请求前向 `system_prompt` 末尾追加 `# ask_user_choice tool policy` 段,marker 防重复 | 每次 LLM 请求都生效 |

**已知失效场景**(软阻塞救不回来):

- 弱指令跟随的 LLM 调完 `ask_user_choice` 之后又输出 "我先帮你做 X"
- LLM 在同一条 assistant 消息里连调多次 `ask_user_choice`
- LLM 在 tool result 之后立刻调别的工具(如 `astrbot_execute_shell`)而不管选项框

要根治这些,必须走"真阻塞"方案(在 `call()` 内 `await` 用户响应,需新增前端 submit 回传协议 + `asyncio.Future` 跨协程解锁,工程量大且牵涉 AstrBot 框架),见 AGENTS.md §4.3.1。

> 实践中,Claude / GPT-4o / DeepSeek 等主流 LLM 在上述 prompt 强化下都能严格遵守,失效主要发生在本地小模型或未对齐的 checkpoint 上。

---

## 安装

将本目录复制或软链接到 AstrBot 的 `data/plugins/` 目录下,重启 AstrBot(或在 WebUI 触发"重载插件")。

```text
Astrbot/
└── data/
    └── plugins/
        └── astrbot_plugin_ask_user/   ← 本仓库
            ├── main.py
            ├── metadata.yaml
            ├── ask_user_choice_tool.py
            ├── README.md
            ├── requirements.txt
            ├── _conf_schema.json
            └── .gitignore
```

### 验证安装

启动 AstrBot 后查看日志,应出现类似:

```text
plugin(module_path astrbot_plugin_ask_user) added LLM tool: ask_user_choice
```

或在 WebUI 的"插件管理"页面看到 `astrbot_plugin_ask_user` 已启用。

---

## 使用

插件加载后,LLM 可在工具列表中看到 `ask_user_choice`,并按需调用。典型调用示例:

```json
{
  "prompt": "请选择下一步要使用的模型:",
  "title": "模型选择",
  "options": [
    { "id": "a", "label": "GPT-4",        "description": "更强但更慢",  "value": "gpt-4"        },
    { "id": "b", "label": "GPT-4 mini",                                       "value": "gpt-4-mini"   },
    { "id": "c", "label": "本地模型",                                         "value": "local"        }
  ],
  "input_placeholder": "或输入自定义模型名",
  "extra_content": "**推荐 b**\n\n理由:质量足够,成本比 GPT-4 低一个数量级。本地模型在中文长文本上略弱。"
}
```

工具的 **JSON Schema**(`parameters` 字段)严格遵循 spec §3.2:

| 字段 | 必填 | 长度上限 | 说明 |
| ---- | :--: | :--: | ---- |
| `prompt` | ✓ | 200 字 | 提问文案,显示在选项框顶部 |
| `options` | ✓ | 2~10 个 | 候选选项,单选 |
| `options[].id` | ✓ | — | 唯一 ID,仅供前端 `:key`,不会发给 LLM |
| `options[].label` | ✓ | 30 字 | 按钮上显示的文字(面向用户) |
| `options[].description` | ✗ | 200 字 | 选项补充说明(面向用户) |
| `options[].value` | ✓ | 不限 | 选中后回传给 LLM 的文本(面向 LLM) |
| `title` | ✗ | 30 字 | 选项框标题,例如 "模型选择" |
| `input_placeholder` | ✗ | 60 字 | 自由输入框的占位符 |
| `extra_content` | ✗ | 5000 字 | **v1.1 新增** 补充说明(Markdown 文本),用于承载 LLM 给用户看的推荐/理由/注意事项/优缺点对比,前端按 Markdown 渲染。**不**回传到 LLM tool result |

### 软错误处理(spec §11.2 #2)

参数不合法时工具**不抛异常**,而是返回 `"错误:..."` 纯文本,让 LLM 自助重试:

| 触发条件 | 返回示例 |
| -------- | -------- |
| `prompt` 为空 | `错误:prompt 必填且不能为空。` |
| `options` 不是 list 或长度越界 | `错误:options 必须是包含 2-10 个元素的数组。` |
| 某项缺 `id` / `label` / `value` | `错误:options[2] 缺 id/label/value。` |
| 存在重复 `id` | `错误:options 中存在重复的 id: 'a'。` |

### 工具层 vs 前端层的双重截断(spec §3.2 footnote)

工具层(本插件)对 `description` / `input_placeholder` / `label` / `title` / `prompt` 做**第一重**截断,主要用于节省 token。
前端(`normalizePartsInternal`)做**第二重**截断,作为防御性兜底以应对非本工具来源的 part。两层不冲突,工具层先截,前端后截不会恢复原文。

---

## 数据流(参考 spec §6)

```text
LLM (agent runner)
  ↓ 调 ask_user_choice 工具
Tool Result: JSON 字符串,形如 {"type":"interactive_choice", ...}
  ↓ framework 默认 Plain 包装成 MessagePart
MessagePart: { type: "plain", text: '{"type":"interactive_choice", ...}' }
  ↓ 通过 webchat 通道到达 useMessages.normalizePartsInternal
  ↓ 步骤 1 解包: text 以 "{" 开头 → JSON.parse → 替换 part
  ↓ 步骤 2 校验: 按 §3.2 规则 → 透传(合法) / 降级为 unknown-part(非法)
WebChat Frontend
  ↓ ChatMessageList 路由到 <InteractiveChoiceBox>
选项框渲染
  ↓ 用户点按钮 / 提交 textarea
emit('submit', option.value | inputText)
  ↓ ChatMessageList.onInteractiveChoiceSubmit
sendMessage({ text })
  ↓ useMessages.send() → POST /api/chat
Backend LLM
  ↓ 收到普通 user message,从上下文推断这是对上一步提问的回应
下一轮回复
```

---

## 前端要求

AstrBot WebChat 前端需 >= spec 日期的 dashboard 版本(支持 `interactive_choice` part 渲染)。

- 中间格式定义: spec §3.1
- 前端组件契约: spec §4
- 4 状态机(`pending` / `submitted_via_option` / `submitted_via_input` / `ignored`): spec §4.4

未升级前端时,工具仍能正常工作,只是工具返回的 JSON 字符串会作为普通 plain text 显示在聊天中(降级体验)。

---

## 配置

插件支持以下配置项(在 AstrBot WebUI 的"插件配置"页面编辑,或直接修改 `data/plugin_data/astrbot_plugin_ask_user/config.json`):

| 字段 | 类型 | 默认 | 说明 |
| ---- | :--: | :--: | ---- |
| `enabled` | `bool` | `true` | 是否启用 `ask_user_choice` 工具。设为 `false` 后 AstrBot 启动时跳过工具注册。**修改后需重启生效**。 |
| `timeout_seconds` | `int` | `300` | 等待用户响应的超时秒数(30-3600),默认 5 分钟。超时后工具返回 `timeout_fallback_message`。 |
| `timeout_fallback_message` | `string` | 见 schema | 超时后返回给 LLM 的文本,`{timeout}` 会被替换为实际秒数。 |
| `max_concurrent_pending` | `int` | `32` | 单 AstrBot 实例最大并发等待数(>=1),超过时工具返回错误。 |

### 关闭后会发生什么

- LLM 的工具列表中**不出现** `ask_user_choice` —— LLM 不知道这个工具存在
- 不会污染 LLM 系统提示(节省 token)
- 用户在前端看到的所有选项框都会消失
- 日志中会出现一行: `ask_user_choice 工具已禁用(配置 enabled=false),跳过注册`

### 关闭时调用会怎样

LLM 不可能再调到这个工具(因为它不在工具列表里)。如果某段对话上下文里残留了旧的工具调用,AstrBot 会以普通"工具不存在"的方式处理(行为由 AstrBot 框架定义,与本插件无关)。

---

## 测试

### 单元测试(spec §8)

`AskUserChoiceTool.call` 行为可使用 `pytest` 直接测试:

```python
import asyncio
from astrbot_plugin_ask_user.ask_user_choice_tool import AskUserChoiceTool

async def test_happy_path():
    tool = AskUserChoiceTool()
    result = await tool.call(
        context=None,
        prompt="请选择",
        options=[
            {"id": "a", "label": "A", "value": "1"},
            {"id": "b", "label": "B", "value": "2"},
        ],
    )
    assert result.startswith('{"type": "interactive_choice"')

async def test_missing_prompt():
    tool = AskUserChoiceTool()
    result = await tool.call(context=None, prompt="", options=[])
    assert "错误" in result
```

更完整的端到端测试需要真实 AstrBot + LLM 环境,见 spec §11.3。

---

## 规范出处

| 工具约束 | spec 章节 |
| -------- | --------- |
| `prompt` 必填,200 字截断 | §3.2 字段约束 |
| `options` 2-10 个,每项必填 `id` / `label` / `value` | §3.2 字段约束 |
| `id` 重复时拒绝 | §3.2 + §7 错误处理 |
| `title` 可选,30 字截断 | §3.2 字段约束 |
| `input_placeholder` 可选,60 字截断 | §3.2 字段约束 |
| 返回 JSON 字符串,framework 走 Plain 包装 | §2.3 + §6 数据流 |
| 前端 `normalizePartsInternal` 展平 | §2.3 翻译位置 |
| 软错误而非抛异常 | §11.2 #2 |
| `title` 空时不输出该字段 | §11.2 #5 |

---

## License

MIT

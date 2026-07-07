# ask_user_choice `extra_content` 字段 v1.1 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `ask_user_choice` 工具新增可选 `extra_content` 字符串字段(≤5000 字符),用于承载 LLM 给用户看的推荐/理由/注意事项/优缺点对比等补充文本,前端按 Markdown 渲染。

**Architecture:** 加性变更。后端在 `_validate_and_build_spec` 末尾按 `title` / `input_placeholder` 的同款模式增加一个可选字段写入 spec;SSE wire format 不变(JSON 字段透传);工具 description 加一句引导 LLM 知道这个能力。**不**回传到 LLM tool result。

**Tech Stack:** Python 3.10+ dataclass + AstrBot `FunctionTool` + pytest(已有)+ ruff(项目规定)。

## Global Constraints

来自 [`2026-07-07-extra-content-field-amendment.md`](../specs/2026-07-07-extra-content-field-amendment.md) 和项目 AGENTS.md,所有 task 都隐含遵守:

- Python ≥ 3.10,UTF-8 中文注释允许,**标识符必须英文**。
- 字符串统一双引号 `"`;缩进 4 空格;行长软限 100 / 硬限 120;多行容器保留尾随逗号。
- 类型标注:`T | None` 而非 `Optional[T]`;`@register` 工具回调签名严格按 AstrBot 装饰器要求。
- 错误处理:可恢复错误 → 返回 `str` 让 LLM 自助重试,不要 `raise`;`logger.warning` 替代 `print`。
- 工具 description 是 LLM 可见契约,加性变更**不**删字段;新加的措辞允许重写(只加不删)。
- SPEC v1.0 的所有约束(平台守卫 `webchat:` 前缀、`sse_message_id` 必须非空、并发上限 32、惰性 mount 守卫、SSE `chain_type=interactive_choice` wire format)全部沿用,**不动**。
- Spec 路径:`docs/superpowers/specs/2026-07-07-extra-content-field-amendment.md`。
- 版本:v1.0.0 → v1.1.0(加性变更,minor bump)。

---

## File Structure

| 路径 | 状态 | 职责 |
|---|---|---|
| `ask_user_choice_tool.py` | 修改 | 加 `_EXTRA_CONTENT_MAX` 常量;`parameters.properties.extra_content`;`_validate_and_build_spec` 末尾写入 spec;`description` 加一句 |
| `tests/test_ask_user_choice_tool.py` | 修改 | 新增 5 个 `extra_content` 单测;更新 1 个旧用例;新增 1 个 SSE wire-format 透传回归测试 |
| `metadata.yaml` | 修改 | `version: v1.0.0` → `v1.1.0`;头部 spec 引用追加本文档;changelog 段加 v1.1 条目;desc 末尾追加 `extra_content` 说明 |
| `README.md` | 修改 | "用法"小节加 `extra_content` 调用示例;spec 链接旁注 v1.1 增量;"非目标"小节删除"推荐项标记"项(已支持) |
| `AGENTS.md` | 修改 | §4.2 模块职责里给 `ask_user_choice_tool.py` 加一句"含 `extra_content` 字段透传到 spec" |

**不动的文件**:`main.py` / `interactive_choice_registry.py` / `api_mount.py` / `_conf_schema.json` / v1.0 spec 文档 / `requirements.txt`(按 spec §1.1 / §7)。

---

## Task 1: 实现 `extra_content` 字段 + 单测(TDD)

**Files:**
- Modify: `ask_user_choice_tool.py`(3 处:`_EXTRA_CONTENT_MAX` 常量 / `parameters` schema / `_validate_and_build_spec` / `description`)
- Modify: `tests/test_ask_user_choice_tool.py`(新增 5 个用例 + 更新 1 个旧用例)

**Interfaces(给 Task 2 用):**
- `AskUserChoiceTool._validate_and_build_spec(kwargs) -> dict | str` — 现在返回值多一个可选 key `extra_content`(str,≤5000 字符)。
- `AskUserChoiceTool.parameters["properties"]` — 现在多一个 `extra_content` JSON Schema property。

- [ ] **Step 1: 写 5 个新单测 + 更新 1 个旧单测**

打开 `tests/test_ask_user_choice_tool.py`,在文件末尾的"缺失 sse_message_id 校验"区块之后追加 5 个新 test 函数。同时**修改** `test_validate_returns_dict_on_valid_input` 在末尾加一行断言(确认默认行为下 spec 不含 `extra_content`)。

```python
# ── v1.1 extra_content 单测 ────────────────────────────────────────


def test_validate_includes_extra_content_when_provided():
    """提供非空 extra_content 时,spec 应包含原样内容(经 strip)。"""
    tool = AskUserChoiceTool()
    result = tool._validate_and_build_spec(
        {
            "prompt": "test",
            "options": [{"id": "A", "label": "a"}, {"id": "B", "label": "b"}],
            "extra_content": "**推荐 B**\n\n理由:便宜",
        }
    )
    assert isinstance(result, dict)
    assert result["extra_content"] == "**推荐 B**\n\n理由:便宜"


def test_validate_omits_extra_content_when_empty_or_none():
    """空 / None / 纯空白 / 缺省 → spec 不含该 key。"""
    tool = AskUserChoiceTool()
    base = {
        "prompt": "test",
        "options": [{"id": "A", "label": "a"}, {"id": "B", "label": "b"}],
    }
    for missing in [None, "", "   ", "\n\t  "]:
        result = tool._validate_and_build_spec({**base, "extra_content": missing})
        assert isinstance(result, dict), f"extra_content={missing!r} should be valid"
        assert "extra_content" not in result, (
            f"extra_content={missing!r} should be omitted, got {result!r}"
        )

    # 完全不传该参数
    result = tool._validate_and_build_spec(base)
    assert "extra_content" not in result


def test_validate_truncates_long_extra_content():
    """长度 > _EXTRA_CONTENT_MAX → 截断到上限。"""
    from astrbot_plugin_ask_user_choice.ask_user_choice_tool import _EXTRA_CONTENT_MAX

    tool = AskUserChoiceTool()
    long_text = "x" * (_EXTRA_CONTENT_MAX + 100)
    result = tool._validate_and_build_spec(
        {
            "prompt": "test",
            "options": [{"id": "A", "label": "a"}, {"id": "B", "label": "b"}],
            "extra_content": long_text,
        }
    )
    assert isinstance(result, dict)
    assert len(result["extra_content"]) == _EXTRA_CONTENT_MAX


def test_validate_extra_content_strips_whitespace():
    """首尾空白被 .strip() 去除。"""
    tool = AskUserChoiceTool()
    result = tool._validate_and_build_spec(
        {
            "prompt": "test",
            "options": [{"id": "A", "label": "a"}, {"id": "B", "label": "b"}],
            "extra_content": "  hello world  \n",
        }
    )
    assert isinstance(result, dict)
    assert result["extra_content"] == "hello world"


def test_validate_non_string_extra_content_is_coerced_to_string():
    """异常非字符串输入 → str() 强转,空则不进 spec。"""
    tool = AskUserChoiceTool()
    # 数字 → 字符串
    result = tool._validate_and_build_spec(
        {
            "prompt": "test",
            "options": [{"id": "A", "label": "a"}, {"id": "B", "label": "b"}],
            "extra_content": 42,
        }
    )
    assert isinstance(result, dict)
    assert result["extra_content"] == "42"

    # 0/False/空 list → 强转后空,不该进 spec
    for falsy in [0, False, []]:
        result = tool._validate_and_build_spec(
            {
                "prompt": "test",
                "options": [{"id": "A", "label": "a"}, {"id": "B", "label": "b"}],
                "extra_content": falsy,
            }
        )
        assert isinstance(result, dict)
        assert "extra_content" not in result, f"falsy {falsy!r} should be omitted"
```

**同时修改** `test_validate_returns_dict_on_valid_input`,在末尾追加一行:

```python
def test_validate_returns_dict_on_valid_input():
    tool = AskUserChoiceTool()
    result = tool._validate_and_build_spec(
        {
            "prompt": "test",
            "options": [
                {"id": "A", "label": "alpha"},
                {"id": "B", "label": "beta"},
            ],
        }
    )
    assert isinstance(result, dict)
    assert result["prompt"] == "test"
    assert result["type"] == "interactive_choice"
    assert len(result["options"]) == 2
    # v1.1: 未传 extra_content → 不进 spec(向后兼容)
    assert "extra_content" not in result
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd F:\github\astrbot_plugin_ask_user_choice
python -m pytest tests/test_ask_user_choice_tool.py -k "extra_content" -v
```

**Expected**:`_validate_and_build_spec` 还没认 `extra_content` → 5 个新 test **全部 FAIL**;`test_validate_returns_dict_on_valid_input` 末尾新增的 `assert "extra_content" not in result` 也会 FAIL(因为还没实现,默认行为不变所以是 PASS,但导入新文件可能有别的问题——主要看 5 个新 test 的状态)。

- [ ] **Step 3: 在 `ask_user_choice_tool.py` 加 `_EXTRA_CONTENT_MAX` 常量**

把现有的常量块从:

```python
_PROMPT_MAX = 200
_TITLE_MAX = 30
_LABEL_MAX = 30
_DESCRIPTION_MAX = 200
_INPUT_PLACEHOLDER_MAX = 60
_OPTIONS_MIN = 2
_OPTIONS_MAX = 10
```

改成:

```python
_PROMPT_MAX = 200
_TITLE_MAX = 30
_LABEL_MAX = 30
_DESCRIPTION_MAX = 200
_INPUT_PLACEHOLDER_MAX = 60
_EXTRA_CONTENT_MAX = 5000   # v1.1: 补充说明(Markdown)字符上限
_OPTIONS_MIN = 2
_OPTIONS_MAX = 10
```

- [ ] **Step 4: 在 `parameters` schema 末尾追加 `extra_content` property**

在 `parameters` 字典的 `"properties"` 块中,定位到 `"input_placeholder"` 那行后、`properties` 闭合的 `},` 之前,插入:

```python
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
```

- [ ] **Step 5: 在 `_validate_and_build_spec` 末尾追加 `extra_content` 写入逻辑**

定位方法最后 `return spec` 之前的空白行,改成:

```python
        placeholder = kwargs.get("input_placeholder")
        if placeholder and placeholder.strip():
            spec["input_placeholder"] = placeholder.strip()[:_INPUT_PLACEHOLDER_MAX]

        # v1.1: 补充说明字段(Markdown 文本,前端渲染)
        extra = kwargs.get("extra_content")
        if extra is not None:
            extra_str = str(extra).strip()
            if extra_str:
                if len(extra_str) > _EXTRA_CONTENT_MAX:
                    logger.warning(
                        f"ask_user_choice: extra_content 截断 "
                        f"({len(extra_str)} -> {_EXTRA_CONTENT_MAX} 字符)"
                    )
                    extra_str = extra_str[:_EXTRA_CONTENT_MAX]
                spec["extra_content"] = extra_str
        return spec
```

> 验证下 `logger` 已经在文件顶部 import 了(检查 `from astrbot.api import logger, ...`);如果没有,加进 import 列表。

- [ ] **Step 6: 在 `AskUserChoiceTool.description` 末尾追加一句**

定位现有 description 字符串的最后一行,改末尾为:

```python
    description: str = (
        "Present the user with a question and a set of options to choose from. "
        "Use this when you need the user to make a decision before you can proceed. "
        "This tool blocks until the user responds, then returns their choice. "
        "The user's response is returned directly as this tool's result. "
        "If you want to show analysis, a recommended pick, reasoning, caveats, "
        "or pros/cons of the options, pass them via `extra_content`. "
        "The frontend renders it as Markdown."
    )
```

- [ ] **Step 7: 跑测试确认全部通过**

```bash
cd F:\github\astrbot_plugin_ask_user_choice
python -m pytest tests/test_ask_user_choice_tool.py -v
```

**Expected**:**全部 PASS**(包括 v1.0 已有用例 + 5 个新 `extra_content` 用例 + 更新后的 `test_validate_returns_dict_on_valid_input`)。

- [ ] **Step 8: 跑 ruff + py_compile**

```bash
cd F:\github\astrbot_plugin_ask_user_choice
python -m py_compile ask_user_choice_tool.py
python -m ruff check ask_user_choice_tool.py
```

**Expected**:零错误,零警告。如果有 ruff 提示 import 排序之类的,按项目 §3.2 顺序调整。

- [ ] **Step 9: 提交**

```bash
cd F:\github\astrbot_plugin_ask_user_choice
git add ask_user_choice_tool.py tests/test_ask_user_choice_tool.py
git commit -m "feat(tool): add optional extra_content field (v1.1)"
```

---

## Task 2: SSE wire-format 透传回归测试

**Files:**
- Modify: `tests/test_ask_user_choice_tool.py`(在 v1.1 区块末尾追加 1 个新 test)

**为什么单独成 task**:Task 1 验证的是 `_validate_and_build_spec` 的纯函数行为;这个 test 验证的是"spec 进了 spec dict 之后,SSE 透传路径也能完整带过去",数据流层的回归保险。

**Interfaces(给 Task 3 用):** 本 task 不输出新接口,只是把 v1.1 字段在 SSE payload 中的存活能力锁住。

- [ ] **Step 1: 写测试**

在 Task 1 新增的"v1.1 extra_content 单测"区块末尾再追加 1 个 test:

```python
# ── v1.1 extra_content SSE 透传回归 ────────────────────────────────


@pytest.mark.asyncio
async def test_call_propagates_extra_content_to_sse_payload(monkeypatch):
    """extra_content 应在 SSE data 字段的 JSON 序列化中完整保留,
    前端解析 spec 时能拿到原值(仅 .strip() + 截断,不做其他转义)。"""
    import json

    tool = AskUserChoiceTool()
    ctx = _make_context()

    captured_data: dict = {}

    class _FakeBackQueue:
        def __init__(self):
            self.items: list = []

        async def put(self, item):
            # 只关心 interactive_choice 事件
            if item.get("chain_type") == "interactive_choice":
                captured_data["data"] = item["data"]

    class _FakeMgr:
        get_or_create_back_queue = staticmethod(
            lambda **kwargs: _FakeBackQueue()
        )

    monkeypatch.setattr(
        "astrbot_plugin_ask_user_choice.ask_user_choice_tool.webchat_queue_mgr",
        _FakeMgr(),
        raising=False,
    )
    monkeypatch.setattr(
        tool,
        "_load_tool_config",
        lambda ctx: {"timeout_seconds": 2, "max_concurrent_pending": 32},
    )

    extra_md = "**推荐 B**\n\n理由:\n- 便宜\n- 快"

    async def cancel_after_push():
        await asyncio.sleep(0.05)
        rid = next(iter(registry._pending.keys()), None)
        if rid:
            registry.resolve(rid, {"choice_id": "A", "free_text": ""})

    call_task = asyncio.create_task(
        tool.call(
            ctx,
            prompt="Pick one",
            options=[{"id": "A", "label": "alpha"}, {"id": "B", "label": "beta"}],
            extra_content=extra_md,
        )
    )
    cancel_coro = asyncio.create_task(cancel_after_push())
    await asyncio.wait_for(call_task, timeout=3.0)
    await cancel_coro

    assert "data" in captured_data, "SSE interactive_choice 事件没被推送"
    parsed = json.loads(captured_data["data"])
    assert parsed["spec"]["extra_content"] == extra_md
```

- [ ] **Step 2: 跑测试**

```bash
cd F:\github\astrbot_plugin_ask_user_choice
python -m pytest tests/test_ask_user_choice_tool.py::test_call_propagates_extra_content_to_sse_payload -v
```

**Expected**:PASS(Task 1 完成后这条用例直接通过,因为代码已经支持)。

> 退化场景:如果这个 test FAIL,大概率是 spec dict 构造顺序 / JSON 序列化路径上有问题,需要回到 `ask_user_choice_tool.py` 检查 `_push_to_webchat_back_queue` 是否真的把 `spec` 整个传给了 `json.dumps`。

- [ ] **Step 3: 提交**

```bash
cd F:\github\astrbot_plugin_ask_user_choice
git add tests/test_ask_user_choice_tool.py
git commit -m "test(tool): cover extra_content SSE wire-format passthrough (v1.1)"
```

---

## Task 3: 文档 + 最终验证

**Files:**
- Modify: `metadata.yaml`
- Modify: `README.md`
- Modify: `AGENTS.md`(项目根的 AGENTS.md,非 spec/plan 目录)

**Interfaces:** 不输出新接口。纯文档/元数据变更。

- [ ] **Step 1: 更新 `metadata.yaml`**

打开 `metadata.yaml`,做 3 处改动:

**(a)** 在文件头注释中(spec 引用那一行后)加 v1.1 changelog 段:

```yaml
# Author: elecvoid243
# Date: 2026-06-30
# Spec: docs/superpowers/specs/2026-06-28-dynamic-choice-box-rendering-design.md §5.3 + §11
# v1.1 spec 增量: docs/superpowers/specs/2026-07-07-extra-content-field-amendment.md
#
# AstrBot 插件元数据。name 字段必须与目录名一致(以便 AstrBot 在 plugins/
# 扫描时识别),version 字段遵循 vMAJOR.MINOR.PATCH 语义化版本约定。
#
# v0.3.0 (2026-06-30): P1+P2 软阻塞增强
#   - description 改为更硬的话术("HARD RULES", "MUST NOT", "turn is OVER")
#   - 新增 @filter.on_llm_request 钩子,向 system_prompt 末尾注入
#     ask_user_choice 使用规范,marker = "# ask_user_choice 工具使用规范"
#   - 不做真阻塞(P0 已被否决),只是加大 LLM 自觉执行的概率。
#
# v1.0.0 (2026-07-02): 真阻塞式实现
#   - 工具 call() 内 await 用户选择,完成后直接返回结果给 LLM(不再是新
#     user message),跨 dashboard 刷新持久化。
#   - Spec: docs/superpowers/specs/2026-07-02-blocking-interactive-choice-design.md
#
# v1.1.0 (2026-07-07): extra_content 字段(加性变更)
#   - 工具参数新增可选 `extra_content`(string,≤5000 字符),用于承载
#     LLM 给用户看的推荐/理由/注意事项/优缺点对比等补充文本,前端按
#     Markdown 渲染。不回传到 tool result(避免 LLM 复读)。
#   - Spec: docs/superpowers/specs/2026-07-07-extra-content-field-amendment.md
```

**(b)** 把 `version: v1.0.0` 改成 `version: v1.1.0`。

**(c)** 在 `desc:` 末尾追加一句,描述 v1.1 能力:

```yaml
desc: 让 LLM 通过 ask_user_choice 工具向用户呈现可交互选项框（单选 + 自由输入）。v1.0 升级为真阻塞式:工具 await 用户选择,完成后直接返回结果,跨刷新持久化。v1.1 新增 `extra_content` 字段,支持 Markdown 补充说明(推荐/理由/注意事项/优缺点对比)。
```

- [ ] **Step 2: 更新 `README.md`**

打开 `README.md`,做 3 处改动:

**(a)** 在顶部"- **当前 spec**" 链接下追加一行:

```markdown
- **当前 spec**: [`docs/superpowers/specs/2026-07-02-blocking-interactive-choice-design.md`](docs/superpowers/specs/2026-07-02-blocking-interactive-choice-design.md)
- **v1.1 增量 spec**: [`docs/superpowers/specs/2026-07-07-extra-content-field-amendment.md`](docs/superpowers/specs/2026-07-07-extra-content-field-amendment.md)
- **历史 spec(已废弃)**: `2026-06-28-dynamic-choice-box-rendering-design.md`(v0.3 软阻塞设计,仅作历史记录)
```

**(b)** 在"## 用法"小节(LLM 自动调用那段后)追加一个 `extra_content` 调用示例:

```markdown
### 工具参数

LLM 调用 `ask_user_choice` 时可传以下参数:

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `prompt` | string | ✅ | 显示在选项框顶部的提问(≤200 字符) |
| `options` | array | ✅ | 选项列表,2~10 个,每个含 `id` / `label` / 可选 `description` |
| `title` | string | ❌ | 对话框标题(≤30 字符) |
| `input_placeholder` | string | ❌ | 自由输入框占位提示(≤60 字符) |
| `extra_content` | string | ❌ | **v1.1 新增** 补充说明(≤5000 字符),前端按 Markdown 渲染。用来给用户看推荐/理由/注意事项/优缺点对比,**不**回传到 LLM tool result |

调用示例(LLM 视角):

```python
ask_user_choice(
    prompt="选一个部署方案?",
    options=[
        {"id": "A", "label": "蓝绿", "description": "零停机,成本翻倍"},
        {"id": "B", "label": "灰度", "description": "可控,需 LB 支持"},
        {"id": "C", "label": "滚动", "description": "最便宜,有中断窗口"},
    ],
    title="部署方案",
    extra_content=(
        "**推荐 B**。\n\n"
        "理由:\n- 兼顾成本与风险\n- LB 已就绪\n\n"
        "**注意**: 灰度比例建议从 5% 起步"
    ),
)
```
```

**(c)** 在"### 非目标(v1 范围外)"小节里**删除**"- 推荐项标记 / "这一条(已支持 via `extra_content`),保留其他。改后:

```markdown
### 非目标(v1 范围外)

- 多选 / 嵌套 / 风险等级 / 超时倒计时 / 非 WebChat 平台适配 — 见 spec §1。
```

- [ ] **Step 3: 更新 `AGENTS.md`**

打开项目根的 `AGENTS.md`,定位 §4.2 `ask_user_choice_tool.py` 那一段,在职责描述末尾加一句:

```markdown
#### `ask_user_choice_tool.py`
- 工具类/函数集中地。
- 负责:
  1. 参数校验(`options` 长度、`description` 长度等)。
  2. 渲染"选项框"中间格式(由前端解析,具体协议见 spec)。
  3. 等待用户响应并以纯文本形式返回。
- 与 `main.py` 通过**构造函数注入**,不要在工具内部 import `main`。
- v1.1+ 工具参数含可选 `extra_content`(string,≤5000 字符,前端按 Markdown 渲染),
  详见 `docs/superpowers/specs/2026-07-07-extra-content-field-amendment.md`。
```

(原文 1.~4. 改成 1.~5. 之类的小编号调整**不需要**——直接追加一段即可,保持原编号。)

- [ ] **Step 4: 最终验证**

```bash
cd F:\github\astrbot_plugin_ask_user_choice
python -m py_compile main.py ask_user_choice_tool.py
python -m pytest tests/ -v
python -m ruff check .
```

**Expected**:
- `py_compile` 零错误
- pytest **全部 PASS**(v1.0 已有 + v1.1 新增 6 个 test)
- `ruff check .` 零错误(若有不影响运行的 warning,按 §3 风格修)

- [ ] **Step 5: 提交**

```bash
cd F:\github\astrbot_plugin_ask_user_choice
git add metadata.yaml README.md AGENTS.md
git commit -m "docs: bump v1.1.0 - add extra_content field"
```

- [ ] **Step 6: 验证 git log 整洁**

```bash
cd F:\github\astrbot_plugin_ask_user_choice
git log --oneline -5
```

**Expected**:看到 3 个 commit(spec 那个 commit `d016e57` + Task 1 feat + Task 2 test + Task 3 docs),按时间顺序。

---

## Self-Review Checklist

- [x] **Spec 覆盖**:每条 spec 条款都有对应 task。
  - §3.1 schema 新增 → Task 1 Step 4
  - §3.2 spec dict 形状 → Task 1 Step 5
  - §3.3 截断与边界 → Task 1 Step 5(截断)+ Step 1 测试(None / 空 / 空白 / 截断 / 非字符串)
  - §3.4 description 增量 → Task 1 Step 6
  - §4.1 前端类型扩展 → **不在本仓库 scope**(spec §4.3 明确说"前端代码在 webchat 仓库"),由对应前端 PR 独立完成
  - §4.2 truncateInteractiveChoice → 同上
  - §5 LLM 可见性(不 echo) → Task 1 Step 5(不修改 `_format_choice_for_llm`,默认就不传)
  - §6 测试策略 5 个用例 → Task 1 Step 1(5 个 test)
  - §7.1 向后兼容 → Task 1 Step 1 末尾更新的 `test_validate_returns_dict_on_valid_input`
  - §8 文档(metadata + README + AGENTS.md)→ Task 3
- [x] **占位符扫描**:全文无 TBD / TODO / "implement later" / "add appropriate error handling" / "similar to task N" 之类。每一步都有完整代码或精确指令。
- [x] **类型一致**:
  - `AskUserChoiceTool._validate_and_build_spec(kwargs) -> dict | str` — Task 1 / Task 2 都用这个签名。
  - `spec["extra_content"]` — Task 1 写入、Task 2 读取、Task 3 文档举例,key 名一致。
  - `_EXTRA_CONTENT_MAX = 5000` — Task 1 常量 + 测试导入 + spec 文档 §2/§3.3/§4.2 一致。
  - `chain_type == "interactive_choice"` — Task 2 筛选条件,沿用 Task 1/2 已有的 wire format 不变。

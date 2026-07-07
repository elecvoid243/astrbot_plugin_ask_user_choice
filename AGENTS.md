# AGENTS.md — astrbot_plugin_ask_user

---

## 1. 项目概览

- **类型**: AstrBot 插件(`astrbot` 第三方插件)。
- **作用**: 向 LLM 注册 `ask_user_choice` 工具,让 LLM 在需要人类拍板时输出"选项框"中间格式,前端动态渲染为按钮 + 自定义输入框,用户的选择以纯文本 user message 回传给 LLM。
- **运行环境**: 由 AstrBot 主程序加载,本身**不作为独立服务运行**,因此不存在传统意义上的"启动入口"和"打包产物"。
- **依赖**: 仅依赖 AstrBot `>=4.16,<5`,无第三方包。`requirements.txt` 保留仅为遵循 AstrBot 插件脚手架约定。
- **规范来源**: 设计细节以 `docs/superpowers/specs/2026-06-28-dynamic-choice-box-rendering-design.md` 为准(README 中链接,可能不在本仓库内)。

---

## 2. 构建 / Lint / 测试命令

本仓库没有 `Makefile`、`pyproject.toml`、`setup.py`、CI 配置或独立测试目录。所有"构建/测试"操作都依赖于宿主 AstrBot 与本地 Python 工具链。

### 2.1 语法 / 导入检查(必做,每次改完代码)

```bash
python -m py_compile main.py ask_user_choice_tool.py
```

编译错误 = **必须修复**;警告(如果有 `python -W` 启用)同样需要评估。CI 不存在,因此**本地必须自检**。

### 2.2 运行 AstrBot 加载插件

```bash
# 在 AstrBot 仓库根目录
python -m astrbot --reload-plugin astrbot_plugin_ask_user
```

或直接把本目录符号链接到 `Astrbot/data/plugins/astrbot_plugin_ask_user/` 后重启 AstrBot。**任何修改必须经过一次实际加载,确认 AstrBot 日志中无 traceback**。

### 2.3 单个工具的端到端验证

没有自动化测试,验证必须人工 + 真实 WebChat:

1. 启动 AstrBot,确保本插件被加载(查日志 `plugin loaded: astrbot_plugin_ask_user`)。
2. 在对话中触发 `ask_user_choice` 工具调用(可直接对 LLM 说"给我一个选项框,选项是 A/B/C")。
3. 确认:
   - 前端渲染出按钮列表 + 自由输入框。
   - 点击按钮 / 输入文本后,作为普通 user message 进入 LLM 上下文。
   - LLM 在下一轮能正确"接住"这个回复并继续。
4. 回归点(必须每次都跑):
   - 选项数量 = 1(边界)
   - 选项数量 = 10(README 标注的 v1 上限)
   - 用户**不点按钮**,直接发普通消息(应被当作正常 user message,不应被误判为工具回调)。

### 2.4 配置 schema 校验

`_conf_schema.json` 是 AstrBot 启动时读的**插件自定义配置 schema**,格式与标准 JSON Schema **不同**!不要写 `{"$schema": "...", "type": "object", "properties": {...}}` —— 这种格式会让 AstrBot 在 `_parse_schema` 里报 `TypeError: string indices must be integers, not 'str'`,因为它把 `$schema` URL 当字段值去取 `["type"]`。

**正确格式**(顶层直接是字段映射,每个字段必须有 `type`):

```json
{
  "field_name": {
    "type": "string",
    "default": "",
    "description": "可选",
    "hint": "可选(WebUI 提示)"
  },
  "another_field": {
    "type": "int",
    "default": 0,
    "min": 1,
    "max": 100
  }
}
```

支持的 `type`:`int` / `float` / `bool` / `string` / `text` / `list` / `file` / `object` / `template_list`(详见 `astrbot/core/config/default.py:DEFAULT_VALUE_MAP`)。

修改后必须保证 JSON 合法:

```bash
python -c "import json; json.load(open('_conf_schema.json'))"
```

如需验证 schema 能被 AstrBot 解析,可执行:

```bash
python -c "
import json, sys
sys.path.insert(0, r'F:\github\Astrbot')
from astrbot.core.config.default import DEFAULT_VALUE_MAP
schema = json.load(open('_conf_schema.json'))
def _parse_schema(schema, conf):
    for k, v in schema.items():
        assert v['type'] in DEFAULT_VALUE_MAP, f'{k}: {v[\"type\"]}'
        if v['type'] == 'object':
            conf[k] = {}; _parse_schema(v['items'], conf[k])
        else:
            conf[k] = v.get('default', DEFAULT_VALUE_MAP[v['type']])
_parse_schema(schema, {})
print('OK')
"
```

### 2.5 元数据校验

```bash
python -c "import yaml; yaml.safe_load(open('metadata.yaml'))"
```

---

## 3. 代码风格指南

> 本项目遵循 **PEP 8** + **PEP 257**(docstring)+ AstrBot 插件生态惯例。下面列出**本仓库内观察到的偏好**和**强约束**。

### 3.1 语言与版本

- **Python ≥ 3.10**(AstrBot 4.16+ 要求)。
- 文件头允许使用 UTF-8 中文注释,但**标识符、变量名必须英文**。
- 字符串中如含中文,直接写即可;无需 `\uXXXX` 转义。

### 3.2 导入(Imports)

- **顺序**: 标准库 → 第三方 → AstrBot SDK → 本项目内模块,各组之间空一行。
- **绝对导入**优先,只在 `TYPE_CHECKING` 守卫下使用相对导入避免循环依赖。
- AstrBot 相关类型/装饰器从 `astrbot.api` 系列顶层路径导入,避免深路径(便于 AstrBot 重构时少改)。

```python
# 正确示例
import asyncio
import json
from typing import Any

from astrbot.api import logger, register
from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import StarTools

from ask_user_choice_tool import AskUserChoiceTool
```

- **禁止** `import *`。
- **禁止** 无意义的 `from foo import Bar` 后只为了改个名(`as` 只在真名冲突或太长时使用)。

### 3.3 格式化

- **缩进**: 4 空格,禁用 Tab。
- **行长**: 软限 100,硬限 120。
- **引号**: 文件统一使用双引号 `"`,仅在三引号 docstring / 含双引号的字符串字面量中切换。
- **尾随逗号**: 多行容器结构**保留尾随逗号**(便于 diff 友好)。
- **空行**: 顶层函数/类之间 2 个空行;类内方法之间 1 个空行。

### 3.4 类型标注

- **强类型**: 所有公开函数签名必须有类型标注。
- **可选**: 用 `T | None`(PEP 604)而不是 `Optional[T]`,符合 3.10+ 风格。
- **工具回调**类型严格按 AstrBot 装饰器要求的签名,例如:

```python
@register("ask_user_choice", owner="astrbot_plugin_ask_user")
async def ask_user_choice(
    self,
    event: AstrMessageEvent,
    options: list[str],
    description: str = "",
) -> str:
    ...
```

- 不要使用 `Any`,除非对接 AstrBot 内部类型确实无法确定。
- 复杂数据结构使用 `TypedDict` 或 `dataclass`,不要裸 dict 满天飞。

### 3.5 命名约定

| 类别 | 规则 | 示例 |
|------|------|------|
| 模块 | 全小写下划线 | `ask_user_choice_tool.py` |
| 类 | PascalCase | `AskUserChoiceTool` |
| 函数 / 变量 | snake_case | `render_choice_box` |
| 常量 | UPPER_SNAKE | `MAX_OPTIONS = 10` |
| 私有 | 前缀单下划线 | `_normalize_options` |
| AstrBot 注册名 | snake_case,动词/名词 | `ask_user_choice` |
| 配置键 | 全小写下划线 | `max_options` |

- **禁止** 单字母变量名(`i`,`j` 仅在 1~2 行短循环中允许)。
- 布尔变量/参数用 `is_` / `has_` / `should_` 前缀或谓词形式(`enabled`,`allow_custom`)。

### 3.6 字符串与消息

- **用户可见文案**(给 LLM 的工具描述 / 给前端的渲染提示)用 f-string 拼接,不要 `+`。
- 跨语言 i18n **不在 v1 范围**,所有文案保持中文(README 已明确)。
- 工具返回给 LLM 的字符串**必须是普通自然语言**,**不要**夹带 sentinel token(如 `[TOOL_RESULT]`),因为前端不会做标记 —— 用户的选择以裸 user message 形式回传。

### 3.7 异步

- 工具回调、事件处理函数一律 `async def`。
- **禁止** 在 `async def` 中调用阻塞 I/O(如 `time.sleep`、`requests.get`),需要时用 `await asyncio.sleep` 或 `aiohttp`。
- 不确定 AstrBot 是否已在事件循环里时,不要手动 `asyncio.run` / `loop.run_until_complete`。

### 3.8 错误处理

- 工具回调抛出的异常会被 AstrBot 捕获并以 system message 形式回给 LLM —— 所以:
  - **可恢复错误**(参数校验失败)应返回 `str` 错误说明,**让 LLM 自己重试**,而不是抛异常。
  - **不可恢复错误**(框架内部故障)才 `raise`。
- 捕获异常时**必须**指明类型,不要 `except Exception:` 裸接;至少 `except Exception as e:` 并 `logger.exception(...)`。
- 校验失败的具体原因写进日志 + 工具返回值,便于 LLM 调整。

```python
if not isinstance(options, list) or len(options) == 0:
    logger.warning("ask_user_choice: options 为空或类型错误")
    return "错误:options 必须是非空列表。"
```

### 3.9 日志

- 使用 `from astrbot.api import logger`,**不要** `print()`。
- 日志级别:
  - `debug`: 开发期细节(payload 序列化等)。
  - `info`: 关键生命周期(插件加载、工具被注册)。
  - `warning`: 可恢复异常。
  - `error`: 影响当前请求但不影响后续。
  - `exception`: 含 traceback 的异常。

### 3.10 注释与 docstring

- 所有公开函数写 Google 风格 docstring:

```python
async def ask_user_choice(event, options, description=""):
    """向用户呈现一个选项框,等待用户选择。

    Args:
        event: AstrBot 消息事件。
        options: 选项文本列表,长度 1~10。
        description: 给用户的额外说明,会显示在选项上方。

    Returns:
        用户的选择结果(以文本形式),LLM 据此继续推理。
    """
```

- 行内注释用 `# ` 后接 1 个空格,中文注释允许。
- 不要写"显而易见"的注释(`# 循环 i` 之类的删掉)。

### 3.11 安全与隐私

- LLM 工具调用是**半可信输入**:不要直接 `eval` / `exec` LLM 传入的字段。
- 配置 schema 中**所有用户可填字段都要给默认值**,避免 AstrBot 启动时崩。
- 用户在前端输入的自定义文本**视为不可信**:
  - 不要直接拼到 SQL/Shell。
  - 长度做上限(如 500 字符),超出截断并 `logger.warning`。

---

## 4. 目录结构与架构

### 4.1 顶层布局

```
astrbot_plugin_ask_user/
├── README.md                  # 用户面向文档(中文)
├── main.py                    # 插件入口:@register 注册、生命周期
├── ask_user_choice_tool.py    # 核心:ask_user_choice 工具实现
├── _conf_schema.json          # AstrBot WebUI 配置 schema
├── metadata.yaml              # 插件元数据(作者、版本、依赖)
├── requirements.txt           # 依赖声明(仅声明 astrbot)
└── AGENTS.md                  # 本文件,代理面向
```

> 文件**全部平铺在根目录**,没有子目录。这是 AstrBot 插件脚手架的强制约束 —— 入口文件必须在包根。

### 4.2 模块职责

#### `metadata.yaml`
AstrBot 启动时读的清单,**必须**字段:
- `name`: 插件名(必须与目录名一致,本仓库为 `astrbot_plugin_ask_user`)。
- `author`: 作者署名。
- `version`: 语义化版本,**每次改动用户可见行为必须 bump**。
- `astrbot_version`: 兼容范围(与 `requirements.txt` 保持一致)。

#### `_conf_schema.json`
AstrBot WebUI 渲染配置面板用的 JSON Schema。修改后:
- 新字段必须有 `default`。
- 删除字段前确认 `metadata.yaml` 与 README 都没引用。
- 字段名保持全小写下划线。

#### `main.py`
- 用 `@register` 装饰器向 AstrBot 注册插件本体。
- 在 `__init__` 里实例化 `AskUserChoiceTool` 并注册为工具。
- 不要在这里写业务逻辑,只做"组装"。

**`__init__` 签名(必读,AstrBot 插件 vs 纯 Python 类的差异)**

当插件声明了 `_conf_schema.json`,AstrBot 的 `StarManager` 会用以下签名实例化插件(见 `astrbot/core/star/star_manager.py:1235-1250`):

```python
obj = plugin_cls(context=self.context, config=plugin_config,)
```

**必须**这样写:

```python
def __init__(self, context: star.Context, config: AstrBotConfig) -> None:
    super().__init__(context)
    self.config = config
```

如果只写 `def __init__(self, context)`,**不要**指望 `self.config` 自动出现 —— AstrBot 框架不会注入。第一次写插件的开发者 100% 会踩这个坑(`AttributeError: object has no attribute 'config'`)。

参考实现:`F:\github\astrbot_plugin_neo_cargo\main.py:155-165`(`NeoCargoPlugin.__init__`)。

#### `ask_user_choice_tool.py`
- 工具类/函数集中地。
- 负责:
  1. 参数校验(`options` 长度、`description` 长度等)。
  2. 渲染"选项框"中间格式(由前端解析,具体协议见 spec)。
  3. 等待用户响应并以纯文本形式返回。
- 与 `main.py` 通过**构造函数注入**,不要在工具内部 import `main`。
- v1.1+ 工具参数含可选 `extra_content`(string,≤5000 字符,前端按 Markdown 渲染),
  详见 `docs/superpowers/specs/2026-07-07-extra-content-field-amendment.md`。

#### `requirements.txt`
- 当前仅含 `astrbot>=4.16,<5`。
- 添加新依赖前**三思**:AstrBot 插件应尽量复用 SDK 已带的库(aiohttp、jinja2 等),否则会污染宿主环境。

### 4.3 数据流

```
LLM  ──(tool call: ask_user_choice(options=[...]))──▶  AstrBot
                                                         │
                                                         ▼
                                                  ask_user_choice_tool.py
                                                         │ 校验 + 渲染中间格式
                                                         ▼
                                                  AstrBot 事件总线
                                                         │
                                                         ▼
                                                  WebChat 前端
                                                         │ 渲染按钮 + 输入框
                                                         ▼
                                                  用户点击 / 输入
                                                         │
                                                         ▼
                                                  AstrBot 事件总线(普通 user message)
                                                         │
                                                         ▼
                                                  LLM(从上下文推断这是工具回调)
```

**关键点**: 从 AstrBot 侧看,用户的选择就是一个普通 `UserMessage`,不带任何工具调用标记。**这是设计,不是 bug —— 不要试图加 sentinel**。

#### 4.3.1 软阻塞(soft-blocking) — v0.3.0+

`AskUserChoiceTool.call()` **不会真阻塞 LLM**:`call()` 立即返回 JSON,框架把 tool result 喂给 LLM 后,LLM 仍可能继续输出文字 / 调其他工具 / 自己做假设。"LLM 是否在选项框出现后停下"完全靠 LLM 自觉。

v0.3.0 通过两道 prompt-level 强化提高自觉率(P0 真阻塞已被用户否决):

| 强化层 | 实现 | 命中时机 |
|---|---|---|
| **P1 硬话术 tool description** | `ask_user_choice_tool.py:description` 字段,包含 `HARD RULES` / `MUST NOT` / `turn is OVER` 等强语气短语 | LLM 决定调不调、看 description 时 |
| **P2 system_prompt 注入** | `main.py:AskUserChoicePlugin._inject_ask_user_choice_policy` 通过 `@filter.on_llm_request()` 钩子,把 `# ask_user_choice tool policy` 段追加到 `req.system_prompt` 末尾;marker 防重复 | 每次 LLM 请求前 |

参考实现来自 `astrbot_plugin_spcode_toolkit` 的 `tools/agentsmd/_handlers.py:AgentsmdHandlers.on_llm_request`(同样采用 "marker 防重复 + 空字符串特判")。

**为什么不做真阻塞(P0)?** 真阻塞需要在 `call()` 里 `await` 用户响应,会挂起 agent runner 协程,需要新增前端 submit 事件回传 + `asyncio.Future` 跨协程解锁,工程量大且牵涉 AstrBot 框架。软阻塞在绝大多数 LLM(Claude / GPT-4o / DeepSeek 等)上效果已够用。

**已知失效场景**(软阻塞救不回来的):
- 弱指令跟随的 LLM 仍可能调 `ask_user_choice` 之后又输出 "我先帮你做 X"
- LLM 在同一条 assistant 消息里连续调多个 `ask_user_choice`(框架本身会串行执行,但 LLM 的"一次性提问"语义被破坏)
- LLM 在 tool result 之后立刻调别的工具(如 `astrbot_execute_shell`)而不管选项框

要根治这些问题,必须走 P0 真阻塞方案。

### 4.4 架构原则

1. **薄插件**: 业务尽量推给 AstrBot SDK / 前端,本插件只做"格式转换 + 参数校验"。
2. **幂等注册**: `main.py` 应可重复 import 不爆,AstrBot 可能在热重载时多次走入口。
3. **无全局可变状态**: 工具实例状态只放实例属性,不要 `module-level` 字典。
4. **向前兼容**: 给 LLM 的工具 description 字段**不可随意删字段**,LLM 训练/提示词可能依赖。改字段名 = bump major。

## Task 7: 工具 - _format_choice_for_llm

**Files:**
- Modify: `astrbot_plugin_ask_user_choice/ask_user_choice_tool.py`
- Modify: `astrbot_plugin_ask_user_choice/tests/test_ask_user_choice_tool.py`

**Interfaces:**
- Produces: `AskUserChoiceTool._format_choice_for_llm(user_choice, spec) -> str`

- [ ] **Step 1: Add failing test**

Append to `tests/test_ask_user_choice_tool.py`:

```python
def test_format_choice_with_label_only():
    tool = AskUserChoiceTool()
    spec = {"options": [{"id": "A", "label": "alpha"}, {"id": "B", "label": "beta"}]}
    result = tool._format_choice_for_llm({"choice_id": "A", "free_text": ""}, spec)
    assert "alpha" in result
    assert "id=A" in result
    assert "Additional note" not in result


def test_format_choice_with_free_text():
    tool = AskUserChoiceTool()
    spec = {"options": [{"id": "A", "label": "alpha"}, {"id": "B", "label": "beta"}]}
    result = tool._format_choice_for_llm({"choice_id": "B", "free_text": "因为快"}, spec)
    assert "beta" in result
    assert "id=B" in result
    assert "因为快" in result
    assert "Additional note" in result


def test_format_choice_with_free_text_only():
    tool = AskUserChoiceTool()
    spec = {"options": [{"id": "A", "label": "alpha"}, {"id": "B", "label": "beta"}]}
    result = tool._format_choice_for_llm(
        {"choice_id": "__free_text__", "free_text": "我选自己想的"}, spec,
    )
    assert "__free_text__" in result
    assert "我选自己想的" in result


def test_format_choice_unknown_id_falls_back_to_id():
    tool = AskUserChoiceTool()
    spec = {"options": [{"id": "A", "label": "alpha"}]}
    result = tool._format_choice_for_llm({"choice_id": "Z", "free_text": ""}, spec)
    # Z 不在 options 里,label fallback 到 choice_id
    assert "Z" in result
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd astrbot_plugin_ask_user_choice && python -m pytest tests/test_ask_user_choice_tool.py -v
```

Expected: FAIL with `NotImplementedError: Implemented in Task 7`

- [ ] **Step 3: Implement _format_choice_for_llm**

Replace the placeholder method in `ask_user_choice_tool.py`:

```python
    def _format_choice_for_llm(self, user_choice: dict, spec: dict) -> str:
        """把用户响应格式化为 LLM 可见字符串。

        Args:
            user_choice: {choice_id, free_text}
            spec: 工具构造的 spec(含 options 列表)。

        Returns:
            "User selected: <label> (id=<id>)[\\nAdditional note: <free_text>]"
        """
        choice_id = user_choice.get("choice_id", "")
        free_text = (user_choice.get("free_text") or "").strip()
        label = choice_id
        for opt in spec.get("options", []):
            if opt.get("id") == choice_id:
                label = opt.get("label") or choice_id
                break
        if free_text:
            return f"User selected: {label} (id={choice_id})\nAdditional note: {free_text}"
        return f"User selected: {label} (id={choice_id})"
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd astrbot_plugin_ask_user_choice && python -m pytest tests/test_ask_user_choice_tool.py -v
```

Expected: 14 passed (7 validate + 3 call + 4 format)

- [ ] **Step 5: Commit**

```bash
cd astrbot_plugin_ask_user_choice
git add ask_user_choice_tool.py tests/test_ask_user_choice_tool.py
git commit -m "feat(tool): implement _format_choice_for_llm"
```

---

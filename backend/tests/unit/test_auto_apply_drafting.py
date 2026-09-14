"""Drafted answers are converted to the form's format, never confirmed,
and dropped when they don't fit the question."""

from app.services.auto_apply.drafting import draft_answers, to_field_value


def field(key, type_, options=None):
    return {"key": key, "label": key, "type": type_, "required": True, "options": options,
            "description": None, "group": "application"}


YES_NO = [{"label": "Yes", "value": "1"}, {"label": "No", "value": "0"}]


def test_to_field_value():
    assert to_field_value(field("s", "select", YES_NO), ["yes"]) == "1"
    assert to_field_value(field("s", "select", YES_NO), "No") == "0"
    assert to_field_value(field("s", "select", YES_NO), ["Maybe"]) is None
    assert to_field_value(field("s", "select", YES_NO), ["Yes", "No"]) is None
    assert to_field_value(field("m", "multiselect", YES_NO), ["Yes", "No"]) == ["1", "0"]
    assert to_field_value(field("b", "boolean"), "Yes") is True
    assert to_field_value(field("b", "boolean"), "perhaps") is None
    assert to_field_value(field("n", "number"), "1,200") == 1200
    assert to_field_value(field("n", "number"), "about five") is None
    assert to_field_value(field("t", "textarea"), "  I led the launch.  ") == "I led the launch."
    assert to_field_value(field("t", "text"), None) is None
    assert to_field_value(field("t", "text"), "null") is None


class FakeLLM:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def generate_structured(self, task_type, system_prompt, user_prompt, tools, max_tokens=4096, tool_choice=None):
        self.calls.append((task_type, user_prompt))
        return self.result


async def test_draft_answers():
    items = [
        field("why", "textarea"),
        field("relocate", "select", YES_NO),
        field("years_android", "select", [{"label": "0-4", "value": "a"}]),
        field("cv", "file"),
    ]
    llm = FakeLLM({"answers": [
        {"key": "why", "answer": "I built payments tooling at Acme for 3 years.", "basis": "PM at Acme"},
        {"key": "relocate", "answer": None, "basis": "none"},
        {"key": "years_android", "answer": ["10+"], "basis": "guess"},
        {"key": "made_up_key", "answer": "x", "basis": "x"},
    ]})
    drafted = await draft_answers(items, "Name: Ada", {"title": "PM", "company": "Stripe", "description": "Build."}, llm=llm)

    assert list(drafted) == ["why"]
    assert drafted["why"]["value"] == "I built payments tooling at Acme for 3 years."
    assert drafted["why"]["source"] == "drafted" and drafted["why"]["confirmed"] is False
    assert "PM at Acme" in drafted["why"]["note"]

    task_type, prompt = llm.calls[0]
    assert task_type == "applying"
    assert '"key": "relocate"' in prompt and '"options": ["Yes", "No"]' in prompt
    assert '"key": "cv"' not in prompt  # files aren't drafted


async def test_nothing_to_draft_makes_no_call():
    llm = FakeLLM({"answers": []})
    assert await draft_answers([field("cv", "file")], "Name: Ada", {}, llm=llm) == {}
    assert llm.calls == []

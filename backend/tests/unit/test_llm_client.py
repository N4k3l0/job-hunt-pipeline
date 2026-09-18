from types import SimpleNamespace

import pytest

from app.llm import client as llm_module
from app.llm.client import LLMClient, LLMRefusalError, THINKING_HEADROOM_TOKENS


def _response(*blocks, stop_reason="end_turn", model="claude-sonnet-5", stop_details=None):
    return SimpleNamespace(
        content=list(blocks),
        stop_reason=stop_reason,
        stop_details=stop_details,
        model=model,
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )


class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def _client_with(response) -> tuple[LLMClient, FakeMessages, FakeMessages]:
    messages = FakeMessages(response)
    beta_messages = FakeMessages(response)
    llm = LLMClient()
    llm._client = SimpleNamespace(messages=messages, beta=SimpleNamespace(messages=beta_messages))
    return llm, messages, beta_messages


async def test_generate_skips_thinking_blocks():
    llm, messages, _ = _client_with(_response(
        SimpleNamespace(type="thinking", thinking=""),
        SimpleNamespace(type="text", text="Hello "),
        SimpleNamespace(type="text", text="there"),
    ))
    assert await llm.generate("parsing", "sys", "hi", max_tokens=100) == "Hello there"


async def test_request_shape_for_sonnet_tasks():
    llm, messages, beta_messages = _client_with(_response(SimpleNamespace(type="text", text="ok")))
    await llm.generate("scoring", "sys", "hi", max_tokens=100)

    (call,) = messages.calls
    assert beta_messages.calls == []
    assert call["model"] == "claude-sonnet-5"
    assert call["max_tokens"] == 100 + THINKING_HEADROOM_TOKENS
    assert call["output_config"] == {"effort": "medium"}
    assert "temperature" not in call


async def test_extraction_uses_haiku_without_effort_or_thinking_headroom():
    llm, messages, _ = _client_with(_response(
        SimpleNamespace(type="tool_use", name="record", input={"ok": True}), model="claude-haiku-4-5",
    ))
    await llm.generate_structured("extraction", "sys", "hi", tools=[{"name": "record"}], max_tokens=1500)

    (call,) = messages.calls
    assert call["model"] == "claude-haiku-4-5"
    assert call["max_tokens"] == 1500
    assert "output_config" not in call


async def test_opus_tasks_use_server_side_fallbacks(monkeypatch):
    """Whatever task is put on Opus gets the server-side fallback, so a
    busy Opus doesn't fail the call. No task uses Opus today: writing runs
    on Sonnet, which costs a fifth as much for the same job."""
    monkeypatch.setitem(llm_module.MODELS, "tailoring", "claude-opus-5")
    llm, messages, beta_messages = _client_with(
        _response(SimpleNamespace(type="text", text="ok"), model="claude-opus-5")
    )
    await llm.generate("tailoring", "sys", "hi", max_tokens=100)

    (call,) = beta_messages.calls
    assert messages.calls == []
    assert call["model"] == "claude-opus-5"
    assert call["fallbacks"] == "default"
    assert call["betas"] == [llm_module.FALLBACK_BETA]


async def test_refusal_raises():
    llm, _, _ = _client_with(_response(
        stop_reason="refusal",
        stop_details=SimpleNamespace(category="cyber"),
    ))
    with pytest.raises(LLMRefusalError, match="cyber"):
        await llm.generate("parsing", "sys", "hi")


async def test_generate_structured_returns_tool_input():
    llm, messages, _ = _client_with(_response(
        SimpleNamespace(type="thinking", thinking=""),
        SimpleNamespace(type="tool_use", name="record", input={"word": "OK"}),
    ))
    tools = [{"name": "record", "input_schema": {"type": "object"}}]
    assert await llm.generate_structured("parsing", "sys", "hi", tools=tools) == {"word": "OK"}
    assert messages.calls[0]["tool_choice"] == {"type": "any"}


async def test_generate_structured_without_tool_or_text_raises():
    llm, _, _ = _client_with(_response(SimpleNamespace(type="thinking", thinking="")))
    with pytest.raises(RuntimeError, match="no tool_use"):
        await llm.generate_structured("parsing", "sys", "hi", tools=[])

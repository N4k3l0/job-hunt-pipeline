from types import SimpleNamespace

import pytest

from app.llm import client as llm_module
from app.llm.client import (
    LLMClient,
    LLMCreditsExhausted,
    LLMRefusalError,
    THINKING_HEADROOM_TOKENS,
    credits_paused,
)

CREDIT_ERROR = (
    "Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', "
    "'message': 'Your credit balance is too low to access the Anthropic API. "
    "Please go to Plans & Billing to upgrade or purchase credits.'}}"
)




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


class FailingMessages(FakeMessages):
    def __init__(self, error: Exception):
        super().__init__(None)
        self.error = error

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        raise self.error


def _failing_client(error: Exception) -> tuple[LLMClient, FailingMessages]:
    messages = FailingMessages(error)
    llm = LLMClient()
    llm._client = SimpleNamespace(messages=messages, beta=SimpleNamespace(messages=messages))
    return llm, messages


async def test_running_out_of_credits_pauses_every_ai_call():
    llm, messages = _failing_client(RuntimeError(CREDIT_ERROR))

    with pytest.raises(LLMCreditsExhausted):
        await llm.generate("parsing", "sys", "hi", max_tokens=100)
    assert credits_paused()
    assert len(messages.calls) == 1

    # While paused, nothing is sent: not through generate, generate_structured,
    # or callers that build their own requests.
    with pytest.raises(LLMCreditsExhausted):
        await llm.generate("tailoring", "sys", "hi", max_tokens=100)
    with pytest.raises(LLMCreditsExhausted):
        await llm.generate_structured("extraction", "sys", "hi", tools=[], max_tokens=100)
    with pytest.raises(LLMCreditsExhausted):
        await llm.client.messages.create(model="claude-haiku-4-5", max_tokens=10, messages=[])
    assert len(messages.calls) == 1


async def test_calls_go_through_again_once_the_pause_ends(monkeypatch):
    llm, messages, _ = _client_with(_response(SimpleNamespace(type="text", text="back")))
    monkeypatch.setattr(llm_module, "_credits_paused_until", llm_module.time.time() + 60)
    with pytest.raises(LLMCreditsExhausted):
        await llm.generate("parsing", "sys", "hi", max_tokens=100)
    assert messages.calls == []

    monkeypatch.setattr(llm_module, "_credits_paused_until", llm_module.time.time() - 1)
    assert await llm.generate("parsing", "sys", "hi", max_tokens=100) == "back"
    assert await llm.client.messages.create(model="claude-haiku-4-5", max_tokens=10, messages=[])
    assert len(messages.calls) == 2


async def test_other_errors_do_not_pause():
    llm, messages = _failing_client(RuntimeError("Error code: 529 - overloaded_error"))
    with pytest.raises(RuntimeError, match="overloaded"):
        await llm.generate("parsing", "sys", "hi", max_tokens=100)
    assert not credits_paused()


async def test_api_answers_in_plain_words_while_paused():
    import httpx

    from app.main import create_app

    app = create_app()

    async def needs_ai():
        raise LLMCreditsExhausted()

    app.add_api_route("/needs-ai", needs_ai)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/needs-ai")
    assert r.status_code == 503
    assert r.json()["detail"] == llm_module.PAUSED_MESSAGE
    assert "Anthropic" not in r.json()["detail"]


async def test_a_pause_one_worker_hits_holds_for_the_others(monkeypatch):
    llm, messages = _failing_client(RuntimeError(CREDIT_ERROR))
    with pytest.raises(LLMCreditsExhausted):
        await llm.generate("parsing", "sys", "hi", max_tokens=100)

    # Another worker process: same pause file, nothing in memory.
    monkeypatch.setattr(llm_module, "_credits_paused_until", 0.0)
    other, other_messages = _failing_client(RuntimeError("should not be called"))
    assert credits_paused()
    with pytest.raises(LLMCreditsExhausted):
        await other.generate("parsing", "sys", "hi", max_tokens=100)
    assert other_messages.calls == []

    llm_module.end_credits_pause()
    assert not credits_paused()
    assert not llm_module.PAUSE_FILE.exists()


def test_an_unreadable_or_old_pause_file_does_not_pause():
    llm_module.PAUSE_FILE.write_text("not a number")
    assert not credits_paused()
    llm_module.PAUSE_FILE.write_text(repr(llm_module.time.time() - 5))
    assert not credits_paused()

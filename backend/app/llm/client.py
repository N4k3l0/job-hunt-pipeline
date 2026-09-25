import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from app.core.config import get_settings

# anthropic is imported lazily inside _client_lazy(). The SDK + its
# pydantic models cost ~500ms to import on Vercel's cold-start —
# routes that never call the LLM (the inbox, /me, /jobs) should not
# pay that cost. Imported on first .generate() call instead.

logger = logging.getLogger(__name__)
settings = get_settings()

# Model selection per task type. Haiku for high-volume field extraction
# from every incoming job; Sonnet for parsing, scoring and web search
# (mechanical, cost-sensitive); Sonnet for tailoring and outreach
# (creative, accuracy-sensitive).
MODELS = {
    "extraction": "claude-haiku-4-5",
    "parsing": "claude-sonnet-5",
    "scoring": "claude-sonnet-5",
    "search": "claude-sonnet-5",
    "tailoring": "claude-sonnet-5",
    "applying": "claude-sonnet-5",
}

# Sonnet 5 and Opus 5 think by default. Every call runs inside a Vercel
# request capped at 60s, so extraction runs at low effort and writing at
# medium rather than the API default of high. None = the model doesn't
# take an effort setting (Haiku 4.5 rejects it) and doesn't think unless
# asked, so no thinking headroom either.
EFFORT = {
    "extraction": None,
    "parsing": "low",
    "scoring": "medium",
    "search": "low",
    "tailoring": "medium",
    "applying": "medium",
}

# Thinking counts toward max_tokens. Callers size max_tokens for the
# answer alone, so this is added on top.
THINKING_HEADROOM_TOKENS = 4000

# Opus 5's safety classifiers can decline a request. fallbacks="default"
# re-runs a declined request on Anthropic's recommended fallback model
# inside the same call instead of returning the refusal.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = frozenset({"claude-opus-5"})

# Below Vercel's 60s function limit, so a hung call surfaces as an error
# the route can handle instead of the function being killed.
REQUEST_TIMEOUT_SECONDS = 45.0


class LLMRefusalError(RuntimeError):
    """The model (and any fallback) declined the request."""


# When the Anthropic account runs out of credits, every call fails the same
# way. Rather than keep asking (the job reader alone failed 25 times every
# scheduler run), all AI calls pause, then try once more after this long.
# Topping up turns AI back on within half an hour.
CREDITS_PAUSE_SECONDS = 30 * 60
# For the admin: what happened and how to fix it.
CREDITS_MESSAGE = (
    "The Anthropic credits have run out, so AI features are paused. "
    "They turn back on by themselves within half an hour of topping up."
)
# For everyone else: users can't top up, so they only need to know to wait.
PAUSED_MESSAGE = (
    "Our AI helper is paused for a little while, so this can't be done right now. "
    "Please try again later."
)

# The backend runs several worker processes in one container. The pause is
# kept in a small file in the container's temp folder as well as in memory,
# so a pause one worker hits holds for all of them, and the admin notice
# agrees whichever worker answers. A deploy starts a new container, which
# clears it.
PAUSE_FILE = Path(os.environ.get("AI_PAUSE_FILE") or Path(tempfile.gettempdir()) / "job-hunt-ai-paused-until")

_credits_paused_until = 0.0  # wall clock, so every process reads it the same way


class LLMCreditsExhausted(RuntimeError):
    """The Anthropic account is out of credits. No call is sent while paused."""

    def __init__(self, message: str = PAUSED_MESSAGE):
        super().__init__(message)


def credits_paused() -> bool:
    """True while AI calls are paused because the credits ran out, by this
    worker or another."""
    global _credits_paused_until
    now = time.time()
    if now < _credits_paused_until:
        return True
    try:
        until = float(PAUSE_FILE.read_text())
    except (OSError, ValueError):
        return False
    if now < until:
        _credits_paused_until = until
        return True
    return False


async def _guarded(call, **kwargs):
    """Make one API call, unless the credits are known to be out."""
    if credits_paused():
        raise LLMCreditsExhausted()
    try:
        return await call(**kwargs)
    except Exception as e:
        if _is_out_of_credits(e):
            _pause_for_credits()
            raise LLMCreditsExhausted() from e
        raise


class _GuardedMessages:
    def __init__(self, messages):
        self._messages = messages

    async def create(self, **kwargs):
        return await _guarded(self._messages.create, **kwargs)


class _GuardedClient:
    """What `llm_client.client` hands out: the SDK client, with the credit
    pause on `messages.create` for the callers that build requests
    themselves (web search, translation)."""

    def __init__(self, client):
        self._client = client
        self.messages = _GuardedMessages(client.messages)

    def __getattr__(self, name):
        return getattr(self._client, name)


def _is_out_of_credits(error: Exception) -> bool:
    text = str(error).lower()
    return "credit balance is too low" in text or "billing_error" in text


def _pause_for_credits() -> None:
    global _credits_paused_until
    if not credits_paused():
        logger.warning("Anthropic credits have run out: pausing AI calls for %d minutes", CREDITS_PAUSE_SECONDS // 60)
    _credits_paused_until = time.time() + CREDITS_PAUSE_SECONDS
    # Written whole then renamed, so another worker never reads half a number.
    staging = PAUSE_FILE.with_name(f"{PAUSE_FILE.name}.{os.getpid()}")
    try:
        staging.write_text(repr(_credits_paused_until))
        os.replace(staging, PAUSE_FILE)
    except OSError as e:
        logger.warning("Couldn't share the AI pause with other workers: %s", e)


def end_credits_pause() -> None:
    """Turn AI back on now, in every worker, instead of waiting out the pause."""
    global _credits_paused_until
    _credits_paused_until = 0.0
    PAUSE_FILE.unlink(missing_ok=True)


def model_for(task_type: str) -> str:
    return MODELS.get(task_type, MODELS["parsing"])


def effort_for(task_type: str) -> str | None:
    return EFFORT.get(task_type, "medium")


class LLMClient:
    """Wrapper around the Claude API: per-task model and effort, refusal
    handling, and token logging. Retries on 408/409/429/5xx and connection
    errors come from the SDK (max_retries).

    The underlying anthropic.AsyncAnthropic client is built lazily on
    first use so importing this module is cheap. Saves ~500ms cold-start
    per Vercel function invocation that doesn't actually call the LLM.
    """

    def __init__(self):
        self._client = None

    def _client_lazy(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.AsyncAnthropic(
                api_key=settings.anthropic_api_key,
                timeout=REQUEST_TIMEOUT_SECONDS,
                max_retries=2,
            )
        return self._client

    @property
    def client(self):
        # For callers that build their own requests (web search, translation).
        return _GuardedClient(self._client_lazy())

    async def _create(self, task_type: str, **kwargs: Any):
        model = model_for(task_type)
        kwargs["model"] = model
        effort = effort_for(task_type)
        if effort is not None:
            kwargs["max_tokens"] += THINKING_HEADROOM_TOKENS
            kwargs["output_config"] = {"effort": effort}
        client = self._client_lazy()
        if model in FALLBACK_MODELS:
            response = await _guarded(
                client.beta.messages.create,
                **kwargs, betas=[FALLBACK_BETA], fallbacks="default",
            )
        else:
            response = await _guarded(client.messages.create, **kwargs)

        usage = response.usage
        logger.info(
            "LLM call: task=%s model=%s served_by=%s input_tokens=%d output_tokens=%d stop=%s",
            task_type, model, response.model, usage.input_tokens,
            usage.output_tokens, response.stop_reason,
        )

        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None)
            raise LLMRefusalError(
                f"Claude declined the {task_type} request"
                + (f" (category: {category})" if category else "")
            )
        return response

    async def generate(
        self,
        task_type: str,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096,
    ) -> str:
        """Generate a text response from Claude."""
        response = await self._create(
            task_type,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        # Thinking blocks come before the text, so join the text blocks
        # rather than reading content[0].
        return "".join(
            block.text for block in response.content if block.type == "text"
        )

    async def generate_structured(
        self,
        task_type: str,
        system_prompt: str,
        user_prompt: str,
        tools: list[dict[str, Any]],
        max_tokens: int = 4096,
        tool_choice: dict[str, Any] | None = None,
    ) -> dict:
        """Generate structured output using Claude's tool use.

        Default tool_choice is `any` — i.e. force the model to call ONE
        of the provided tools. Previously this was `auto`, which let the
        model fall back to text and silently break callers (deep scorer,
        decision-maker finder, target-role auto-suggest) that all
        require a structured tool response. Override via the parameter
        if a caller really wants opt-in behavior.
        """
        response = await self._create(
            task_type,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            tools=tools,
            tool_choice=tool_choice or {"type": "any"},
        )

        for block in response.content:
            if block.type == "tool_use":
                return block.input

        # Fallback: no tool_use block in the response. With tool_choice=any
        # this shouldn't happen, but be defensive — pull the text if
        # present, else surface a clear error rather than crashing on a
        # missing attribute.
        text = "".join(
            block.text for block in response.content if block.type == "text"
        )
        if text:
            return {"text": text}
        raise RuntimeError(
            "LLM returned no tool_use or text content. "
            f"stop_reason={response.stop_reason}"
        )


# Singleton
llm_client = LLMClient()

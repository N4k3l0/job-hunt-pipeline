import logging
from typing import Any

from app.core.config import get_settings

# anthropic is imported lazily inside _client_lazy(). The SDK + its
# pydantic models cost ~500ms to import on Vercel's cold-start —
# routes that never call the LLM (the inbox, /me, /jobs) should not
# pay that cost. Imported on first .generate() call instead.

logger = logging.getLogger(__name__)
settings = get_settings()

# Model selection per task type. Sonnet for parsing, scoring and web
# search (mechanical, cost-sensitive); Opus for tailoring and outreach
# (creative, accuracy-sensitive).
MODELS = {
    "parsing": "claude-sonnet-5",
    "scoring": "claude-sonnet-5",
    "search": "claude-sonnet-5",
    "tailoring": "claude-opus-5",
}

# Sonnet 5 and Opus 5 think by default. Every call runs inside a Vercel
# request capped at 60s, so extraction runs at low effort and writing at
# medium rather than the API default of high.
EFFORT = {
    "parsing": "low",
    "scoring": "medium",
    "search": "low",
    "tailoring": "medium",
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


def model_for(task_type: str) -> str:
    return MODELS.get(task_type, MODELS["parsing"])


def effort_for(task_type: str) -> str:
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
        # Backwards-compat for any caller still touching .client directly.
        return self._client_lazy()

    async def _create(self, task_type: str, **kwargs: Any):
        model = model_for(task_type)
        kwargs.update(
            model=model,
            max_tokens=kwargs["max_tokens"] + THINKING_HEADROOM_TOKENS,
            output_config={"effort": effort_for(task_type)},
        )
        client = self._client_lazy()
        if model in FALLBACK_MODELS:
            response = await client.beta.messages.create(
                **kwargs, betas=[FALLBACK_BETA], fallbacks="default"
            )
        else:
            response = await client.messages.create(**kwargs)

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

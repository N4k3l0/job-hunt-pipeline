import logging
from typing import Any

from app.core.config import get_settings

# anthropic is imported lazily inside _client_lazy(). The SDK + its
# pydantic models cost ~500ms to import on Vercel's cold-start —
# routes that never call the LLM (the inbox, /me, /jobs) should not
# pay that cost. Imported on first .generate() call instead.

logger = logging.getLogger(__name__)
settings = get_settings()

# Model selection per task type. Sonnet 4.6 for parsing + scoring
# (mechanical, cost-sensitive); Opus 4.7 for tailoring + outreach
# (creative, accuracy-sensitive).
MODELS = {
    "parsing": "claude-sonnet-4-6",
    "scoring": "claude-sonnet-4-6",
    "tailoring": "claude-opus-4-7",
}


class LLMClient:
    """Wrapper around Claude API with retry logic and cost tracking.

    The underlying anthropic.AsyncAnthropic client is built lazily on
    first use so importing this module is cheap. Saves ~500ms cold-start
    per Vercel function invocation that doesn't actually call the LLM.
    """

    def __init__(self):
        self._client = None
        self._anthropic_module = None

    def _client_lazy(self):
        if self._client is None:
            import anthropic
            self._anthropic_module = anthropic
            self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        return self._client

    @property
    def client(self):
        # Backwards-compat for any caller still touching .client directly.
        return self._client_lazy()

    @staticmethod
    def _accepts_temperature(model: str) -> bool:
        """Opus 4.7 deprecated the `temperature` parameter — passing it
        now returns 400 invalid_request_error. Sonnet 4.6 + Haiku still
        accept it. Centralise the check so callers don't need to know."""
        return "opus-4-7" not in model

    async def generate(
        self,
        task_type: str,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> str:
        """Generate a text response from Claude."""
        model = MODELS.get(task_type, MODELS["parsing"])

        kwargs: dict[str, Any] = dict(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        if self._accepts_temperature(model):
            kwargs["temperature"] = temperature

        try:
            response = await self.client.messages.create(**kwargs)

            usage = response.usage
            logger.info(
                "LLM call: task=%s model=%s input_tokens=%d output_tokens=%d",
                task_type, model, usage.input_tokens, usage.output_tokens,
            )

            return response.content[0].text

        except Exception as e:
            # `anthropic` is imported lazily, so we can't catch its exception
            # types directly at the top level. Use the cached module reference
            # to distinguish rate limits from generic API errors for logging.
            anthropic = self._anthropic_module
            if anthropic is not None and isinstance(e, anthropic.RateLimitError):
                logger.warning("Rate limited on %s, will retry", task_type)
            elif anthropic is not None and isinstance(e, anthropic.APIError):
                logger.error("Claude API error: %s", e)
            else:
                logger.error("Unexpected LLM error: %s", e)
            raise

    async def generate_structured(
        self,
        task_type: str,
        system_prompt: str,
        user_prompt: str,
        tools: list[dict[str, Any]],
        max_tokens: int = 4096,
    ) -> dict:
        """Generate structured output using Claude's tool use."""
        model = MODELS.get(task_type, MODELS["parsing"])

        kwargs: dict[str, Any] = dict(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            tools=tools,
            tool_choice={"type": "auto"},
        )
        if self._accepts_temperature(model):
            kwargs["temperature"] = 0.0

        response = await self.client.messages.create(**kwargs)

        usage = response.usage
        logger.info(
            "LLM structured call: task=%s model=%s input_tokens=%d output_tokens=%d",
            task_type, model, usage.input_tokens, usage.output_tokens,
        )

        for block in response.content:
            if block.type == "tool_use":
                return block.input

        return {"text": response.content[0].text}


# Singleton
llm_client = LLMClient()

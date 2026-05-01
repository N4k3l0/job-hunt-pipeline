import logging
from typing import Any

import anthropic

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Model selection per task type. The previous IDs (claude-*-4-20250514)
# were the May 2025 release wave — long since deprecated. Updated to the
# current Claude 4.X family (Opus 4.7 / Sonnet 4.6) per CLAUDE.md:
#   - Sonnet 4.6 for parsing + scoring (mechanical, cost-sensitive).
#   - Opus 4.7 for tailoring + outreach (creative, accuracy-sensitive).
MODELS = {
    "parsing": "claude-sonnet-4-6",
    "scoring": "claude-sonnet-4-6",
    "tailoring": "claude-opus-4-7",
}


class LLMClient:
    """Wrapper around Claude API with retry logic and cost tracking.

    Uses anthropic.AsyncAnthropic so each call yields the event loop —
    important inside the FastAPI request handler so tailoring's 3-5
    sequential LLM calls don't starve other coroutines (DB queries,
    progress callbacks) or hold the worker pool.
    """

    def __init__(self):
        self.client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

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

        try:
            response = await self.client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )

            usage = response.usage
            logger.info(
                "LLM call: task=%s model=%s input_tokens=%d output_tokens=%d",
                task_type, model, usage.input_tokens, usage.output_tokens,
            )

            return response.content[0].text

        except anthropic.RateLimitError:
            logger.warning("Rate limited on %s, will retry", task_type)
            raise
        except anthropic.APIError as e:
            logger.error("Claude API error: %s", e)
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

        response = await self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=0.0,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            tools=tools,
            tool_choice={"type": "auto"},
        )

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

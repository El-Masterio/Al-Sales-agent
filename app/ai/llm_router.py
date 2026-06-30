"""
app/ai/llm_router.py
====================
Unified LLM abstraction layer.

All AI services in this codebase call through LLMRouter rather than
talking to OpenAI/Anthropic/Gemini SDKs directly. This gives:
  - Single place to swap providers
  - Automatic fallback if the primary provider errors
  - Consistent token usage tracking for cost dashboards
  - Consistent retry/backoff behavior
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Literal

import structlog
from anthropic import AsyncAnthropic, APIError as AnthropicAPIError
from openai import AsyncOpenAI, APIError as OpenAIAPIError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import settings

logger = structlog.get_logger(__name__)

Provider = Literal["openai", "anthropic", "google"]


@dataclass
class LLMResponse:
    text: str
    model: str
    provider: Provider
    prompt_tokens: int
    completion_tokens: int
    generation_ms: int
    raw: Any = None


class LLMRouter:
    """
    Routes completion requests to the configured primary provider,
    falling back to the secondary provider on failure.

    Usage:
        router = LLMRouter()
        response = await router.complete(
            system="You are a sales research assistant.",
            user="Summarize this company's tech stack: ...",
            temperature=0.2,
        )
    """

    def __init__(self) -> None:
        self._openai: AsyncOpenAI | None = None
        self._anthropic: AsyncAnthropic | None = None
        self._gemini_configured = False

    # ── Lazy client init ──────────────────────────────────────────────────────

    @property
    def openai_client(self) -> AsyncOpenAI:
        if self._openai is None:
            self._openai = AsyncOpenAI(
                api_key=settings.OPENAI_API_KEY,
                organization=settings.OPENAI_ORG_ID,
                timeout=settings.OPENAI_TIMEOUT,
                max_retries=0,  # we handle retries ourselves via tenacity
            )
        return self._openai

    @property
    def anthropic_client(self) -> AsyncAnthropic:
        if self._anthropic is None:
            if not settings.ANTHROPIC_API_KEY:
                raise RuntimeError("ANTHROPIC_API_KEY not configured")
            self._anthropic = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        return self._anthropic

    def _ensure_gemini(self) -> None:
        if not self._gemini_configured:
            if not settings.GOOGLE_AI_API_KEY:
                raise RuntimeError("GOOGLE_AI_API_KEY not configured")
            import google.generativeai as genai

            genai.configure(api_key=settings.GOOGLE_AI_API_KEY)
            self._gemini_configured = True

    # ── Public API ────────────────────────────────────────────────────────────

    async def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        model: str | None = None,
        provider: Provider | None = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        """
        Generate a completion, trying the primary provider first and falling
        back to the secondary provider on failure.
        """
        primary = provider or settings.LLM_PRIMARY_PROVIDER
        fallback = settings.LLM_FALLBACK_PROVIDER if primary != settings.LLM_FALLBACK_PROVIDER else None

        try:
            return await self._dispatch(
                primary, system, user,
                temperature=temperature, max_tokens=max_tokens,
                model=model, json_mode=json_mode,
            )
        except Exception as exc:
            logger.warning(
                "llm_primary_provider_failed",
                provider=primary, error=str(exc),
            )
            if fallback is None:
                raise
            try:
                return await self._dispatch(
                    fallback, system, user,
                    temperature=temperature, max_tokens=max_tokens,
                    model=None, json_mode=json_mode,
                )
            except Exception as fallback_exc:
                logger.error(
                    "llm_fallback_provider_failed",
                    provider=fallback, error=str(fallback_exc),
                )
                raise

    async def _dispatch(
        self,
        provider: Provider,
        system: str,
        user: str,
        *,
        temperature: float | None,
        max_tokens: int | None,
        model: str | None,
        json_mode: bool,
    ) -> LLMResponse:
        if provider == "openai":
            return await self._complete_openai(system, user, temperature, max_tokens, model, json_mode)
        if provider == "anthropic":
            return await self._complete_anthropic(system, user, temperature, max_tokens, model)
        if provider == "google":
            return await self._complete_gemini(system, user, temperature, max_tokens, model)
        raise ValueError(f"Unknown provider: {provider}")

    # ── Provider implementations ──────────────────────────────────────────────

    @retry(
        retry=retry_if_exception_type(OpenAIAPIError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _complete_openai(
        self,
        system: str,
        user: str,
        temperature: float | None,
        max_tokens: int | None,
        model: str | None,
        json_mode: bool,
    ) -> LLMResponse:
        start = time.monotonic()
        kwargs: dict[str, Any] = {
            "model": model or settings.OPENAI_DEFAULT_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature if temperature is not None else settings.LLM_TEMPERATURE,
            "max_tokens": max_tokens or settings.OPENAI_MAX_TOKENS,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        response = await self.openai_client.chat.completions.create(**kwargs)
        elapsed_ms = int((time.monotonic() - start) * 1000)

        choice = response.choices[0]
        usage = response.usage

        return LLMResponse(
            text=choice.message.content or "",
            model=response.model,
            provider="openai",
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            generation_ms=elapsed_ms,
            raw=response,
        )

    @retry(
        retry=retry_if_exception_type(AnthropicAPIError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _complete_anthropic(
        self,
        system: str,
        user: str,
        temperature: float | None,
        max_tokens: int | None,
        model: str | None,
    ) -> LLMResponse:
        start = time.monotonic()
        response = await self.anthropic_client.messages.create(
            model=model or settings.ANTHROPIC_DEFAULT_MODEL,
            system=system,
            messages=[{"role": "user", "content": user}],
            temperature=temperature if temperature is not None else settings.LLM_TEMPERATURE,
            max_tokens=max_tokens or settings.ANTHROPIC_MAX_TOKENS,
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)

        text = "".join(block.text for block in response.content if hasattr(block, "text"))

        return LLMResponse(
            text=text,
            model=response.model,
            provider="anthropic",
            prompt_tokens=response.usage.input_tokens,
            completion_tokens=response.usage.output_tokens,
            generation_ms=elapsed_ms,
            raw=response,
        )

    async def _complete_gemini(
        self,
        system: str,
        user: str,
        temperature: float | None,
        max_tokens: int | None,
        model: str | None,
    ) -> LLMResponse:
        self._ensure_gemini()
        import google.generativeai as genai

        start = time.monotonic()
        gen_model = genai.GenerativeModel(
            model_name=model or settings.GEMINI_DEFAULT_MODEL,
            system_instruction=system,
        )
        response = await gen_model.generate_content_async(
            user,
            generation_config=genai.types.GenerationConfig(
                temperature=temperature if temperature is not None else settings.LLM_TEMPERATURE,
                max_output_tokens=max_tokens or 4096,
            ),
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)

        usage = getattr(response, "usage_metadata", None)
        prompt_tokens = getattr(usage, "prompt_token_count", 0) if usage else 0
        completion_tokens = getattr(usage, "candidates_token_count", 0) if usage else 0

        return LLMResponse(
            text=response.text,
            model=model or settings.GEMINI_DEFAULT_MODEL,
            provider="google",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            generation_ms=elapsed_ms,
            raw=response,
        )

    # ── Embeddings (OpenAI only — used for pgvector memory) ──────────────────

    async def embed(self, text_input: str) -> list[float]:
        response = await self.openai_client.embeddings.create(
            model=settings.OPENAI_EMBEDDING_MODEL,
            input=text_input,
        )
        return response.data[0].embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = await self.openai_client.embeddings.create(
            model=settings.OPENAI_EMBEDDING_MODEL,
            input=texts,
        )
        return [item.embedding for item in response.data]


# Module-level singleton
llm_router = LLMRouter()

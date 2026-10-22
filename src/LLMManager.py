from typing import Optional
import os
from langchain_anthropic import ChatAnthropic


class LLMManager:
    """Class for managing the Anthropic chat model."""

    def __init__(
        self,
        model_name: str = "claude-haiku-5-5",
        api_key: Optional[str] = None,
        max_tokens: int = 8000,
        effort: str = "low",
        fallback: Optional[bool] = None
    ):
        """Initialize the LLM client.

        Args:
            model_name: Model name to use
            api_key: Anthropic API key (uses ANTHROPIC_API_KEY if not set)
            max_tokens: Maximum tokens to generate (thinking included)
            effort: Reasoning effort: low, medium, high, xhigh or max.
                Current models reject custom temperature, effort replaces it.
            fallback: Server-side refusal fallback (if a safety classifier declines, Anthropic retries
                on another model). Default: on for Sonnet/Opus, which support it; off for Haiku.
        """
        self.model_name = model_name
        self.max_tokens = max_tokens
        self.effort = effort

        # Get and validate API key
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Anthropic API key not provided and ANTHROPIC_API_KEY environment variable not set"
            )

        if fallback is None:
            fallback = not self.model_name.startswith("claude-haiku")
        extra = {"betas": ["server-side-fallback-2026-07-01"], "model_kwargs": {"fallbacks": "default"}} if fallback else {}

        self.llm = ChatAnthropic(
            model=self.model_name,
            anthropic_api_key=self.api_key,
            max_tokens=self.max_tokens,
            effort=self.effort,
            **extra
        )

        print(f"Initialized ANTHROPIC with model: {self.model_name} (effort: {self.effort})")

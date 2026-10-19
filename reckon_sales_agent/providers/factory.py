from __future__ import annotations

from reckon_sales_agent.constants import DEFAULT_AI_MODEL
from reckon_sales_agent.providers.llm import ClaudeProvider


def get_llm(company: str):
    """The Claude provider when both the vendor and the Company enabled AI, else None."""
    from reckon_sales_agent.usage import get_settings, platform_settings

    platform = platform_settings()
    if not platform.ai_enabled or not get_settings(company).ai_enabled:
        return None
    key = platform.get_password("anthropic_api_key", raise_exception=False)
    if not key:
        return None
    return ClaudeProvider(key, model=platform.ai_model or DEFAULT_AI_MODEL, effort=platform.ai_effort or "medium")

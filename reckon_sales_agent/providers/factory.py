from __future__ import annotations

from reckon_sales_agent.constants import DEFAULT_AI_MODEL
from reckon_sales_agent.providers.llm import ClaudeProvider

AI_BLOCKED_KEY = "reckon_sales_agent:ai_blocked"


def ai_blocked() -> str | None:
    """Why AI is paused site-wide (a billing or key problem the provider reported), or None."""
    import frappe

    return frappe.cache.get_value(AI_BLOCKED_KEY)


def get_llm(company: str):
    """The Claude provider when both the vendor and the Company enabled AI, else None.

    Live: the account ran out of credits and every agent kept calling and failing each hour. While the provider
    reports a billing or key problem, AI is paused for an hour and the agents fall back to their rules.
    """
    from reckon_sales_agent.usage import get_settings, platform_settings

    if ai_blocked():
        return None
    platform = platform_settings()
    if not platform.ai_enabled or not get_settings(company).ai_enabled:
        return None
    key = platform.get_password("anthropic_api_key", raise_exception=False)
    if not key:
        return None
    return ClaudeProvider(key, model=platform.ai_model or DEFAULT_AI_MODEL, effort=platform.ai_effort or "medium")

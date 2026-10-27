"""Which AI the agents use: one platform default, optionally overridden per tenant Company.

Providers: Anthropic (Claude), OpenAI, or a local / self-hosted model behind an OpenAI-compatible API
(Ollama, LM Studio, vLLM). The vendor sets the default in Sales Agent Platform Settings and decides whether
Companies may override it (and, separately, whether they may point at their own endpoint, since a URL a
tenant chooses is reached from the shared server). A Company's override (provider, model, key, endpoint) is
in its Sales Agent Settings. ``choose_ai`` is pure.
"""

from __future__ import annotations

from reckon_sales_agent.constants import DEFAULT_AI_MODEL
from reckon_sales_agent.providers.llm import ClaudeProvider, OpenAICompatibleProvider

PROVIDERS = {"Anthropic (Claude)": "anthropic", "OpenAI": "openai", "Local (OpenAI-compatible)": "local"}
LABELS = {kind: label for label, kind in PROVIDERS.items()}
AI_BLOCKED_KEY = "reckon_sales_agent:ai_blocked"


def choose_ai(platform: dict, company: dict) -> dict:
    """The AI setup for a Company: {kind, model, base_url, key_from ("platform"|"company"), scope, source, error}.

    ``platform``/``company`` are the settings as dicts; key values are not needed (only whether one is set).
    """
    kind = PROVIDERS.get(platform.get("ai_provider") or "", "anthropic")
    source = "platform"
    override = PROVIDERS.get(company.get("ai_provider_override") or "")
    if override and platform.get("allow_company_ai_override"):
        kind, source = override, "company"
    defaults = {"anthropic": platform.get("ai_model") or DEFAULT_AI_MODEL,
                "openai": platform.get("openai_model") or "",
                "local": platform.get("local_ai_model") or ""}
    model = (company.get("ai_model_override") if source == "company" else None) or defaults[kind]
    base_url = {"anthropic": None, "openai": platform.get("openai_base_url") or "https://api.openai.com/v1",
                "local": platform.get("local_ai_base_url") or ""}[kind]
    error = ""
    if source == "company" and company.get("ai_base_url_override") and kind != "anthropic":
        if not platform.get("allow_company_ai_endpoints"):
            error = "Your provider does not allow Companies to use their own AI endpoint."
        elif not str(company["ai_base_url_override"]).startswith("https://"):
            error = "A Company's own AI endpoint must use HTTPS."
        else:
            base_url = company["ai_base_url_override"]
    key_from = "company" if source == "company" and company.get("has_api_key_override") else "platform"
    if not model:
        error = error or f"No model is set for {LABELS[kind]}."
    if kind == "local" and not base_url:
        error = error or "No address is set for the local AI server."
    custom_endpoint = bool(source == "company" and company.get("ai_base_url_override")
                           and base_url == company.get("ai_base_url_override"))
    # The Company's own key or endpoint is its own account: a billing problem there pauses only that Company.
    scope = f"company:{company.get('company')}" if key_from == "company" or custom_endpoint else f"platform:{kind}"
    return {"kind": kind, "label": LABELS[kind], "model": model, "base_url": base_url, "key_from": key_from,
            "scope": scope, "source": source, "custom_endpoint": custom_endpoint, "error": error}


def blocked_key(scope: str) -> str:
    return f"{AI_BLOCKED_KEY}:{scope}"


def _settings(company: str) -> tuple[dict, dict, object, object]:
    from reckon_sales_agent.usage import get_settings, platform_settings

    platform = platform_settings()
    settings = get_settings(company)
    company_view = {**settings.as_dict(), "company": company,
                    "has_api_key_override": bool(settings.get_password("ai_api_key_override", raise_exception=False))
                    if settings.get("ai_api_key_override") else False}
    return platform.as_dict(), company_view, platform, settings


def ai_setup(company: str) -> dict:
    platform_dict, company_dict, _platform, _settings_doc = _settings(company)
    return choose_ai(platform_dict, company_dict)


def ai_blocked(company: str | None = None) -> str | None:
    """Why this Company's AI account is paused (a billing or key problem the provider reported), or None."""
    import frappe

    if not company:
        return frappe.cache.get_value(blocked_key("platform:anthropic"))
    return frappe.cache.get_value(blocked_key(ai_setup(company)["scope"]))


def get_llm(company: str):
    """The AI provider for this Company when the vendor and the Company enabled AI, else None.

    Live: the account ran out of credits and every agent kept calling and failing each hour. While the provider
    reports a billing or key problem, that account is paused for an hour and the agents fall back to rules.
    """
    import frappe

    platform_dict, company_dict, platform, settings = _settings(company)
    if not platform.ai_enabled or not settings.ai_enabled:
        return None
    setup = choose_ai(platform_dict, company_dict)
    if setup["error"] or frappe.cache.get_value(blocked_key(setup["scope"])):
        return None
    if setup["key_from"] == "company":
        key = settings.get_password("ai_api_key_override", raise_exception=False)
    else:
        key = platform.get_password({"anthropic": "anthropic_api_key", "openai": "openai_api_key",
                                     "local": "local_ai_api_key"}[setup["kind"]], raise_exception=False)
    if setup["kind"] == "anthropic":
        if not key:
            return None
        return ClaudeProvider(key, model=setup["model"], effort=platform.ai_effort or "medium", scope=setup["scope"])
    if setup["kind"] == "openai" and not key:
        return None
    if setup["custom_endpoint"]:
        from reckon_sales_agent.research.url_safety import UnsafeURL, validate_url

        try:
            validate_url(setup["base_url"])  # a tenant's endpoint must be a public address, never the internal network
        except UnsafeURL:
            return None
    return OpenAICompatibleProvider(key, setup["model"], setup["base_url"], kind=setup["kind"], scope=setup["scope"])

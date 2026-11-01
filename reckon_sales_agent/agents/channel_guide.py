"""AI-guided setup help for each integration: what is done, what is missing, and how to do it.

Whether a step is done always comes from the settings themselves. The AI only explains the missing steps, and it
sees the names of the settings that are filled in or missing, never their values. Without AI (off, paused, or out
of credits) the same checklist is shown with plain instructions. Answers are cached for a few hours per Company
and setup state.

``rules_guide``, ``ai_guide`` and ``cache_key`` are pure.
"""

from __future__ import annotations

import hashlib
import json

FALLBACK_DETAIL = "Fill this in the panel, then press Save. The reference links below show where to find it."
CACHE_HOURS = 6

# Official help for each integration (checked to respond). The Integrations page shows these at the foot of a panel.
REFERENCES = {
    "whatsapp": [["frappe_whatsapp configuration", "https://shridarpatil.github.io/frappe_whatsapp/#configuration"],
                 ["WhatsApp Cloud API", "https://developers.facebook.com/docs/whatsapp/cloud-api/get-started"]],
    "facebook": [["Messenger platform", "https://developers.facebook.com/docs/messenger-platform/overview"],
                 ["Webhooks", "https://developers.facebook.com/docs/graph-api/webhooks"]],
    "instagram": [["Instagram platform", "https://developers.facebook.com/docs/instagram-platform"]],
    "meta_leads": [["Lead ads", "https://developers.facebook.com/docs/marketing-api/guides/lead-ads"]],
    "linkedin": [["LinkedIn developer docs", "https://learn.microsoft.com/en-us/linkedin/"]],
    "linkedin_leads": [["LinkedIn developer docs", "https://learn.microsoft.com/en-us/linkedin/"]],
    "twilio": [["Twilio docs", "https://www.twilio.com/docs"], ["Messaging services", "https://www.twilio.com/docs/messaging/services"]],
    "voice_ai": [["Twilio Voice", "https://www.twilio.com/docs/voice"]],
    "sms": [["Twilio SMS and RCS", "https://www.twilio.com/docs/sms"], ["BulkSMSBD", "https://www.bulksmsbd.net"],
            ["SSL Wireless", "https://sslwireless.com"]],
    "asterisk": [["Asterisk ARI", "https://docs.asterisk.org/Configuration/Interfaces/Asterisk-REST-Interface-ARI/"]],
    "email": [["Frappe documentation", "https://frappeframework.com/docs"]],
    "sendgrid": [["SendGrid docs", "https://www.twilio.com/docs/sendgrid"]],
    "ai": [["Anthropic docs", "https://docs.anthropic.com"], ["OpenAI docs", "https://platform.openai.com/docs"]],
    "platform_ai": [["Anthropic docs", "https://docs.anthropic.com"], ["OpenAI docs", "https://platform.openai.com/docs"],
                    ["Ollama", "https://github.com/ollama/ollama"], ["vLLM", "https://docs.vllm.ai"]],
    "platform_meta": [["Messenger platform", "https://developers.facebook.com/docs/messenger-platform/overview"],
                      ["Facebook Login", "https://developers.facebook.com/docs/facebook-login"],
                      ["App review", "https://developers.facebook.com/docs/app-review"],
                      ["Business verification", "https://www.facebook.com/business/help/2058515294227817"]],
    "platform_linkedin": [["LinkedIn developer docs", "https://learn.microsoft.com/en-us/linkedin/"]],
    "platform_transcription": [["Speech to text (OpenAI)", "https://platform.openai.com/docs/guides/speech-to-text"]],
    "platform_lead_sources": [["Brave Search API", "https://api-dashboard.search.brave.com/app/documentation"],
                              ["Google Places API", "https://developers.google.com/maps/documentation/places/web-service/overview"],
                              ["SerpAPI", "https://serpapi.com/search-api"], ["Apify", "https://docs.apify.com"],
                              ["Scrapingdog", "https://docs.scrapingdog.com"], ["ScrapingBee", "https://www.scrapingbee.com/documentation/"]],
    "platform_social": [["Graph API", "https://developers.facebook.com/docs/graph-api"],
                        ["LinkedIn developer docs", "https://learn.microsoft.com/en-us/linkedin/"]],
    "platform_email_events": [["SendGrid event webhook", "https://www.twilio.com/docs/sendgrid"]],
}

# Vendor-only integrations (the system provider's settings).
PLATFORM_KEYS = frozenset(key for key in REFERENCES if key.startswith("platform_"))

SYSTEM = (
    "You are the setup assistant for Reckon Sales Agent. Explain, in plain English, how to finish the setup of one "
    "integration. You get the integration's name, the steps already done, and the steps still missing. For each missing "
    "step, say in one or two short sentences what to do and where (for example which page, which field, which key). "
    "Use only the facts given; never invent a URL, a price or a setting name that is not in the facts. Mention "
    "safety where it matters: keys stay secret, and sending stays in dry run until the go-live checklist says otherwise. "
    "items: one entry per missing step, with the step's exact text as 'item'. watch_out: up to three short warnings."
)
SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "items": {"type": "array", "items": {
            "type": "object",
            "properties": {"item": {"type": "string"}, "how": {"type": "string"}},
            "required": ["item", "how"], "additionalProperties": False}},
        "watch_out": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "items", "watch_out"],
    "additionalProperties": False,
}


def rules_guide(checks: list[tuple[str, bool]]) -> dict:
    """The checklist without AI: each step is done or not, with the same plain instruction for what is missing."""
    done = sum(1 for _, ok in checks if ok)
    steps = [{"title": label, "detail": "Done." if ok else FALLBACK_DETAIL, "done": bool(ok)} for label, ok in checks]
    summary = f"{done} of {len(checks)} steps done." if checks else "No setup steps for this integration."
    return {"source": "rules", "summary": summary, "steps": steps, "watch_out": []}


def ai_guide(checks: list[tuple[str, bool]], data: dict) -> dict:
    """The AI's explanation, joined to the real checklist: the AI never decides what is done."""
    how = {str(i.get("item")): str(i.get("how") or "") for i in data.get("items") or [] if isinstance(i, dict)}
    steps = []
    for label, ok in checks:
        detail = "Done." if ok else (how.get(label) or FALLBACK_DETAIL)
        steps.append({"title": label[:160], "detail": detail[:400], "done": bool(ok)})
    return {
        "source": "ai",
        "summary": str(data.get("summary") or "")[:300],
        "steps": steps[:12],
        "watch_out": [str(w)[:240] for w in data.get("watch_out") or []][:3],
    }


def cache_key(company: str, key: str, checks: list[tuple[str, bool]]) -> str:
    digest = hashlib.sha256(json.dumps(checks).encode()).hexdigest()[:16]
    return f"reckon_sales_agent:guide:{company}:{key}:{digest}"


# --------------------------------------------------------------------------- Frappe side


def checks_for(company: str, key: str) -> list[tuple[str, bool]]:
    """(step, done) for an integration, read from the Company's and the platform's settings. Values are never returned."""
    import frappe

    from reckon_sales_agent.usage import get_settings, platform_settings

    settings = get_settings(company)
    platform = platform_settings()

    def setting(doc, field):
        return bool(doc.get(field))

    def accounts(platform_name):
        return bool(frappe.db.exists("Sales Social Account", {"company": company, "platform": platform_name, "enabled": 1}))

    email = bool(frappe.db.exists("Email Account", {"enable_outgoing": 1, "default_outgoing": 1}))
    table = {
        "whatsapp": [("Turn WhatsApp on", setting(settings, "whatsapp_enabled")),
                     ("Choose the WhatsApp account", setting(settings, "whatsapp_account"))],
        "twilio": [("Account SID", setting(settings, "twilio_account_sid")),
                   ("Auth token", setting(settings, "twilio_auth_token")),
                   ("Twilio phone number", setting(settings, "twilio_phone_number"))],
        "voice_ai": [("Turn the voice assistant on", setting(settings, "voice_ai_enabled")),
                     ("A phone to connect callers to", setting(settings, "voice_forward_to"))],
        "sms": [("Turn SMS on", setting(settings, "sms_enabled")),
                ("API key or token", setting(settings, "sms_api_key") or settings.get("sms_provider") == "Platform gateway"),
                ("Sender ID", setting(settings, "sms_sender_id") or settings.get("sms_provider") == "Platform gateway")],
        "asterisk": [("ARI address (HTTPS)", setting(settings, "ari_url")),
                     ("ARI user", setting(settings, "ari_username")),
                     ("ARI password", setting(settings, "ari_password")),
                     ("Caller ID", setting(settings, "sip_caller_id"))],
        "email": [("A default outgoing email account", email)],
        "sendgrid": [("SendGrid API key", setting(settings, "sendgrid_api_key")),
                     ("Verified from address", setting(settings, "sendgrid_from_email")),
                     ("Signed event webhook key", setting(settings, "sendgrid_webhook_key"))],
        "facebook": [("Connect your Facebook Page", accounts("Facebook Page"))],
        "instagram": [("Connect your Instagram account", accounts("Instagram"))],
        "meta_leads": [("Connect a Page for lead ads", accounts("Facebook Page"))],
        "linkedin": [("Connect your LinkedIn page", accounts("LinkedIn"))],
        "linkedin_leads": [("Connect your lead forms", accounts("LinkedIn Lead Gen"))],
        "webchat": [("Show the chat on your website", setting(settings, "webchat_enabled")),
                    ("Your website addresses", setting(settings, "webchat_allowed_origins"))],
        "ai": [("AI turned on for this Company", bool(platform.get("ai_enabled") and settings.get("ai_enabled")))],
        "platform_ai": [("Turn AI on", setting(platform, "ai_enabled")),
                        ("A key for Anthropic, OpenAI or a local server",
                         setting(platform, "anthropic_api_key") or setting(platform, "openai_api_key")
                         or setting(platform, "local_ai_base_url"))],
        "platform_meta": [("App ID", setting(platform, "meta_app_id")), ("App secret", setting(platform, "meta_app_secret")),
                          ("Webhook verify token", setting(platform, "meta_verify_token"))],
        "platform_linkedin": [("Client ID", setting(platform, "linkedin_client_id")),
                              ("Client secret", setting(platform, "linkedin_client_secret"))],
        "platform_transcription": [("Turn transcription on", setting(platform, "transcription_enabled"))],
        "platform_lead_sources": [("Turn Brave Search on", setting(platform, "brave_enabled")),
                                  ("Brave API key", setting(platform, "brave_api_key"))],
        "platform_social": [("Turn publishing on", setting(platform, "social_enabled"))],
        "platform_email_events": [("Signing secret", setting(platform, "email_webhook_secret"))],
    }
    return table.get(key, [])


def build_guide(company: str, key: str, refresh: bool = False) -> dict:
    import frappe

    from reckon_sales_agent.constants import USAGE_AI
    from reckon_sales_agent.providers.factory import get_llm
    from reckon_sales_agent.providers.llm import LLMError, untrusted
    from reckon_sales_agent.usage import remaining, reserve

    checks = checks_for(company, key)
    references = REFERENCES.get(key, [])
    cache = cache_key(company, key, checks)
    if not refresh:
        cached = frappe.cache.get_value(cache)
        if cached:
            return cached
    result = None
    if checks and not all(ok for _, ok in checks):
        llm = get_llm(company)
        if llm and remaining(company, USAGE_AI) > 0:
            facts = {"integration": key.replace("_", " "),
                     "done": [label for label, ok in checks if ok],
                     "missing": [label for label, ok in checks if not ok],
                     "reference_links": [label for label, _url in references]}
            try:
                reserve(company, USAGE_AI, 1, None)
                data = llm.complete_json(SYSTEM, untrusted("setup facts (names only, never values)", json.dumps(facts)),
                                         SCHEMA, max_tokens=900)
                result = ai_guide(checks, data)
            except LLMError:
                result = None
    if result is None:
        result = rules_guide(checks)
    result["references"] = references
    frappe.cache.set_value(cache, result, expires_in_sec=CACHE_HOURS * 3600)
    return result

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

# Quick help: a short plain explanation and the steps for each integration. It shows at once, with no AI call.
QUICK_HELP = {
    "autopilot": {"what": "The agents work the pipeline for you: they find, research, draft and follow up, and ask you before anything risky.",
                  "steps": ["Turn on the agents you want in Agent Studio.", "Set the approval rules so you see each message before it is sent.",
                            "Check Conversations each day; the waiting count shows what needs a person."]},
    "ai": {"what": "The AI writes drafts, scores leads and explains setup. It runs on the provider your system provider chose.",
           "steps": ["Ask your system provider to turn AI on for the platform.", "Optional: pick your own AI provider for this Company in Sales Agent Settings."]},
    "webchat": {"what": "A chat box on your website. Visitors who write in appear in Conversations.",
                "steps": ["Turn the chat on and give it a title and a welcome line.", "Add the website addresses that may show it.",
                          "Paste the snippet shown in the panel into your website, then test it."]},
    "whatsapp": {"what": "WhatsApp Business messages through the frappe_whatsapp app. Each Company uses its own WhatsApp account.",
                 "steps": ["Set up a WhatsApp Account in the frappe_whatsapp app with your Meta token and phone number ID.",
                           "Point the Meta webhook at the address shown here, subscribed to messages.",
                           "Choose that account here and turn WhatsApp on.",
                           "Send a test message. After 24 hours you can only reply with an approved template."]},
    "facebook": {"what": "Messenger chats with people who write to your Facebook Page.",
                 "steps": ["Your system provider sets up the Meta app first.", "Press Connect and choose the Page you manage.",
                           "Send a test message from the Page to confirm it reaches Conversations."]},
    "instagram": {"what": "Instagram direct messages from your business account.",
                  "steps": ["The Instagram account must be a professional account linked to a Facebook Page.",
                            "Press Connect and approve the Instagram account.", "Send a test direct message to confirm it arrives."]},
    "linkedin": {"what": "Publish approved posts to a LinkedIn company page you administer.",
                 "steps": ["Your system provider sets up the LinkedIn app first.", "Press Connect and choose the company page.",
                           "Approve a post in the content queue and press Test."]},
    "meta_leads": {"what": "New leads from Facebook lead ads go straight into Reckon as prospects.",
                   "steps": ["Connect the Facebook Page that runs the lead forms.", "Check that the Meta app has the leads permission.",
                             "Submit a test lead with Meta's Lead Ads Testing Tool."]},
    "linkedin_leads": {"what": "New leads from LinkedIn Lead Gen Forms.",
                       "steps": ["Your LinkedIn app needs access to Lead Gen Forms.", "Connect the company page that owns the forms.",
                                 "Submit a test response to confirm the lead arrives."]},
    "twilio": {"what": "Phone calls and SMS through Twilio, including RCS where it is available.",
               "steps": ["Enter the Account SID, Auth token and your Twilio number.",
                         "In the Twilio console, point the number's messaging and voice webhooks at the addresses shown.",
                         "Send a test SMS to your own phone."]},
    "voice_ai": {"what": "An AI assistant that answers calls and passes the caller to a person when needed.",
                 "steps": ["Turn the voice assistant on.", "Enter the phone number where live callers should be connected.",
                           "Call the Twilio number to test it."]},
    "sms": {"what": "Bulk and single SMS through the gateway you choose.",
            "steps": ["Pick a gateway and enter its key and sender ID.", "Keep it in dry run until the go-live checklist is complete.",
                      "Send one test SMS to your own number."]},
    "asterisk": {"what": "Calls through your own Asterisk server, using its ARI interface.",
                 "steps": ["Enter the ARI address. It must be HTTPS.", "Enter the ARI user and password.", "Set the caller ID and place a test call."]},
    "email": {"what": "Sending from your own mailbox through a Frappe email account.",
              "steps": ["Create an outgoing Email Account in Frappe.", "Mark it as the default outgoing account.", "Send a test email to yourself."]},
    "sendgrid": {"what": "Bulk email through SendGrid, with delivery and bounce events sent back to Reckon.",
                 "steps": ["Paste the SendGrid API key.", "Use a sender address verified in SendGrid.",
                           "Paste the signed event webhook key and point SendGrid's event webhook at the address shown."]},
    "platform_ai": {"what": "The AI provider for the whole system: Claude, OpenAI, or a local model.",
                    "steps": ["Turn AI on.", "Enter a key for Anthropic or OpenAI, or the address of your local server.",
                              "Set the monthly AI limit and whether Companies may use their own key."]},
    "platform_meta": {"what": "The Meta app that Facebook, Instagram and Meta lead ads connect through.",
                      "steps": ["Create the app at developers.facebook.com and copy its App ID and secret.",
                                "Choose a verify token and enter it here.", "Complete app review and business verification before going live."]},
    "platform_linkedin": {"what": "The LinkedIn app used for company page publishing and lead forms.",
                          "steps": ["Create the app in the LinkedIn developer portal.", "Enter the client ID and secret.",
                                    "Request the products you need and wait for approval."]},
    "platform_transcription": {"what": "Turns call recordings into text for the call notes.",
                               "steps": ["Turn transcription on.", "Enter the speech-to-text key."]},
    "platform_lead_sources": {"what": "Finds new companies to research, from search and maps providers.",
                              "steps": ["Turn on the sources you have keys for.", "Enter each key and check it with Test.",
                                        "Keep to each provider's terms of use."]},
    "platform_social": {"what": "Publishing and social research for the whole platform.",
                        "steps": ["Turn publishing on.", "Check the Meta and LinkedIn connections first."]},
    "platform_email_events": {"what": "Receives SendGrid delivery events for every Company.",
                              "steps": ["Create a long random signing secret and enter it here.",
                                        "Use the same secret in the SendGrid event webhook settings."]},
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

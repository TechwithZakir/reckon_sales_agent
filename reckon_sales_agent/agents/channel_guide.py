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
                      ["WhatsApp Embedded Signup", "https://developers.facebook.com/docs/whatsapp/embedded-signup/"],
                      ["Facebook Login", "https://developers.facebook.com/docs/facebook-login"],
                      ["App review", "https://developers.facebook.com/docs/app-review"],
                      ["Business verification", "https://www.facebook.com/business/help/2058515294227817"]],
    "platform_linkedin": [["LinkedIn developer docs", "https://learn.microsoft.com/en-us/linkedin/"]],
    "platform_transcription": [["Speech to text (OpenAI)", "https://platform.openai.com/docs/guides/speech-to-text"]],
    "platform_openai": [["OpenAI docs", "https://platform.openai.com/docs"], ["API keys", "https://platform.openai.com/api-keys"]],
    "platform_local_ai": [["Ollama", "https://github.com/ollama/ollama"], ["vLLM", "https://docs.vllm.ai"]],
    "platform_places": [["Places API overview", "https://developers.google.com/maps/documentation/places/web-service/overview"],
                        ["Google Maps Platform terms", "https://cloud.google.com/maps-platform/terms"]],
    "platform_serpapi": [["SerpAPI docs", "https://serpapi.com/search-api"]],
    "platform_apify": [["Apify docs", "https://docs.apify.com"]],
    "platform_scrapingdog": [["Scrapingdog docs", "https://docs.scrapingdog.com"]],
    "platform_scrapingbee": [["ScrapingBee docs", "https://www.scrapingbee.com/documentation/"]],
    "platform_brave": [["Brave Search API", "https://api-dashboard.search.brave.com/app/documentation"]],
    "platform_search": [["Google terms", "https://developers.google.com/terms"]],
    "platform_routing": [],
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
    "platform_openai": {"what": "OpenAI models for every customer that uses OpenAI.",
                        "steps": ["Create an API key in the OpenAI dashboard and paste it here.", "Choose the model and, if needed, the API address."]},
    "platform_local_ai": {"what": "An OpenAI-compatible server you run yourself, such as Ollama or vLLM.",
                          "steps": ["Start the server and note its address, such as http://127.0.0.1:11434/v1.", "Enter the address and the model name.", "Enter a key only if the server needs one."]},
    "platform_places": {"what": "Finds businesses through Google Places.",
                        "steps": ["Create a Places API key in Google Cloud with billing and a spending limit.", "Read Google's terms, tick that they are reviewed, then turn Places on."]},
    "platform_serpapi": {"what": "Google Maps and Google Search results through SerpAPI.",
                         "steps": ["Copy the key from your SerpAPI dashboard.", "Turn it on for Google Maps, Google Search, or both."]},
    "platform_apify": {"what": "The Apify actor that scrapes Google Maps.",
                       "steps": ["Copy the API token from Apify under Settings, Integrations.", "Check the actor name, then turn Apify on."]},
    "platform_scrapingdog": {"what": "Google Maps and Google Search results through Scrapingdog.",
                             "steps": ["Copy the API key from your Scrapingdog dashboard.", "Turn it on for Google Maps, Google Search, or both."]},
    "platform_scrapingbee": {"what": "Google Maps and Google Search results through ScrapingBee.",
                             "steps": ["Copy the API key from your ScrapingBee dashboard.", "Turn it on for Google Maps, Google Search, or both."]},
    "platform_brave": {"what": "Web search, places and page context from Brave.",
                       "steps": ["Create an API key in the Brave Search API dashboard.", "Paste it here and turn Brave on. It is the default provider."]},
    "platform_search": {"what": "Terms, country and language for lead search on Google results.",
                        "steps": ["Read Google's terms and tick that you accept responsibility for the data.", "Set the country and language, then choose how long to keep the data."]},
    "platform_routing": {"what": "Which provider each lookup uses by default. Every other provider that is on joins Smart Sources.",
                         "steps": ["Choose the default places, page context and web search providers.", "Check the monthly budgets in Sales Agent Platform Settings."]},
    "platform_social": {"what": "Publishing and social research for the whole platform.",
                        "steps": ["Turn publishing on.", "Check the Meta and LinkedIn connections first."]},
    "platform_email_events": {"what": "Receives SendGrid delivery events for every Company.",
                              "steps": ["Create a long random signing secret and enter it here.",
                                        "Use the same secret in the SendGrid event webhook settings."]},
}

# Configuration details: what to fill in, for each integration. Shown under the steps in the quick help.
CONFIG = {
    "autopilot": [
        "Each agent has its own on/off switch in Agent Studio. Turn on only the ones you want.",
        "Approval rules decide which actions wait for you (sending, publishing, spending) and which run on their own.",
        "Keep new agents in dry run until you have reviewed a few of their drafts.",
    ],
    "ai": [
        "Provider: Claude, OpenAI or a local model, chosen by the system provider.",
        "Company override: if the system provider allows it, enter your own key in Sales Agent Settings. It is used for this Company only.",
        "Monthly AI limit: when it is used up, AI pauses until next month and the agents fall back to rule-based replies.",
        "Keys stay secret: after saving, a key is never shown again.",
    ],
    "webchat": [
        "Enable: turn the chat on in this panel.",
        "Title and welcome line: what visitors see when the chat opens.",
        "Allowed website addresses: only these sites may show the chat. Enter each one in full, for example https://www.yourcompany.com.",
        "Install: paste the snippet shown in this panel into your website, just before the closing body tag.",
    ],
    "whatsapp": [
        "WhatsApp Account: create it in the frappe_whatsapp app with the Meta access token, phone number ID, business account ID and app ID.",
        "Token: a permanent access token for this number, from Meta (a system-user token is best). It is not the Meta app secret.",
        "Webhook Verify Token: the same text as the Webhook verify token in Sales Agent Platform Settings. Get it from Integrations, System provider, Meta app, Make a new verify token.",
        "Webhook: in Meta, open WhatsApp, Configuration. Paste the callback URL shown above and the same verify token, then subscribe to messages and message_template_status_update.",
        "Company link: choose the WhatsApp Account here. One account belongs to one Company.",
        "One-click connection: Connect WhatsApp with Facebook signs the customer in and connects their number. It needs the system provider's Embedded Signup configuration ID (in Sales Agent Platform Settings).",
        "Templates: a message sent more than 24 hours after the customer's last message needs an approved template. Submit templates from Message Templates.",
    ],
    "facebook": [
        "Connect: the Connect button opens Facebook sign-in. Grant access to the Page's messages.",
        "Page: it must be a Page you manage, and the Meta app must be in live mode.",
        "Permission: pages_messaging must be approved for the Meta app.",
        "Test: message the Page from another account and check that it appears in Conversations.",
    ],
    "instagram": [
        "Account type: a professional (business or creator) Instagram account.",
        "Link: the Instagram account must be connected to a Facebook Page you manage.",
        "Permission: instagram_manage_messages must be approved for the Meta app.",
        "Enable: turn the account on in the list so it can receive messages.",
    ],
    "linkedin": [
        "Connect: sign in with LinkedIn and choose the company page you administer.",
        "Permission: posting needs the LinkedIn products for page posting to be approved for the app.",
        "Enable: turn the page on in the list. Posts go out only after you approve them.",
        "Test: the Test button checks the connection without posting anything.",
    ],
    "meta_leads": [
        "Page: the Facebook Page that owns the lead forms.",
        "Permission: leads_retrieval must be approved for the Meta app.",
        "Webhook: the system provider sets the verify token. The Meta app must subscribe to the leadgen field.",
        "Check: submit a test lead and confirm it appears among the prospects, with name, email and phone filled in.",
    ],
    "linkedin_leads": [
        "Forms: the Lead Gen Forms must belong to a company page you administer.",
        "Permission: Lead Gen Forms access must be approved for the LinkedIn app.",
        "Connect: choose the company page in the list and turn it on.",
        "Test: submit a test response on a draft form and confirm the prospect appears.",
    ],
    "twilio": [
        "Account SID and Auth token: from the Twilio console home page. The Auth token is hidden after saving.",
        "Phone number: a Twilio number in international format, for example +14155550123.",
        "Webhooks: in the Twilio console, set the number's messaging and voice webhook addresses to the ones shown here, using HTTP POST.",
        "RCS: needs a Messaging Service and a sender registered in Twilio.",
    ],
    "voice_ai": [
        "Enable: the assistant answers when your Twilio number receives a call.",
        "Forward to: the phone number, in international format, that takes over when the caller asks for a person.",
        "Recording: check your local rules before recording any call.",
        "Test: call the Twilio number from your own phone and ask for a person.",
    ],
    "sms": [
        "Enable: turns SMS sending on for this Company.",
        "Gateway: Twilio, BulkSMSBD, SSL Wireless, or the platform gateway (no key needed).",
        "API key or token: copy it from your gateway's dashboard. It is hidden after saving.",
        "Sender ID: the name or number recipients see. Some gateways need it approved first.",
        "Dry run: keep it on until you have checked the message text and the recipients.",
    ],
    "asterisk": [
        "ARI address: the HTTPS address of your Asterisk REST interface, for example https://pbx.example.com:8089.",
        "ARI user and password: defined in Asterisk's ari.conf with the rights to start calls.",
        "Caller ID: the number people see when you call. Your SIP trunk must allow it.",
        "Network: the Asterisk server must be reachable from Reckon over HTTPS.",
    ],
    "email": [
        "Email Account: create it in Frappe with your SMTP server, port and login.",
        "Default outgoing: tick Default Outgoing on that account. Bulk email is sent from it.",
        "Sender domain: set SPF and DKIM for your domain so mail is not marked as spam.",
        "Test: send one email to yourself before any bulk send.",
    ],
    "sendgrid": [
        "API key: create it in SendGrid with Mail Send permission. SendGrid shows it only once, so copy it then.",
        "Verified sender: the From address must be verified in SendGrid, as a single sender or through domain authentication.",
        "Signed event webhook: enable it in SendGrid, copy the verification key into the field here, and point the webhook at the address shown.",
        "Events: enable delivered, opened, clicked, bounced and unsubscribed so the timeline is complete.",
    ],
    "platform_ai": [
        "Provider: choose Claude, OpenAI or a local server. Each needs its own key or address.",
        "Local server: the base address of an OpenAI-compatible server, such as Ollama or vLLM.",
        "Monthly limits: they stop AI usage per Company before the cost grows.",
        "Company override: tick to let Companies use their own AI key.",
    ],
    "platform_meta": [
        "App ID and App secret: from the Meta app's Settings, Basic page. Keep the secret private.",
        "Verify token: any random string you choose. Enter the same value in the Meta webhook setup.",
        "Products: add Messenger, Instagram and Webhooks to the app.",
        "Review: app review and business verification must be complete before other businesses can connect.",
        "WhatsApp: get Meta's approval for your app as a Tech Provider, then create an Embedded Signup configuration in the Meta app.",
        "Enter the configuration ID in Sales Agent Platform Settings, in the Meta app section. Without it, the Connect WhatsApp button says it is not set up yet.",
    ],
    "platform_linkedin": [
        "Client ID and client secret: from the Auth tab of the LinkedIn app.",
        "Redirect URL: add the callback address shown here to the app's authorized redirect URLs.",
        "Products: request the products for page posting and lead forms. Approval can take days.",
    ],
    "platform_transcription": [
        "Enable transcription, then enter the speech-to-text key.",
        "Transcripts are attached to the call in Conversations. Check your consent rules before recording.",
    ],
    "platform_openai": [
        "API key: copied from the OpenAI dashboard. It is hidden after saving.",
        "Model: the model name used for drafts and replies.",
        "API address: only change it if you use a proxy.",
    ],
    "platform_local_ai": [
        "Server address: must answer OpenAI-compatible requests, for example at /v1.",
        "Model: the name the server gives the model.",
        "Key: only if the server is protected.",
    ],
    "platform_places": [
        "API key: a Places API key from Google Cloud. Set a billing limit first.",
        "Terms reviewed: tick only after your team has read Google's terms.",
        "Retention: how many days Places data is kept.",
        "Google Maps data: accept responsibility for the Maps data rules before any Maps provider runs.",
    ],
    "platform_serpapi": [
        "API key: from the SerpAPI dashboard.",
        "Maps and Search: each has its own switch, so you can use SerpAPI for one or both.",
    ],
    "platform_apify": [
        "API token: from Apify under Settings, Integrations.",
        "Actor: the Apify actor that performs the Google Maps scrape.",
    ],
    "platform_scrapingdog": [
        "API key: from the Scrapingdog dashboard.",
        "Maps and Search: each has its own switch.",
    ],
    "platform_scrapingbee": [
        "API key: from the ScrapingBee dashboard.",
        "Maps and Search: each has its own switch.",
    ],
    "platform_brave": [
        "API key: from the Brave Search API dashboard.",
        "Country: optional two-letter country code, such as BD.",
    ],
    "platform_search": [
        "Terms accepted: needed before any Google Search provider runs.",
        "Country and language: Google's gl and hl settings.",
        "Retention: how many days Search data is kept.",
    ],
    "platform_routing": [
        "Places, page context and web search: one default provider each.",
        "Budgets: set monthly limits per provider in Sales Agent Platform Settings.",
    ],
    "platform_social": [
        "Publishing: turn it on to allow approved posts to go out to connected pages.",
        "Connections: connect Meta and LinkedIn company by company first.",
        "Approval: posts wait for approval before they go out.",
    ],
    "platform_email_events": [
        "Signing secret: a long random string. Enter it here and in the SendGrid event webhook settings.",
        "Webhook address: point the SendGrid event webhook at the address shown here.",
        "Check: send a test email and confirm its delivered event appears in Reckon.",
    ],
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
                          ("Webhook verify token", setting(platform, "meta_verify_token")),
                          ("WhatsApp Embedded Signup configuration ID", setting(platform, "whatsapp_signup_config_id"))],
        "platform_linkedin": [("Client ID", setting(platform, "linkedin_client_id")),
                              ("Client secret", setting(platform, "linkedin_client_secret"))],
        "platform_transcription": [("Turn transcription on", setting(platform, "transcription_enabled"))],
        "platform_openai": [("OpenAI key", setting(platform, "openai_api_key"))],
        "platform_local_ai": [("Local server address", setting(platform, "local_ai_base_url"))],
        "platform_places": [("Turn Google Places on", setting(platform, "places_enabled")),
                            ("Google Places key", setting(platform, "google_places_api_key"))],
        "platform_serpapi": [("SerpAPI key", setting(platform, "serpapi_api_key"))],
        "platform_apify": [("Turn Apify on", setting(platform, "apify_enabled")),
                           ("Apify token", setting(platform, "apify_api_token"))],
        "platform_scrapingdog": [("Scrapingdog key", setting(platform, "scrapingdog_api_key"))],
        "platform_scrapingbee": [("ScrapingBee key", setting(platform, "scrapingbee_api_key"))],
        "platform_brave": [("Turn Brave Search on", setting(platform, "brave_enabled")),
                           ("Brave API key", setting(platform, "brave_api_key"))],
        "platform_search": [("Google Search terms accepted", setting(platform, "search_terms_ack"))],
        "platform_routing": [("Default places provider chosen", setting(platform, "default_places_provider"))],
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

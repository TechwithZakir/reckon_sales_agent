"""AI help for the template builder: a first draft from a brief, and rewrites of a piece of text.

The person gives a brief ("re-engage manufacturing leads who went quiet after a demo"), a goal and a tone. The model writes
only from the Company's approved knowledge and brand voice, using the merge fields with fallbacks, and returns plain
pieces (a subject, paragraphs, a button label) that are turned into builder content here. Nothing is saved or sent: the
person edits the draft, and a template still needs approval before it is used.

The ``*_content`` functions are pure, so how a model's answer becomes builder content is unit-tested without a model.
"""

from __future__ import annotations

import re

from reckon_sales_agent.campaigns.templates import FIELDS

TONES = ("Friendly", "Professional", "Direct", "Consultative")
GOALS = ("Book a meeting", "Re-engage", "Upsell", "Event invite")
CHANNELS = ("Email", "SMS", "WhatsApp", "LinkedIn")
BOOKING = "https://[BOOKING LINK]"

FIELD_LIST = "; ".join(f"{{{{{key}|{fallback}}}}}" if fallback else f"{{{{{key}}}}}" for _g, key, _l, _s, fallback, _n in FIELDS)
SYSTEM = (
    "You write one B2B message for a company selling in Bangladesh. Use ONLY facts in the approved knowledge: never invent "
    "prices, discounts, clients, numbers, results or guarantees. Personalise with these merge fields, written exactly like this "
    f"with their fallback after the bar: {FIELD_LIST}. Use {{{{first_name|there}}}} for a greeting, not a bare name. Do not add "
    "unsubscribe or opt-out text, and do not write links: they are added separately. One clear next step. Match the "
    "requested tone and language; for Bangla write natural Bangla as Bangladeshi business owners write it and keep product names "
    "in English. Rely on the brief and goal; if the brief names something the knowledge does not support, leave it out."
)
LENGTHS = {
    "Email": "Subject under 60 characters. A headline of at most 8 words, then 2 or 3 short paragraphs (at most 90 words in all), "
             "a button label of at most 5 words, and two other subject lines that try a different angle.",
    "SMS": "At most 220 characters. One idea and one next step.",
    "WhatsApp": "At most 50 words, friendly, no links, at most 3 merge fields (never first or last). Up to 3 short quick-reply "
                "button labels of at most 20 characters.",
    "LinkedIn": "A subject of at most 8 words and a message of at most 90 words, as one person writing to another.",
}
SCHEMAS = {
    "Email": {"type": "object", "properties": {
        "subject": {"type": "string"}, "preheader": {"type": "string"}, "variants": {"type": "array", "items": {"type": "string"}},
        "headline": {"type": "string"}, "paragraphs": {"type": "array", "items": {"type": "string"}},
        "button_label": {"type": "string"}}, "required": ["subject", "preheader", "variants", "headline", "paragraphs", "button_label"],
        "additionalProperties": False},
    "SMS": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"], "additionalProperties": False},
    "WhatsApp": {"type": "object", "properties": {"body": {"type": "string"}, "buttons": {"type": "array", "items": {"type": "string"}}},
                 "required": ["body", "buttons"], "additionalProperties": False},
    "LinkedIn": {"type": "object", "properties": {"subject": {"type": "string"}, "text": {"type": "string"}},
                 "required": ["subject", "text"], "additionalProperties": False},
}
EDIT_SCHEMA = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"], "additionalProperties": False}


def _clean(value, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _paragraphs(items) -> str:
    return "\n\n".join(_clean(p, 600) for p in (items or [])[:4] if _clean(p, 600))


def opt_out_line(language: str, keyword: str = "STOP") -> str:
    return f"বন্ধ করতে {keyword} লিখুন।" if language == "Bangla" else f"Reply {keyword} to opt out."


def email_content(data: dict) -> dict:
    """A model's email answer as builder content: headline, paragraphs, a button to fill, and the signature."""
    from reckon_sales_agent.campaigns import builder

    blocks = [{"type": "heading", "level": 2, "text": _clean(data.get("headline"), 120) or "Hi {{first_name|there}}"}]
    body = _paragraphs(data.get("paragraphs"))
    if body:
        blocks.append({"type": "text", "text": body})
    label = _clean(data.get("button_label"), 40)
    if label:
        blocks.append({"type": "button", "label": label, "url": BOOKING})
    blocks.append(builder.new_block("signature"))
    variants = [v for v in (_clean(v, 140) for v in (data.get("variants") or [])[:builder.MAX_VARIANTS + 1]) if v]
    return {"subject": _clean(data.get("subject"), 140), "preheader": _clean(data.get("preheader"), 140), "blocks": blocks,
            "variants": variants[:3]}


def sms_content(data: dict, language: str = "English", keyword: str = "STOP") -> dict:
    """The SMS text, with the opt-out line added when the model did not write one."""
    from reckon_sales_agent.campaigns import builder

    text = _clean(data.get("text"), 400)
    if not builder.OPT_OUT_RE.search(text) and keyword.lower() not in text.lower():
        text = f"{text} {opt_out_line(language, keyword)}".strip()
    return {"text": text, "keyword": keyword, "window": "09:00-21:00"}


def whatsapp_content(data: dict, language: str = "English") -> dict:
    """A WhatsApp draft that Meta's rules accept: it neither starts nor ends with a variable, and has an opt-out footer."""
    body = _clean(data.get("body"), 1000)
    if body.startswith("{{"):
        body = "Hi " + body
    if body.endswith("}}"):
        body += "."
    labels = [_clean(b, 25) for b in (data.get("buttons") or [])[:3] if _clean(b, 25)]
    footer = "বন্ধ করতে STOP লিখুন" if language == "Bangla" else "Reply STOP to unsubscribe"
    return {"header_type": "None", "header": "", "body": body, "footer": footer, "category": "Marketing",
            "buttons": [{"kind": "quick", "label": label} for label in labels], "samples": {}}


def linkedin_content(data: dict) -> dict:
    return {"subject": _clean(data.get("subject"), 150), "text": _clean(data.get("text"), 1800)}


def content_from(channel: str, data: dict, language: str = "English", keyword: str = "STOP") -> dict:
    if channel == "Email":
        return email_content(data)
    if channel == "SMS":
        return sms_content(data, language, keyword)
    if channel == "WhatsApp":
        return whatsapp_content(data, language)
    return linkedin_content(data)


# Frappe side -----------------------------------------------------------------


def _brand_context(company: str, language: str) -> str:
    from reckon_sales_agent.agents.content import knowledge_prompt
    from reckon_sales_agent.agents.content_agent import _brand, approved_knowledge
    from reckon_sales_agent.providers.llm import untrusted
    from reckon_sales_agent.research.market import business_profile

    voice, banned, _profile = _brand(company)
    profile = business_profile(company, create=False)
    seller = "\n".join(f"{f}: {profile.get(f)}" for f in ("business_name", "what_we_sell", "products") if profile and profile.get(f))
    return (untrusted("seller", seller or company) + "\n"
            + untrusted("approved knowledge", knowledge_prompt(approved_knowledge(company, language))) + "\n"
            + f"Brand voice: {voice}. Never use: {', '.join(banned) or 'n/a'}.")


def _ask(company: str, system: str, user: str, schema: dict, max_tokens: int = 2500) -> dict:
    import frappe
    from frappe import _

    from reckon_sales_agent.constants import USAGE_AI
    from reckon_sales_agent.providers.factory import get_llm
    from reckon_sales_agent.providers.llm import LLMError
    from reckon_sales_agent.usage import remaining, reserve

    llm = get_llm(company)
    if not llm:
        frappe.throw(_("Turn on AI in Sales Agent Settings to draft with AI."))
    if remaining(company, USAGE_AI) <= 0:
        frappe.throw(_("Monthly AI limit reached."))
    reserve(company, USAGE_AI, 1, None)
    frappe.db.commit()  # no open transaction while waiting on the model
    try:
        return llm.complete_json(system, user, schema, max_tokens=max_tokens)
    except LLMError as exc:
        frappe.throw(str(exc))


def draft(company: str, channel: str, brief: str, goal: str = "", tone: str = "Friendly", language: str = "English",
          keyword: str = "STOP") -> dict:
    """A first draft for one channel, as builder content."""
    import frappe
    from frappe import _

    from reckon_sales_agent.usage import log_activity

    if channel not in CHANNELS:
        frappe.throw(_("Choose Email, SMS, WhatsApp or LinkedIn."))
    tone = tone if tone in TONES else "Friendly"
    language = language if language in ("English", "Bangla") else "English"
    user = (f"{_brand_context(company, language)}\n\nChannel: {channel}\nLanguage: {language}\nTone: {tone}\n"
            f"Goal: {goal if goal in GOALS else 'Book a meeting'}\nLength: {LENGTHS[channel]}\n"
            f"Brief: {_clean(brief, 600) or 'A friendly first message to a business we want to work with.'}")
    data = _ask(company, SYSTEM, user, SCHEMAS[channel])
    log_activity(company, "content_template_drafted", None, f"{channel} draft, {tone} tone", actor_type="agent",
                 agent="Content", policy_outcome="draft only: a person edits and approves")
    return content_from(channel, data, language, keyword)


def rewrite(company: str, channel: str, text: str, instruction: str, language: str = "English") -> str:
    """One piece of text rewritten as asked ("make it shorter", "translate to Bangla"). Merge fields are kept."""
    import frappe
    from frappe import _

    text = (text or "").strip()
    if not text:
        frappe.throw(_("Write something first."))
    system = (SYSTEM + " You are editing text the person already wrote: follow their instruction, keep every merge field "
              "with its fallback exactly as written, add nothing the knowledge does not support, and return only the new text.")
    user = (f"{_brand_context(company, language)}\n\nChannel: {channel}\nInstruction: {_clean(instruction, 200)}\n"
            f"Text:\n{text[:3000]}")
    data = _ask(company, system, user, EDIT_SCHEMA, 1500)
    return re.sub(r"\n{3,}", "\n\n", str(data.get("text") or "").strip())[:3000]

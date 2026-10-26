"""Content agent rules: sequence plans, the AI writing brief, and fact / claim checks (pure: no Frappe imports).

Drafts may only state what the Company's approved knowledge says. The checks
here are deterministic and run on every campaign save, so an approver always
sees the issues: absolute or banned claims, figures that no approved item
contains, commercial terms (discounts, offers) without an approved Pricing or
Offer item, unknown merge fields and channel length limits. A campaign with
issues can still be approved, but only by a person who has seen them.
"""

from __future__ import annotations

import re

from reckon_sales_agent.campaigns.templates import PLACEHOLDER_RE, PLACEHOLDERS
from reckon_sales_agent.providers.llm import UNTRUSTED_RULES

CHANNELS = ("Email", "WhatsApp", "SMS", "Call Task")
SUBJECT_CHANNELS = ("Email", "Call Task")  # a call task's subject is the CRM task title
DEFAULT_BANNED = (
    "guaranteed", "guarantee", "100%", "risk-free", "risk free", "no.1", "no. 1", "number one", "best in bangladesh",
    "lowest price", "cheapest", "free forever", "act now", "once in a lifetime", "click here", "winner",
    "100% গ্যারান্টি", "সবচেয়ে কম দাম",
)
COMMERCIAL = re.compile(
    r"(discount|\d+\s*%\s*off|free trial|special offer|offer ends|limited[- ]time|promo(tion)? code|coupon|cashback"
    r"|ছাড়|ফ্রি ট্রায়াল|অফার)", re.I)
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
FIGURE = re.compile(
    r"(?:৳|tk\.?|bdt|usd|\$)\s?\d[\d,]*(?:\.\d+)?|\d[\d,]*(?:\.\d+)?\s?(?:%|৳|tk\b|taka|bdt|টাকা|percent|clients?|customers?"
    r"|distributors?|years?|outlets?)", re.I)
LIMITS = {"Email": 1500, "WhatsApp": 1000, "SMS": 459, "Call Task": 2500}  # characters of body text
SUBJECT_LIMIT = 80

SEQUENCE_SYSTEM = (
    "You write short B2B outreach sequences for a company selling in Bangladesh. Use ONLY facts from the approved "
    "knowledge provided: never invent prices, discounts, offers, client names, numbers, awards or guarantees. Use "
    "these placeholders exactly where they fit: {{business_name}}, {{city}}, {{industry}}, {{sender_name}}, "
    "{{offer}}; put {{personal_line}} on its own line near the start of the first message (it is an opening the "
    "agent writes from research on each business). Do not add unsubscribe or opt-out text; it is added "
    "automatically. Email: subject at most 60 characters, body at most 120 words. WhatsApp: at most 60 words, "
    "conversational, no subject. SMS: at most 300 characters, no subject. Call Task: a script for the seller's "
    "salesperson (never sent to the customer); subject names the goal, e.g. 'introduce our DMS to "
    "{{business_name}}'; body "
    "at most 180 words with: the opening line in English, then the same line in Bangla; {{personal_line}} as a "
    "talking point; two or three questions about how they take orders, manage stock and collect dues; {{offer}} "
    "as the next step; and a polite answer if they are not interested. Each lead only gets the steps its channels "
    "allow (a lead without email gets no email), so never refer to an earlier message, email or call ('I emailed "
    "you', 'as I mentioned'); each step must make sense on its own. Every message adds something new: a "
    "problem the seller solves for this segment, a proof point from the knowledge, or a low-effort next step such "
    "as a 15-minute call. Later messages are shorter. Write in the requested language; for Bangla, write natural "
    "Bangla as Bangladeshi business owners write it, keeping product names in English. " + UNTRUSTED_RULES
)
SEQUENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {"type": "array", "items": {
            "type": "object",
            "properties": {"step_no": {"type": "integer"}, "subject": {"type": "string"}, "body": {"type": "string"}},
            "required": ["step_no", "subject", "body"],
            "additionalProperties": False,
        }},
        "notes": {"type": "string"},
    },
    "required": ["steps", "notes"],
    "additionalProperties": False,
}
CLAIM_SYSTEM = (
    "You check B2B sales messages against the seller's approved knowledge. List every factual claim in the "
    "messages that the approved knowledge does not support (figures, client names, results, guarantees, prices, "
    "offers, product capabilities). Placeholders in double braces are filled in later and are not claims. "
    + UNTRUSTED_RULES
)
CLAIM_SCHEMA = {
    "type": "object",
    "properties": {"unsupported_claims": {"type": "array", "items": {"type": "string"}}},
    "required": ["unsupported_claims"],
    "additionalProperties": False,
}


def default_plan(steps: int, channels: list[str]) -> list[dict]:
    """Which channel each step uses and how long after the previous one: e.g. Email, WhatsApp 3 days later, Email."""
    usable = [c for c in channels if c in CHANNELS] or ["Email"]
    delays = [0, 3, 4, 7, 7]
    return [{"step_no": i + 1, "channel": usable[i % len(usable)], "delay_days": delays[min(i, len(delays) - 1)]}
            for i in range(max(1, min(int(steps or 3), 5)))]


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in NUMBER.findall(text or "")}


def check_step(step: dict, knowledge_text: str, pricing_text: str, banned: list[str]) -> list[str]:
    """Issues for one step's subject and body template."""
    label = f"Step {step.get('step_no') or '?'} ({step.get('channel') or 'Email'})"
    subject, body = step.get("subject_template") or "", step.get("body_template") or ""
    text = f"{subject}\n{body}"
    lowered = text.lower()
    issues = []
    for phrase in dict.fromkeys([*DEFAULT_BANNED, *banned]):
        if phrase and phrase.lower() in lowered:
            issues.append(f"{label}: avoid \"{phrase}\" (an absolute or unverifiable claim).")
    known = _numbers(knowledge_text)
    for figure in dict.fromkeys(match.strip() for match in FIGURE.findall(text)):
        if not _numbers(figure) <= known:
            issues.append(f"{label}: \"{figure}\" is not in your approved knowledge.")
    approved_terms = " ".join((pricing_text or "").lower().split())
    for match in COMMERCIAL.finditer(text):
        term = " ".join(match.group(0).lower().split())
        if term not in approved_terms:  # each offer must be one an approved Pricing or Offer item makes
            issues.append(f"{label}: mentions \"{match.group(0)}\" but no approved Pricing or Offer item does "
                          "(commercial terms need a person's approval).")
    unknown = sorted({name for name in PLACEHOLDER_RE.findall(text) if name not in PLACEHOLDERS})
    if unknown:
        issues.append(f"{label}: unknown placeholder(s) {', '.join(unknown)} (they are removed when sending).")
    channel = step.get("channel") or "Email"
    plain = PLACEHOLDER_RE.sub("", body)
    if channel in LIMITS and len(plain) > LIMITS[channel]:
        issues.append(f"{label}: {len(plain)} characters; keep {channel} under {LIMITS[channel]}.")
    if channel == "Email" and len(subject) > SUBJECT_LIMIT:
        issues.append(f"{label}: subject is {len(subject)} characters; keep it under {SUBJECT_LIMIT}.")
    if not body.strip():
        issues.append(f"{label}: the message is empty.")
    return issues


def check_steps(steps: list[dict], knowledge: list[dict], banned: list[str]) -> dict:
    """{'status': 'Passed' | 'Needs review', 'issues': [...]} for a whole sequence."""
    knowledge_text = "\n".join(f"{k.get('title', '')}\n{k.get('content', '')}" for k in knowledge)
    pricing_text = "\n".join(k.get("content", "") for k in knowledge if k.get("category") in ("Pricing", "Offer"))
    issues = [issue for step in steps for issue in check_step(step, knowledge_text, pricing_text, banned)]
    return {"status": "Needs review" if issues else "Passed", "issues": issues}


def knowledge_prompt(knowledge: list[dict]) -> str:
    return "\n\n".join(f"[{k.get('category')}] {k.get('title')}\n{k.get('content')}" for k in knowledge) \
        or "No approved knowledge yet: describe only what the seller profile says, with no figures or offers."


def clean_steps(data: dict, plan: list[dict]) -> list[dict]:
    """AI output fitted to the fixed plan: one message per planned step, placeholders limited to the known ones."""
    written = {int(s.get("step_no") or 0): s for s in data.get("steps") or [] if isinstance(s, dict)}
    rows = []
    for slot in plan:
        draft = written.get(slot["step_no"]) or {}
        body = str(draft.get("body") or "").strip()
        body = PLACEHOLDER_RE.sub(lambda m: m.group(0) if m.group(1) in PLACEHOLDERS else "", body)
        subject = " ".join(str(draft.get("subject") or "").split())[:SUBJECT_LIMIT] \
            if slot["channel"] in SUBJECT_CHANNELS else ""
        if body:
            rows.append({**slot, "subject_template": subject, "body_template": body[:3000],
                         "use_ai_personalisation": 1 if "{{personal_line}}" in body.replace(" ", "") else 0})
    return rows

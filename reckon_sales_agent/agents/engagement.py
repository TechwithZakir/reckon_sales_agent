"""Engagement agent rules (pure: no Frappe imports).

* Routine questions are answered only from the Company's approved knowledge;
  pricing exceptions, contracts, complaints, legal matters and anything the
  knowledge does not cover go to a person.
* WhatsApp: free-form messages only inside the 24-hour customer-service
  window that opens when the customer writes; outside it, only an approved
  template may be sent.
* Email delivery events (bounces, complaints) arrive on a signed webhook,
  are verified, de-duplicated by event id and acted on.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta

from reckon_sales_agent.providers.llm import UNTRUSTED_RULES

SERVICE_WINDOW_HOURS = 24
SENSITIVE_TOPICS = frozenset({"pricing_exception", "contract", "complaint", "legal"})
TOPICS = ("product", "pricing_standard", "pricing_exception", "contract", "complaint", "legal", "meeting", "other")

ANSWER_SYSTEM = (
    "You answer a prospect's question for a B2B seller in Bangladesh, using ONLY the approved knowledge provided. "
    "If any part of the answer is not in the approved knowledge, set can_answer to false and leave the answer "
    "empty. Never offer discounts, special prices, payment terms, contract terms or promises beyond the approved "
    "knowledge. List the topics the question touches. Reply in the language of the question (English or Bangla), "
    "politely, in at most 80 words, without a greeting line or signature (those are added). " + UNTRUSTED_RULES
)
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "can_answer": {"type": "boolean"},
        "answer": {"type": "string"},
        "topics": {"type": "array", "items": {"type": "string", "enum": list(TOPICS)}},
    },
    "required": ["can_answer", "answer", "topics"],
    "additionalProperties": False,
}

SEND, DRAFT, ESCALATE = "send", "draft", "escalate"


def answer_route(can_answer: bool, topics: list[str], issues: list[str], auto_allowed: bool) -> tuple[str, str]:
    """What to do with an AI answer: send it, keep it as a draft for a person, or hand the question to a person."""
    sensitive = sorted(set(topics or []) & SENSITIVE_TOPICS)
    if sensitive:
        return ESCALATE, f"Needs a person: {', '.join(t.replace('_', ' ') for t in sensitive)}."
    if not can_answer:
        return ESCALATE, "The approved knowledge does not answer this question."
    if issues:
        return DRAFT, "The answer failed the content check: " + "; ".join(issues[:3])
    if not auto_allowed:
        return DRAFT, "Automatic answers are off or not allowed on this channel; a person reviews it."
    return SEND, "Answered from approved knowledge."


def within_service_window(last_inbound: datetime | None, now: datetime, hours: int = SERVICE_WINDOW_HOURS) -> bool:
    """True while the customer's last WhatsApp message is less than 24 hours old."""
    return bool(last_inbound) and now - last_inbound < timedelta(hours=hours)


def sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def verify_signature(secret: str | None, body: bytes, signature: str | None) -> bool:
    """HMAC-SHA256 of the raw body with the shared secret; constant-time comparison."""
    if not secret or not signature:
        return False
    given = signature.split("=", 1)[1] if signature.startswith("sha256=") else signature
    return hmac.compare_digest(sign(secret, body), given.strip().lower())


EVENT_TYPES = {"bounce": "bounce", "bounced": "bounce", "complaint": "complaint", "spamreport": "complaint",
               "spam_report": "complaint", "delivered": "delivered", "delivery": "delivered",
               "unsubscribe": "unsubscribe"}


def normalize_email_events(payload) -> list[dict]:
    """[{id, type: bounce|complaint|delivered, hard, email, message}] from {"events": [...]} (or a list)."""
    raw = payload.get("events") if isinstance(payload, dict) else payload
    events = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        kind = EVENT_TYPES.get(str(item.get("type") or item.get("event") or "").lower())
        event_id = str(item.get("id") or item.get("event_id") or "").strip()
        if not kind or not event_id:
            continue
        bounce_type = str(item.get("bounce_type") or item.get("bounceType") or "hard").lower()
        events.append({
            "id": event_id[:140],
            "type": kind,
            "hard": kind == "bounce" and bounce_type in ("hard", "permanent"),
            "email": str(item.get("email") or item.get("recipient") or "").strip().lower()[:200],
            "message": str(item.get("message_id") or item.get("message") or "").strip()[:140],
        })
    return events

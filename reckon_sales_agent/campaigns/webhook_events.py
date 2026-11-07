"""Outgoing webhooks: which events exist and how they are signed (pure: no Frappe imports).

A subscription is a web address plus the events it wants. Each delivery is a JSON POST::

    {"event": "opened", "at": "2026-11-07 10:00:00", "data": {...}}

with the headers ``X-Reckon-Event`` and ``X-Reckon-Signature`` (hex HMAC-SHA256 of the raw body, keyed with the subscription's
secret), so the receiver can check that it really came from here.
"""

from __future__ import annotations

import hashlib
import hmac
import re

EVENTS = {
    "signup": "Someone signs up on a form",
    "confirmed": "Someone confirms their email",
    "tag_added": "A tag is added to someone",
    "sent": "A campaign message is sent",
    "opened": "An email is opened",
    "clicked": "A link is clicked",
    "replied": "Someone replies",
    "bounced": "An email bounces",
    "complained": "Someone marks an email as spam",
    "unsubscribed": "Someone unsubscribes",
    "automation_completed": "Someone finishes an automation",
}
# Communication event types (Sales Communication Event) -> webhook events
FROM_COMMUNICATION = {
    "sent": "sent", "opened": "opened", "clicked": "clicked", "replied": "replied", "positive_reply": "replied",
    "meeting_requested": "replied", "bounced": "bounced", "complained": "complained", "unsubscribed": "unsubscribed",
}
MAX_FAILURES = 10  # in a row: the subscription is switched off so a dead address is not called forever


def clean_events(value) -> list[str]:
    """The known events in a comma separated text or a list, without repeats, in catalogue order."""
    parts = value if isinstance(value, (list, tuple, set)) else re.split(r"[,\n]", str(value or ""))
    wanted = {str(p).strip().lower() for p in parts}
    return [event for event in EVENTS if event in wanted]


def wants(events_text, event: str) -> bool:
    return event in clean_events(events_text)


def sign(secret: str, body: bytes) -> str:
    return hmac.new((secret or "").encode(), body, hashlib.sha256).hexdigest()


def verify(secret: str, body: bytes, signature: str) -> bool:
    """For receivers (and tests): the signature matches the body."""
    return bool(secret) and hmac.compare_digest(sign(secret, body), str(signature or ""))


def safe_url(value) -> str:
    text = str(value or "").strip()
    return text if text.lower().startswith("https://") and len(text) <= 500 and not re.search(r"[\s\"'<>]", text) else ""

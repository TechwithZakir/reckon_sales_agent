"""Sending pace and unsubscribe headers (pure: no Frappe imports).

Mailbox providers read a sudden burst as spam, so a Company's outreach goes out one message at a time with a gap between
messages, never above an hourly limit, on top of the daily limit and the warm-up. The gap is not an exact interval
(a fixed beat looks like a script), so each message gets its own length between ``gap * (1 - jitter)`` and
``gap * (1 + jitter)``, always the same for the same message.

Bulk senders are also expected to carry a one-click unsubscribe header (RFC 8058), which Gmail and Yahoo require.
"""

from __future__ import annotations

import hashlib

PACED_CHANNELS = ("Email", "SMS", "WhatsApp")  # internal tasks and chat replies contact nobody in bulk

DEFAULT_GAP_SECONDS = 45
DEFAULT_JITTER_PERCENT = 40
DEFAULT_HOURLY_LIMIT = 30  # per channel
BREVO_FREE_DAILY_LIMIT = 300
MAX_GAP_SECONDS = 600


def _whole(value, default: int) -> int:
    """An unset (None or empty) setting takes its default; a stored 0 stays 0, which switches the control off."""
    if value is None or value == "":
        return default
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return default


def config(settings) -> dict:
    """The Company's pace: gap seconds (0 = no gap), jitter percent, and the hourly limit per channel (0 = none)."""
    get = settings.get if hasattr(settings, "get") else (lambda key: None)
    return {
        "gap": min(_whole(get("send_gap_seconds"), DEFAULT_GAP_SECONDS), MAX_GAP_SECONDS),
        "jitter": min(_whole(get("send_gap_jitter"), DEFAULT_JITTER_PERCENT), 90),
        "hourly": _whole(get("hourly_message_limit"), DEFAULT_HOURLY_LIMIT),
    }


def message_gap(gap: int, jitter_percent: int, key: str) -> float:
    """This message's gap in seconds: the base gap moved by up to the jitter, the same every time for the same key."""
    if gap <= 0:
        return 0.0
    spread = gap * min(max(jitter_percent, 0), 90) / 100
    unit = int(hashlib.sha256((key or "").encode()).hexdigest()[:8], 16) / 0xFFFFFFFF  # 0..1
    return round(gap - spread + 2 * spread * unit, 1)


def wait_seconds(seconds_since_last_send: float | None, gap_for_message: float) -> float:
    """How long until the gap has passed (0 = send now). No earlier send means no wait."""
    if seconds_since_last_send is None or gap_for_message <= 0:
        return 0.0
    return max(round(gap_for_message - max(seconds_since_last_send, 0.0), 1), 0.0)


def hourly_reached(sent_last_hour: int, hourly_limit: int) -> bool:
    return hourly_limit > 0 and sent_last_hour >= hourly_limit


def brevo_daily_limit(settings) -> int:
    """The most Brevo will take today for this Company: its own plan, free by default (300 a day). 0 = no cap."""
    get = settings.get if hasattr(settings, "get") else (lambda key: None)
    return _whole(get("brevo_daily_cap"), BREVO_FREE_DAILY_LIMIT)


# Unsubscribe headers ---------------------------------------------------------


def unsubscribe_headers(url: str) -> dict:
    """One-click unsubscribe (RFC 8058). The link is https, and a POST to it unsubscribes without a page."""
    if not (url or "").lower().startswith("https://"):
        return {}  # the standard needs an https link; a plain-http one would be ignored or flagged, so none is sent
    if any(ch in url for ch in "<>\r\n "):
        return {}
    return {"List-Unsubscribe": f"<{url}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}


def add_headers_to_mime(raw: str, headers: dict) -> str:
    """The headers at the top of a stored MIME message, unless it already carries a List-Unsubscribe."""
    if not headers or not raw:
        return raw
    head = raw.split("\n\n", 1)[0].split("\r\n\r\n", 1)[0].lower()
    if "\nlist-unsubscribe:" in "\n" + head:
        return raw
    newline = "\r\n" if "\r\n" in raw[:2000] else "\n"
    return "".join(f"{name}: {value}{newline}" for name, value in headers.items()) + raw

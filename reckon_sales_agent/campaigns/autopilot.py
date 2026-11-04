"""Campaign autopilot: how much the agent may do alone (pure: no Frappe imports).

Three levels, per Company:

* Off: the agent drafts nothing on its own initiative and a person approves every message.
* Assist: the copilot suggests and creates internal follow-up tasks for people who engage. A person still approves
  every message that reaches a customer.
* Auto-send: once a person has approved a campaign (its content, channels, audience and schedule), the messages that
  follow its steps go out without a second click, inside the sending window and the daily limits.

Autopilot never overrides a safety rule: suppression, missing consent, the kill switch, the outbound switch, daily limits,
the WhatsApp 24-hour window and a failed content check all still stop a message. A campaign that changed after approval
needs a person again.
"""

from __future__ import annotations

OFF, ASSIST, AUTO = "Off", "Assist", "Auto-send"
LEVELS = (OFF, ASSIST, AUTO)
OUTREACH_CHANNELS = frozenset({"Email", "SMS", "WhatsApp"})

DESCRIPTIONS = {
    OFF: "A person approves every message. The copilot is silent.",
    ASSIST: "The copilot suggests, and creates internal follow-up tasks for people who engage. A person approves every message.",
    AUTO: "After a person approves a campaign, its messages go out on their own, inside the sending window and daily limits.",
}


def normalize_level(value) -> str:
    return value if value in LEVELS else OFF


def parse_window(text) -> tuple[int, int] | None:
    """"09:00-20:00" as minutes after midnight, or None when empty or not understood."""
    try:
        start, end = str(text or "").replace(" ", "").split("-")
        (sh, sm), (eh, em) = (map(int, start.split(":")), map(int, end.split(":")))
    except ValueError:
        return None
    if not (0 <= sh < 24 and 0 <= eh <= 24 and 0 <= sm < 60 and 0 <= em < 60):
        return None
    return sh * 60 + sm, eh * 60 + em


def in_window(text, minutes_now: int) -> bool:
    """True when sending is allowed now. No window set (or an unreadable one) means any time. A window that
    crosses midnight, such as 20:00-06:00, is supported."""
    window = parse_window(text)
    if not window:
        return True
    start, end = window
    if start == end:
        return True
    return start <= minutes_now < end if start < end else minutes_now >= start or minutes_now < end


def may_auto_approve(level: str, *, campaign_active: bool, campaign_approved: bool, content_passed: bool,
                     channel: str) -> tuple[bool, str]:
    """May this draft skip the per-message click? Returns (yes/no, why)."""
    if level != AUTO:
        return False, "Autopilot is not set to Auto-send."
    if channel not in OUTREACH_CHANNELS:
        return False, "Only email, SMS and WhatsApp messages can be auto-approved."
    if not campaign_active or not campaign_approved:
        return False, "A person has not approved this campaign."
    if not content_passed:
        return False, "The content check has not passed."
    return True, "The campaign was approved by a person and its content passed the check."


def creates_followup_tasks(level: str) -> bool:
    """Internal tasks for engaged people (the agent contacts nobody) from Assist upwards."""
    return level in (ASSIST, AUTO)

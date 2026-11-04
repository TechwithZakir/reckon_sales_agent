"""One person's campaign history and how engaged they are (pure: no Frappe imports).

Every message and event a person has had, across all campaigns, in time order: this is the trace-back for a lead,
contact or prospect. The engagement score turns the same events into one number so the team knows who to call first.
"""

from __future__ import annotations

# Points per event. Opens and clicks are counted up to a cap so one curious person cannot outrank a real reply.
WEIGHTS = {
    "opened": (2, 3),
    "clicked": (5, 3),
    "read": (2, 1),
    "replied": (10, 1),
    "positive_reply": (15, 1),
    "meeting_requested": (20, 1),
    "call_interested": (15, 1),
}
PENALTIES = {"bounced": 10, "unsubscribed": 20, "complained": 30, "failed": 3, "call_not_interested": 10,
             "call_wrong_number": 10}
REPLIES = ("replied", "positive_reply", "meeting_requested")
HOT, WARM = 15, 5  # a positive reply or three clicks is hot; one click is warm

LABELS = {
    "drafted": "Draft written", "approved": "Approved", "auto_approved": "Approved by the autopilot",
    "sent": "Sent", "dry_run": "Test run (nothing sent)", "delivered": "Delivered", "read": "Read",
    "opened": "Opened", "clicked": "Clicked a link", "replied": "Replied", "positive_reply": "Replied: interested",
    "meeting_requested": "Asked for a meeting", "out_of_office": "Out of office", "bounced": "Bounced",
    "unsubscribed": "Unsubscribed", "complained": "Marked as spam", "failed": "Failed to send",
    "stopped": "Sequence stopped", "task_created": "Follow-up task created",
}
# Events a person reads in a timeline; the rest (drafts, approvals) are internal and shown only on request.
VISIBLE = frozenset({"sent", "dry_run", "delivered", "read", "opened", "clicked", "replied", "positive_reply",
                     "meeting_requested", "out_of_office", "bounced", "unsubscribed", "complained", "failed",
                     "stopped", "task_created"})


def engagement_score(events: list[dict]) -> int:
    """0 to 100. Opens and clicks add a little (capped), replies and meetings add a lot, bounces and opt-outs subtract."""
    counts: dict[str, int] = {}
    for event in events:
        kind = event.get("event_type") or ""
        counts[kind] = counts.get(kind, 0) + 1
    score = 0
    for kind, (points, cap) in WEIGHTS.items():
        score += points * min(counts.get(kind, 0), cap)
    for kind, points in PENALTIES.items():
        if counts.get(kind):
            score -= points
    return max(0, min(100, score))


def temperature(score: int, events: list[dict] | None = None) -> str:
    """Hot, Warm, Cold, or Opted out for someone who unsubscribed or complained."""
    kinds = {e.get("event_type") for e in events or []}
    if kinds & {"unsubscribed", "complained"}:
        return "Opted out"
    if score >= HOT:
        return "Hot"
    if score >= WARM:
        return "Warm"
    return "Cold"


def build_timeline(messages: list[dict], events: list[dict], show_internal: bool = False) -> list[dict]:
    """Oldest first. Each entry: at, kind, label, campaign, channel, step_no, subject, detail."""
    by_message = {m.get("name"): m for m in messages}
    entries = []
    for event in events:
        kind = event.get("event_type") or ""
        if not show_internal and kind not in VISIBLE:
            continue
        message = by_message.get(event.get("message")) or {}
        entries.append({
            "at": str(event.get("event_time") or ""), "kind": kind, "label": LABELS.get(kind, kind.replace("_", " ").title()),
            "campaign": event.get("campaign") or message.get("campaign") or "", "channel": message.get("channel") or event.get("channel") or "",
            "step_no": message.get("step_no") or 0, "subject": message.get("subject") or "", "detail": event.get("detail") or "",
            "message": event.get("message") or "",
        })
    return sorted(entries, key=lambda e: e["at"])


def summarize_person(events: list[dict]) -> dict:
    """The headline for one person: score, temperature, counts and the last time anything happened."""
    score = engagement_score(events)
    counts = {kind: sum(1 for e in events if e.get("event_type") == kind)
              for kind in ("sent", "opened", "clicked", "bounced", "unsubscribed")}
    # One answer can be several events (a reply, then its classification): count the messages that were answered.
    counts["replied"] = len({e.get("message") or f"#{i}" for i, e in enumerate(events) if e.get("event_type") in REPLIES})
    stamps = [str(e.get("event_time") or "") for e in events if e.get("event_time")]
    return {"score": score, "temperature": temperature(score, events), "counts": counts,
            "last_activity": max(stamps) if stamps else ""}

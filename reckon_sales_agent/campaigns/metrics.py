"""Campaign funnel aggregation (pure: no Frappe imports)."""

from __future__ import annotations

OUTREACH_EVENTS = ("sent", "dry_run")
REPLY_EVENTS = ("replied", "positive_reply", "meeting_requested")


def rate(numerator: int, denominator: int) -> float:
    return round(100.0 * numerator / denominator, 1) if denominator else 0.0


def summarize(events: list[dict], members: list[dict], deals: list[dict]) -> dict:
    """Pure aggregation, easy to test: events need event_type, channel, step_no."""
    by_channel: dict[str, dict] = {}
    by_step: dict[int, dict] = {}
    totals = {name: 0 for name in ("outreach", "replies", "positive", "meetings", "unsubscribed", "bounced",
                                   "failed", "tasks", "out_of_office")}
    for event in events:
        kind = event.get("event_type")
        channel = event.get("channel") or "Email"
        step = int(event.get("step_no") or 0)
        bucket_c = by_channel.setdefault(channel, {"outreach": 0, "replies": 0, "positive": 0})
        bucket_s = by_step.setdefault(step, {"outreach": 0, "replies": 0, "positive": 0})
        if kind in OUTREACH_EVENTS:
            totals["outreach"] += 1
            bucket_c["outreach"] += 1
            bucket_s["outreach"] += 1
        if kind in REPLY_EVENTS:
            totals["replies"] += 1
            bucket_c["replies"] += 1
            bucket_s["replies"] += 1
        if kind in ("positive_reply", "meeting_requested"):
            totals["positive"] += 1
            bucket_c["positive"] += 1
            bucket_s["positive"] += 1
        if kind == "meeting_requested":
            totals["meetings"] += 1
        if kind == "unsubscribed":
            totals["unsubscribed"] += 1
        if kind == "bounced":
            totals["bounced"] += 1
        if kind == "failed":
            totals["failed"] += 1
        if kind == "task_created":
            totals["tasks"] += 1
        if kind == "out_of_office":
            totals["out_of_office"] += 1
    for bucket in list(by_channel.values()) + list(by_step.values()):
        bucket["reply_rate"] = rate(bucket["replies"], bucket["outreach"])
        bucket["positive_rate"] = rate(bucket["positive"], bucket["outreach"])
    status_counts: dict[str, int] = {}
    for member in members:
        status_counts[member.get("status") or "?"] = status_counts.get(member.get("status") or "?", 0) + 1
    reached = sum(1 for m in members if m.get("status") not in ("Ineligible", "Eligible"))
    pipeline = sum(float(d.get("deal_value") or 0) for d in deals)
    return {
        "members": len(members),
        "member_status": status_counts,
        "totals": totals,
        "reply_rate": rate(totals["replies"], totals["outreach"]),
        "positive_reply_rate": rate(totals["positive"], totals["outreach"]),
        "unsubscribe_rate": rate(totals["unsubscribed"], totals["outreach"]),
        "deals": len(deals),
        "conversion_rate": rate(len(deals), reached),
        "pipeline_value": round(pipeline, 2),
        "by_channel": by_channel,
        "by_step": {str(k): v for k, v in sorted(by_step.items())},
    }

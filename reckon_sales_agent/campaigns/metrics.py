"""Campaign funnel aggregation (pure: no Frappe imports)."""

from __future__ import annotations

OUTREACH_EVENTS = ("sent", "dry_run")
REPLY_EVENTS = ("replied", "positive_reply", "meeting_requested")


def rate(numerator: int, denominator: int) -> float:
    return round(100.0 * numerator / denominator, 1) if denominator else 0.0


# Which funnel step each event feeds (a unique message is counted once per step).
FUNNEL_STEPS = {
    "sent": "sent", "dry_run": "sent", "delivered": "delivered", "opened": "opened", "clicked": "clicked",
    "read": "read", "replied": "replied", "positive_reply": "replied", "meeting_requested": "replied",
    "bounced": "bounced", "unsubscribed": "unsubscribed", "complained": "complained",
}
POSITIVE_EVENTS = ("positive_reply", "meeting_requested")


def funnel(events: list[dict]) -> dict:
    """Unique-message funnel, rates, a daily series and the hours people open. Events need ``event_type``;
    ``message``, ``channel`` and ``event_time`` are used when present (without ``message`` each event counts once)."""
    steps = ("sent", "delivered", "opened", "clicked", "read", "replied", "positive", "bounced", "unsubscribed",
             "complained")
    seen = {step: set() for step in steps}
    per_channel: dict[str, dict] = {}
    per_variant: dict[str, dict] = {}
    by_day: dict[str, dict] = {}
    open_hours: dict[str, int] = {}
    totals = {"opens": 0, "clicks": 0}
    for index, event in enumerate(events):
        kind = event.get("event_type")
        step = FUNNEL_STEPS.get(kind)
        if not step:
            continue
        key = event.get("message") or f"#{index}"
        channel = event.get("channel") or "Email"
        chan = per_channel.setdefault(channel, {name: set() for name in steps})
        targets = [step] + (["positive"] if kind in POSITIVE_EVENTS else [])
        variant = event.get("variant")
        var = per_variant.setdefault(variant, {name: set() for name in steps}) if variant else None
        for target in targets:
            seen[target].add(key)
            chan[target].add(key)
            if var is not None:
                var[target].add(key)
        day = str(event.get("event_time") or "")[:10]
        if day:
            bucket = by_day.setdefault(day, {"sent": 0, "opened": 0, "clicked": 0, "replied": 0})
            if step in bucket:
                bucket[step] += 1
        if kind == "opened":
            totals["opens"] += 1
            hour = str(event.get("event_time") or "")[11:13]
            if hour.isdigit():
                open_hours[hour] = open_hours.get(hour, 0) + 1
        if kind == "clicked":
            totals["clicks"] += 1

    def counts(source: dict) -> dict:
        return {name: len(values) for name, values in source.items()}

    def rates(c: dict) -> dict:
        return {
            "open_rate": rate(c["opened"], c["sent"]), "click_rate": rate(c["clicked"], c["sent"]),
            "click_to_open_rate": rate(c["clicked"], c["opened"]), "reply_rate": rate(c["replied"], c["sent"]),
            "positive_rate": rate(c["positive"], c["sent"]), "bounce_rate": rate(c["bounced"], c["sent"]),
            "unsubscribe_rate": rate(c["unsubscribed"], c["sent"]), "delivery_rate": rate(c["delivered"], c["sent"]),
            "read_rate": rate(c["read"], c["sent"]),
        }

    overall = counts(seen)
    by_channel = {}
    for channel, source in per_channel.items():
        c = counts(source)
        by_channel[channel] = {**c, **rates(c)}
    by_variant = {}
    for letter, source in sorted(per_variant.items()):
        c = counts(source)
        by_variant[letter] = {**c, **rates(c)}
    return {"counts": overall, "rates": rates(overall), "totals": totals, "by_channel": by_channel, "by_variant": by_variant,
            "by_day": dict(sorted(by_day.items())), "open_hours": dict(sorted(open_hours.items()))}


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
    reached = sum(1 for m in members if m.get("status") not in ("Ineligible", "Eligible", "Holdout"))
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
        "engagement": funnel(events),
    }

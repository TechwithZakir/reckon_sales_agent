"""Campaign copilot: plain-language suggestions from a campaign's numbers (pure: no Frappe imports).

The copilot only suggests. It reads aggregated metrics (``campaigns.metrics.summarize``) and a few facts about the
campaign, and returns a ranked list of things worth doing. Each suggestion names an action the Studio can offer, but
nothing here changes a campaign, a message or a recipient. Small samples are not judged: a rate on ten messages is noise.
"""

from __future__ import annotations

HIGH, WARN, INFO = "high", "warn", "info"
ORDER = {HIGH: 0, WARN: 1, INFO: 2}

MIN_BOUNCE_SAMPLE = 20
MIN_RATE_SAMPLE = 50
BOUNCE_LIMIT = 5.0
UNSUBSCRIBE_LIMIT = 2.0
OPEN_FLOOR = 15.0
CLICK_TO_OPEN_FLOOR = 5.0
GOOD_REPLY = 5.0


def best_hours(open_hours: dict, top: int = 2, minimum_opens: int = 10) -> list[int]:
    """The hours people open mail most, once there are enough opens to say (server time)."""
    total = sum(open_hours.values())
    if total < minimum_opens:
        return []
    ranked = sorted(open_hours.items(), key=lambda item: (-item[1], item[0]))[:top]
    return sorted(int(hour) for hour, _count in ranked)


def suggest(metrics: dict, context: dict | None = None) -> list[dict]:
    """Ranked suggestions: each has id, severity, title, detail and an optional action for the Studio."""
    ctx = context or {}
    engagement = metrics.get("engagement") or {}
    counts, rates = engagement.get("counts") or {}, engagement.get("rates") or {}
    sent = int(counts.get("sent") or 0)
    items: list[dict] = []

    def add(item_id: str, severity: str, title: str, detail: str, action: str = "") -> None:
        items.append({"id": item_id, "severity": severity, "title": title, "detail": detail, "action": action})

    if ctx.get("hot_recipients"):
        n = int(ctx["hot_recipients"])
        add("hot_recipients", HIGH, f"{n} {'person is' if n == 1 else 'people are'} showing real interest",
            "They clicked a link more than once or replied. Call them while it is fresh.", "call_hot")
    if sent >= MIN_BOUNCE_SAMPLE and rates.get("bounce_rate", 0) >= BOUNCE_LIMIT:
        add("bounces", HIGH, f"{rates['bounce_rate']}% of messages bounced",
            "Too many bad addresses hurt your sender reputation. Pause, clean the audience, then resume.", "pause")
    if sent >= MIN_BOUNCE_SAMPLE and rates.get("unsubscribe_rate", 0) >= UNSUBSCRIBE_LIMIT:
        add("unsubscribes", WARN, f"{rates['unsubscribe_rate']}% opted out",
            "People are asking not to hear from you. Narrow the audience or space the steps further apart.", "narrow_audience")
    if ctx.get("outbound_enabled") is False and sent:
        add("test_mode", WARN, "Sending is switched off, so these are test runs",
            "Nothing reached a customer. Turn sending on in Sales Agent Settings when the content is ready.", "")
    if ctx.get("sms_parts", 0) > 2:
        add("sms_length", WARN, f"An SMS step takes {ctx['sms_parts']} parts",
            "Long texts cost more and are read less. Shorten it to two parts or fewer.", "edit_template")
    email = (engagement.get("by_channel") or {}).get("Email") or {}
    if int(email.get("sent") or 0) >= MIN_RATE_SAMPLE and email.get("open_rate", 100) < OPEN_FLOOR:
        add("low_opens", WARN, f"Email opens are low ({email['open_rate']}%)",
            "Try a shorter, more specific subject line and send at the hours people open (see below).", "rewrite_subject")
    if int(counts.get("opened") or 0) >= 20 and rates.get("click_to_open_rate", 100) < CLICK_TO_OPEN_FLOOR:
        add("opens_without_clicks", INFO, "People open but do not click",
            "Use one clear button near the top and say what happens when they click.", "edit_template")
    hours = best_hours(engagement.get("open_hours") or {})
    if hours:
        add("send_window", INFO, "Most opens happen around " + " and ".join(f"{h:02d}:00" for h in hours),
            "Set the sending window to cover these hours (server time).", "set_window")
    if sent >= MIN_RATE_SAMPLE and rates.get("reply_rate", 0) >= GOOD_REPLY:
        add("good_replies", INFO, f"Replies are strong ({rates['reply_rate']}%)",
            "This message works. Consider a larger audience or a second step.", "scale")
    if not sent and not ctx.get("campaign_new"):
        add("nothing_sent", INFO, "Nothing has been sent yet",
            "Start with a small pilot audience so you learn before you scale.", "pilot")
    if ctx.get("unreached"):
        add("unreached", INFO, f"{ctx['unreached']} audience members cannot be reached on these channels",
            "They have no email or phone for the steps in this campaign, or no consent for SMS or WhatsApp.", "")
    return sorted(items, key=lambda item: ORDER[item["severity"]])

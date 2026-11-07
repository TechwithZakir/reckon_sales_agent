"""A campaign's results in plain words (pure: no Frappe imports).

Numbers alone do not tell a busy person what to do. This turns the funnel into a headline, a few plain sentences and the
steps people drop out at, using ranges that are usual for B2B email. They are guides, not promises: a small send says so
instead of judging.
"""

from __future__ import annotations

import csv
import io

MIN_SENT = 30  # under this a rate says very little
# (low edge, good edge) in percent: below the low edge is weak, above the good edge is strong
OPEN = (20.0, 35.0)
CLICK = (1.5, 4.0)
REPLY = (1.0, 4.0)
BOUNCE_WARN, BOUNCE_BAD = 2.0, 5.0
UNSUB_WARN, UNSUB_BAD = 0.5, 1.5


def _band(value: float, edges: tuple[float, float]) -> str:
    return "low" if value < edges[0] else ("good" if value >= edges[1] else "ok")


def verdict(counts: dict, rates: dict, channel: str = "Email") -> dict:
    """{tone, headline, lines, advice}. tone is good, ok, low or early."""
    sent = int(counts.get("sent") or 0)
    if sent < MIN_SENT:
        return {"tone": "early", "headline": f"Too early to judge: {sent} sent so far.",
                "lines": ["Rates move a lot on small numbers. Judge it once at least 30 messages have gone out."], "advice": []}
    lines: list[str] = []
    advice: list[str] = []
    opened, clicked, replied = rates.get("open_rate", 0.0), rates.get("click_rate", 0.0), rates.get("reply_rate", 0.0)
    bands = {}
    if channel == "Email":
        bands["open"] = _band(opened, OPEN)
        lines.append({"low": f"{opened:g}% opened: below the usual {OPEN[0]:g} to {OPEN[1]:g}%.",
                      "ok": f"{opened:g}% opened: in the usual range of {OPEN[0]:g} to {OPEN[1]:g}%.",
                      "good": f"{opened:g}% opened: above the usual range."}[bands["open"]])
        if bands["open"] == "low":
            advice.append("Try a clearer, shorter subject line, and test two subjects against each other.")
    bands["click"] = _band(clicked, CLICK)
    lines.append({"low": f"{clicked:g}% clicked: people are not acting on it.",
                  "ok": f"{clicked:g}% clicked: a normal response.",
                  "good": f"{clicked:g}% clicked: strong interest."}[bands["click"]])
    if bands["click"] == "low":
        advice.append("Make the call to action a clear button with one next step.")
    bands["reply"] = _band(replied, REPLY)
    if replied:
        lines.append(f"{replied:g}% replied" + (f", {counts.get('positive', 0)} interested." if counts.get("positive") else "."))
    bounce, unsub = rates.get("bounce_rate", 0.0), rates.get("unsubscribe_rate", 0.0)
    if bounce >= BOUNCE_BAD:
        lines.append(f"{bounce:g}% bounced: that is high and can hurt your sender reputation.")
        advice.append("Check the list in Capture Studio → Clean list before the next send.")
    elif bounce >= BOUNCE_WARN:
        lines.append(f"{bounce:g}% bounced: a little high.")
        advice.append("Check the list in Capture Studio → Clean list.")
    if unsub >= UNSUB_BAD:
        lines.append(f"{unsub:g}% opted out: more than usual.")
        advice.append("Send to a narrower, more relevant audience, or less often.")
    elif unsub >= UNSUB_WARN:
        lines.append(f"{unsub:g}% opted out: slightly high.")
    scored = [b for k, b in bands.items() if k != "reply"]
    if bounce >= BOUNCE_BAD or unsub >= UNSUB_BAD or scored.count("low") >= 2:
        tone, headline = "low", "Needs attention"
    elif scored.count("good") >= 1 and "low" not in scored:
        tone, headline = "good", "Strong engagement"
    elif "low" in scored:
        tone, headline = "ok", "Mixed: some things to improve"
    else:
        tone, headline = "ok", "A normal result"
    return {"tone": tone, "headline": headline, "lines": lines, "advice": advice}


def steps(counts: dict) -> list[dict]:
    """The journey, step by step: how many reached each step, as a share of those sent and of the step before, and how many
    dropped out between. A step nobody could reach (such as delivery for mail without receipts) is left out."""
    order = [("sent", "Sent"), ("delivered", "Delivered"), ("opened", "Opened"), ("clicked", "Clicked"), ("replied", "Replied"),
             ("positive", "Interested")]
    sent = int(counts.get("sent") or 0)
    out: list[dict] = []
    previous = None
    for key, label in order:
        n = int(counts.get(key) or 0)
        if key not in ("sent", "opened") and n == 0:
            continue
        out.append({"key": key, "label": label, "count": n, "of_sent": round(100.0 * n / sent, 1) if sent else 0.0,
                    "of_previous": round(100.0 * n / previous, 1) if previous else (100.0 if key == "sent" else 0.0),
                    "lost": max(previous - n, 0) if previous is not None else 0})
        previous = n
    return out


EXPORT_COLUMNS = ("Person", "Email", "Phone", "Channel", "Step", "Variant", "Status", "Sent", "Opened", "Clicked", "Replied", "Bounced",
                  "Unsubscribed")


def export_rows(messages: list[dict], events: list[dict], people: dict) -> list[list]:
    """One row per message: who, what, when it was sent and what the person did. ``people`` maps prospect -> {name, email, phone}.
    Spreadsheet formulas are neutralised (a cell starting with = + - @ gets a leading apostrophe)."""
    done: dict[str, set] = {}
    for event in events:
        done.setdefault(event.get("message") or "", set()).add(event.get("event_type"))
    rows = []
    for message in messages:
        kinds = done.get(message.get("name"), set())
        person = people.get(message.get("prospect"), {})
        rows.append([
            _safe(person.get("name") or message.get("prospect") or ""), _safe(person.get("email") or ""), _safe(person.get("phone") or ""),
            message.get("channel") or "", message.get("step_no") or "", message.get("variant") or "", message.get("status") or "",
            str(message.get("sent_on") or ""), "yes" if "opened" in kinds else "", "yes" if "clicked" in kinds else "",
            "yes" if kinds & {"replied", "positive_reply", "meeting_requested"} else "", "yes" if "bounced" in kinds else "",
            "yes" if "unsubscribed" in kinds else ""])
    return rows


def _safe(value) -> str:
    text = str(value or "")
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def to_csv(rows: list[list]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(EXPORT_COLUMNS)
    writer.writerows(rows)
    return out.getvalue()

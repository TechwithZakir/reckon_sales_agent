"""Segments: saved rules that pick people (pure: no Frappe imports, so the rules are unit-tested directly).

A segment is "match ALL (or ANY) of these conditions". It is re-evaluated every time it is used, so it stays current: the
same segment can be the audience of a campaign, the trigger or a branch of an automation, and an export.

Each person is described to the rules as a plain dict (see ``person_view`` in segment_service): how many days ago they
joined and last opened, clicked, replied or were sent something, their tags, place and industry, consent and so on.
"""

from __future__ import annotations

from reckon_sales_agent.campaigns import tags as tag_rules

MAX_CONDITIONS = 12
ALL, ANY = "All", "Any"
MATCH_MODES = (ALL, ANY)

DAYS_OPS = {"within": "in the last", "not_within": "not in the last", "never": "never"}
# key: (label, kind, operators {op: label}, choices)
CONDITIONS: dict[str, tuple[str, str, dict, tuple]] = {
    "joined": ("Joined", "days", {"within": "in the last", "before": "more than"}, ()),
    "opened": ("Opened an email", "days", DAYS_OPS, ()),
    "clicked": ("Clicked a link", "days", DAYS_OPS, ()),
    "replied": ("Replied", "days", DAYS_OPS, ()),
    "sent": ("Was sent a message", "days", DAYS_OPS, ()),
    "tag": ("Tag", "text", {"has": "has", "not_has": "does not have"}, ()),
    "city": ("City", "text", {"is": "is", "contains": "contains", "not_is": "is not"}, ()),
    "industry": ("Industry", "text", {"is": "is", "contains": "contains"}, ()),
    "source": ("Where they came from", "text", {"is": "is", "contains": "contains"}, ()),
    "fit_score": ("Fit score", "number", {"at_least": "at least", "at_most": "at most"}, ()),
    "has_email": ("Has an email address", "flag", {"yes": "yes", "no": "no"}, ()),
    "has_phone": ("Has a phone number", "flag", {"yes": "yes", "no": "no"}, ()),
    "sms_consent": ("Agreed to SMS", "flag", {"yes": "yes", "no": "no"}, ()),
    "whatsapp_consent": ("Agreed to WhatsApp", "flag", {"yes": "yes", "no": "no"}, ()),
    "confirmed": ("Email confirmed", "flag", {"yes": "yes", "no": "no"}, ()),
    "temperature": ("Engagement", "choice", {"is": "is"}, ("Hot", "Warm", "Cold")),
    "email_check": ("Email address check", "choice", {"is": "is"}, ("Valid", "Risky", "Invalid", "Unchecked")),
}
EVENT_KEYS = {"opened": "last_opened_days", "clicked": "last_clicked_days", "replied": "last_replied_days",
              "sent": "last_sent_days"}


def catalog() -> list[dict]:
    """What the segment builder offers, for the page."""
    return [{"key": key, "label": label, "kind": kind, "ops": [{"op": op, "label": text} for op, text in ops.items()],
             "choices": list(choices)} for key, (label, kind, ops, choices) in CONDITIONS.items()]


def clean_condition(raw) -> tuple[dict | None, str]:
    """(condition, '') or (None, the reason it is not usable)."""
    if not isinstance(raw, dict) or raw.get("field") not in CONDITIONS:
        return None, "Choose what to check."
    label, kind, ops, choices = CONDITIONS[raw["field"]]
    op = raw.get("op") if raw.get("op") in ops else next(iter(ops))
    value = raw.get("value")
    if kind == "days":
        if op == "never":
            value = ""
        else:
            try:
                value = int(float(value))
            except (TypeError, ValueError):
                return None, f"{label}: enter a number of days."
            if not 0 <= value <= 3650:
                return None, f"{label}: days must be between 0 and 3650."
    elif kind == "number":
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None, f"{label}: enter a number."
        if not 0 <= value <= 100:
            return None, f"{label}: enter a number between 0 and 100."
    elif kind == "text":
        value = tag_rules.clean(value) if raw["field"] == "tag" else " ".join(str(value or "").split())[:140]
        if not value:
            return None, f"{label}: enter a value."
    elif kind == "choice":
        value = value if value in choices else ""
        if not value:
            return None, f"{label}: choose one."
    else:
        value = ""
    return {"field": raw["field"], "op": op, "value": value}, ""


def clean_conditions(rows) -> tuple[list[dict], list[str]]:
    """(usable conditions, one message per row that is not usable). At most 12 rows."""
    good, problems = [], []
    for index, raw in enumerate((rows or [])[:MAX_CONDITIONS], start=1):
        condition, reason = clean_condition(raw)
        if condition:
            good.append(condition)
        else:
            problems.append(f"Rule {index}: {reason}")
    return good, problems


def _flag(person: dict, key: str) -> bool:
    return bool(person.get(key))


def _days_match(days, op: str, value) -> bool:
    if op == "never":
        return days is None
    if op == "within":
        return days is not None and days <= value
    return days is None or days > value  # not_within


def _text_match(have, op: str, want: str) -> bool:
    have, want = str(have or "").strip().lower(), str(want or "").strip().lower()
    if op == "is":
        return have == want
    if op == "not_is":
        return have != want
    return want in have  # contains


def condition_matches(person: dict, condition: dict) -> bool:
    field, op, value = condition.get("field"), condition.get("op"), condition.get("value")
    if field == "joined":
        days = person.get("joined_days")
        if days is None:
            return False
        return days <= value if op == "within" else days > value
    if field in EVENT_KEYS:
        return _days_match(person.get(EVENT_KEYS[field]), op, value)
    if field == "tag":
        found = tag_rules.has(person.get("tags"), value)
        return found if op == "has" else not found
    if field in ("city", "industry", "source"):
        return _text_match(person.get(field), op, value)
    if field == "fit_score":
        score = float(person.get("fit_score") or 0)
        return score >= float(value) if op == "at_least" else score <= float(value)
    if field == "temperature":
        return str(person.get("temperature") or "Cold") == value
    if field == "email_check":
        return (str(person.get("email_status") or "") or "Unchecked") == value
    flag = {"has_email": _flag(person, "email"), "has_phone": _flag(person, "phone"),
            "sms_consent": _flag(person, "sms_consent"), "whatsapp_consent": _flag(person, "whatsapp_consent"),
            "confirmed": person.get("confirmed", True) is not False}.get(field)
    if flag is None:
        return False
    return flag if op == "yes" else not flag


def matches(person: dict, conditions, mode: str = ALL) -> bool:
    """True when the person meets all (or any) of the conditions. A segment with no conditions matches nobody."""
    rules = [c for c in (conditions or []) if isinstance(c, dict)]
    if not rules:
        return False
    results = (condition_matches(person, c) for c in rules)
    return any(results) if mode == ANY else all(results)


def describe(condition: dict) -> str:
    """A rule as a sentence, for lists and summaries."""
    label, kind, ops, _choices = CONDITIONS.get(condition.get("field"), ("?", "text", {}, ()))
    op = ops.get(condition.get("op"), "")
    value = condition.get("value")
    if kind == "days":
        return f"{label} {op}".strip() if condition.get("op") == "never" else f"{label} {op} {value} days"
    if kind == "flag":
        return f"{label}: {op}"
    return f"{label} {op} {value}".replace("  ", " ")


def summary(conditions, mode: str = ALL) -> str:
    rules = [describe(c) for c in conditions or []]
    if not rules:
        return "No rules yet"
    return (" and " if mode != ANY else " or ").join(rules)

"""Reply classification and the actions each class triggers.

Rules always run; Claude refines the class when AI is enabled. The reply
text is untrusted: it is only classified, never followed.
"""

from __future__ import annotations

import re

CLASSES = ("interested", "meeting_request", "question", "not_now", "not_interested", "wrong_person",
           "unsubscribe", "out_of_office", "other")
POSITIVE = frozenset({"interested", "meeting_request", "question"})

SCHEMA = {
    "type": "object",
    "properties": {
        "classification": {"type": "string", "enum": list(CLASSES)},
        "summary": {"type": "string"},
        "suggested_next_step": {"type": "string"},
    },
    "required": ["classification", "summary", "suggested_next_step"],
    "additionalProperties": False,
}

RULES = (
    ("unsubscribe", r"\b(unsubscribe|remove me|stop (sending|emailing)|do not (contact|email)|opt[ -]?out)\b|^\s*stop\s*$|বন্ধ করুন"),
    ("out_of_office", r"\b(out of (the )?office|on leave|on vacation|auto[- ]?reply|automatic reply)\b"),
    ("meeting_request", r"\b(schedule|book|set up|arrange)\b.*\b(call|meeting|demo)\b|\b(call me|meet(ing)? (on|at|next))\b"),
    ("not_interested", r"\b(not interested|no thanks|no, thank|don'?t need|we already have)\b|আগ্রহী নই"),
    ("not_now", r"\b(not (right )?now|later|next (month|quarter|year)|after eid)\b"),
    ("wrong_person", r"\b(wrong person|not the right person|no longer (work|with))\b"),
    ("interested", r"\b(interested|sounds good|tell me more|send (me )?(details|price|quotation|proposal))\b|আগ্রহী"),
    ("question", r"\?"),
)


def strip_quoted(text: str) -> str:
    """Drop the quoted original message so only the new reply is classified."""
    lines = []
    for line in (text or "").splitlines():
        if line.strip().startswith(">") or re.match(r"^\s*On .+wrote:\s*$", line) or line.strip() == "-- ":
            break
        lines.append(line)
    return "\n".join(lines).strip()[:4000]


def classify_rules(text: str) -> str:
    lowered = strip_quoted(text).lower()
    for label, pattern in RULES:
        if re.search(pattern, lowered, flags=re.I | re.M):
            return label
    return "other"


def resolve(rule_class: str, ai_class: str | None) -> str:
    """Opt-outs found by rules always win; otherwise prefer the AI's valid class."""
    if rule_class == "unsubscribe":
        return "unsubscribe"
    if ai_class in CLASSES and ai_class != "other":
        return ai_class
    return rule_class


def actions_for(classification: str) -> dict:
    """What the engine should do: stop?, suppress?, task (priority, days) or None, reschedule days."""
    return {
        "interested": {"stop": True, "suppress": False, "task": ("High", 0), "event": "positive_reply"},
        "meeting_request": {"stop": True, "suppress": False, "task": ("High", 0), "event": "meeting_requested"},
        "question": {"stop": True, "suppress": False, "task": ("High", 0), "event": "positive_reply"},
        "not_now": {"stop": True, "suppress": False, "task": ("Low", 30), "event": "replied"},
        "not_interested": {"stop": True, "suppress": False, "task": None, "event": "replied"},
        "wrong_person": {"stop": True, "suppress": False, "task": ("Medium", 2), "event": "replied"},
        "unsubscribe": {"stop": True, "suppress": True, "task": None, "event": "unsubscribed"},
        "out_of_office": {"stop": False, "suppress": False, "task": None, "event": "out_of_office",
                          "reschedule_days": 5},
        "other": {"stop": True, "suppress": False, "task": ("Medium", 1), "event": "replied"},
    }[classification]

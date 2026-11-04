"""Starter templates and built-in sections for the template builder (pure: no Frappe imports).

A starter is a complete, working example for each channel that suits it: a person picks one, then makes it theirs.
Links are written as ``https://[BOOKING LINK]`` and similar, so the pre-send checks and the approval step both say what is
still to fill before anything can go out. Nothing here states a figure, a price or a result.

A test builds every starter through the builder's own checks, so a starter can never be one the builder would refuse.
"""

from __future__ import annotations

BOOKING = "https://[BOOKING LINK]"
OPT_OUT_FOOTER = "Reply STOP to unsubscribe"


def _sign(closing: str = "Best,") -> dict:
    return {"type": "signature", "closing": closing, "name": "{{owner_name|our team}}", "title": "",
            "company": "{{company}}", "phone": "", "email": ""}


def _button(label: str, url: str = BOOKING) -> dict:
    return {"type": "button", "label": label, "url": url}


def _quick(*labels: str) -> list[dict]:
    return [{"kind": "quick", "label": label} for label in labels]


STARTERS = [
    {
        "id": "post_demo", "name": "Post-demo follow-up", "meta": "Email, SMS, WhatsApp, LinkedIn", "goal": "Book a meeting",
        "Email": {
            "subject": "Your next step after the demo, {{first_name|there}}",
            "preheader": "A short plan built around how your team works today",
            "variants": ["A quick follow-up for {{business_name|your team}}", "Questions after the demo?"],
            "blocks": [
                {"type": "heading", "level": 2, "text": "Hi {{first_name|there}}, thank you for your time"},
                {"type": "text", "text": "Thank you for joining the demo. {{personal_line}}\n\nHere is a short plan for "
                                          "{{business_name|your business}}: what to set up first, who needs to be involved, and "
                                          "what you will see in the first weeks."},
                _button("Book a 15-minute call"), _sign(),
            ],
        },
        "SMS": {"text": "Hi {{first_name|there}}, it's {{sender_name|our team}} from {{company|our company}}. Thanks for the "
                        "demo. Book a short call here: [SHORT LINK]. Reply STOP to opt out.",
                "keyword": "STOP", "window": "09:00-21:00"},
        "WhatsApp": {"header_type": "None", "header": "", "category": "Marketing",
                     "body": "Hi {{first_name|there}}, this is {{sender_name|our team}}. Thanks for joining the demo. Would you "
                             "like a short call to plan the next steps?",
                     "footer": OPT_OUT_FOOTER, "buttons": _quick("Book a call", "Send details", "Not now"),
                     "samples": {"first_name": "Rahim", "sender_name": "Nadia"}},
        "LinkedIn": {"subject": "Following up on our demo",
                     "text": "Hi {{first_name|there}}, thank you for your time at the demo. I put together a short plan for "
                             "{{business_name|your business}}. Would a quick call this week help?"},
    },
    {
        "id": "stalled", "name": "Stalled deal revival", "meta": "Email and WhatsApp", "goal": "Re-engage",
        "Email": {
            "subject": "Still on your list, {{first_name|there}}?",
            "preheader": "One question, and an easy way to pick this up again",
            "variants": ["A quick idea for {{business_name|your team}}", "Should we close this out?"],
            "blocks": [
                {"type": "heading", "level": 2, "text": "Is this still a priority?"},
                {"type": "text", "text": "Hi {{first_name|there}}, we spoke a while ago about {{business_name|your business}} and "
                                          "things went quiet. That is completely fine: priorities change.\n\nIf it is still on "
                                          "your list, a short call is enough to pick it up. If not, just tell me and I will "
                                          "stop writing."},
                _button("Choose a time"), _sign(),
            ],
        },
        "WhatsApp": {"header_type": "None", "header": "", "category": "Marketing",
                     "body": "Hi {{first_name|there}}, it is {{sender_name|our team}}. We spoke a while ago and things went "
                             "quiet. Is this still something you want to look at?",
                     "footer": OPT_OUT_FOOTER, "buttons": _quick("Yes, call me", "Later", "Not now"),
                     "samples": {"first_name": "Rahim", "sender_name": "Nadia"}},
    },
    {
        "id": "event", "name": "Event or webinar invite", "meta": "Email, SMS", "goal": "Event invite",
        "Email": {
            "subject": "You are invited: [EVENT NAME]",
            "preheader": "Save your seat",
            "variants": ["{{first_name|there}}, join us at [EVENT NAME]"],
            "blocks": [
                {"type": "heading", "level": 1, "text": "Join us at [EVENT NAME]"},
                {"type": "columns", "left": "When\n[DATE AND TIME]", "right": "Where\n[PLACE OR LINK]"},
                {"type": "text", "text": "Hi {{first_name|there}}, we would like {{business_name|your team}} to be there. You "
                                          "will see how the work gets done and can ask your questions."},
                _button("Reserve my seat", "https://[RSVP LINK]"), _sign(),
            ],
        },
        "SMS": {"text": "Hi {{first_name|there}}, you are invited to [EVENT NAME] on [DATE]. Reserve your seat: [SHORT LINK]. "
                        "Reply STOP to opt out.", "keyword": "STOP", "window": "09:00-21:00"},
    },
    {
        "id": "renewal", "name": "Renewal reminder", "meta": "Email and SMS", "goal": "Re-engage",
        "Email": {
            "subject": "Your renewal for {{business_name|your business}}",
            "preheader": "A reminder, and how to renew",
            "variants": ["{{first_name|there}}, a reminder about your renewal"],
            "blocks": [
                {"type": "heading", "level": 2, "text": "Hi {{first_name|there}}, a quick reminder"},
                {"type": "text", "text": "Your plan with us is due for renewal on [RENEWAL DATE]. If you would like to continue, "
                                          "or change anything first, you can reply to this email or book a short call."},
                _button("Talk about my renewal"), _sign(),
            ],
        },
        "SMS": {"text": "Hi {{first_name|there}}, your plan renews on [RENEWAL DATE]. Questions? Call us or reply here. "
                        "Reply STOP to opt out.", "keyword": "STOP", "window": "09:00-21:00"},
    },
    {
        "id": "welcome", "name": "New lead welcome", "meta": "Email and WhatsApp", "goal": "Book a meeting",
        "Email": {
            "subject": "Welcome, {{first_name|there}}",
            "preheader": "What happens next, in three short steps",
            "variants": ["Thanks for getting in touch, {{first_name|there}}"],
            "blocks": [
                {"type": "heading", "level": 2, "text": "Thanks for getting in touch"},
                {"type": "text", "text": "Hi {{first_name|there}}, thank you for your interest. {{personal_line}}"},
                {"type": "dynamic", "fallback": "Tell us how your team handles orders and stock today, and we will show what "
                                                "would change.",
                 "rules": [{"field": "industry", "op": "contains", "value": "pharma",
                            "text": "If you distribute medicines, we will show how orders and stock can be kept in one place."}]},
                _button("Book a 15-minute call"), _sign(),
            ],
        },
        "WhatsApp": {"header_type": "None", "header": "", "category": "Marketing",
                     "body": "Hi {{first_name|there}}, thanks for getting in touch. This is {{sender_name|our team}}. Can we "
                             "find a few minutes to talk about what you need?",
                     "footer": OPT_OUT_FOOTER, "buttons": _quick("Book a call", "Send details", "Not now"),
                     "samples": {"first_name": "Rahim", "sender_name": "Nadia"}},
    },
]

# Sections that are always there to insert in the Blocks tab; a Company's own sections are stored with it.
BUILTIN_SECTIONS = [
    {"id": "signature", "name": "Signature card", "blocks": [_sign()]},
    {"id": "booking", "name": "Booking call to action",
     "blocks": [{"type": "text", "text": "Want to see how it fits your team?"}, _button("Book a 15-minute call")]},
    {"id": "follow", "name": "Follow us",
     "blocks": [{"type": "social", "links": [{"label": "LinkedIn", "url": "https://[LINKEDIN PAGE]"}]}]},
]


def starter_summaries() -> list[dict]:
    """What the Templates tab lists: name, what it contains and for which channels."""
    channels = ("Email", "SMS", "WhatsApp", "LinkedIn")
    return [{"id": s["id"], "name": s["name"], "meta": s["meta"], "goal": s["goal"],
             "channels": [c for c in channels if c in s]} for s in STARTERS]


def starter_content(starter_id: str, channel: str) -> dict | None:
    """A copy of the starter's content for one channel, or None when that starter has none for it."""
    import copy

    for starter in STARTERS:
        if starter["id"] == starter_id and channel in starter:
            return copy.deepcopy(starter[channel])
    return None

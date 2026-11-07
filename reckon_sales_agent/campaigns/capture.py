"""Lead capture forms: the fields, the checks on a submission, and what the public page may know (pure: no Frappe imports).

A form is public, so every value a visitor sends is untrusted: it is trimmed, length-limited and normalised here, an email
must look like an email, and a hidden field that only a script fills in marks the submission as a bot.
"""

from __future__ import annotations

import re

from reckon_sales_agent.discovery.normalize import normalize_email, normalize_phone

# key: (default label, input type, longest value)
FIELD_CATALOG: dict[str, tuple[str, str, int]] = {
    "email": ("Email", "email", 140),
    "first_name": ("First name", "text", 60),
    "last_name": ("Last name", "text", 60),
    "phone": ("Phone", "tel", 30),
    "business_name": ("Company", "text", 140),
    "city": ("City", "text", 80),
    "industry": ("Industry", "text", 80),
}
DEFAULT_FIELDS = ("email", "first_name")
FORM_TYPES = ("Embedded", "Popup", "Hosted page")
POPUP_TRIGGERS = ("Delay", "Scroll", "Exit intent")
HONEYPOT = "hp_website"
DEFAULT_ACCENT = "#4f46e5"
MAX_PER_HOUR = 30  # submissions from one address in an hour (the page also limits per form)

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def clean_fields(rows) -> list[dict]:
    """The form's fields in order: known keys only, email always there, first and required."""
    out: list[dict] = []
    for raw in rows or []:
        if not isinstance(raw, dict) or raw.get("key") not in FIELD_CATALOG or any(f["key"] == raw["key"] for f in out):
            continue
        default = FIELD_CATALOG[raw["key"]][0]
        out.append({"key": raw["key"], "label": " ".join(str(raw.get("label") or default).split())[:60] or default,
                    "required": bool(raw.get("required"))})
    out = [f for f in out if f["key"] != "email"]
    label = next((" ".join(str(r.get("label") or "").split())[:60] for r in rows or []
                  if isinstance(r, dict) and r.get("key") == "email"), "") or FIELD_CATALOG["email"][0]
    return [{"key": "email", "label": label, "required": True}] + out


def accent(value) -> str:
    return value if _HEX.match(str(value or "")) else DEFAULT_ACCENT


def safe_redirect(url) -> str:
    """A thank-you address: https only, no spaces or quotes ('' when it is not usable)."""
    text = str(url or "").strip()
    return text if text.lower().startswith("https://") and len(text) <= 500 and not re.search(r"[\s\"'<>]", text) else ""


def validate_submission(fields, data, *, require_consent: bool = True, ask_sms: bool = False,
                        ask_whatsapp: bool = False) -> tuple[dict, dict]:
    """(clean values, {field: message}). ``bot`` is set (and nothing else matters) when the hidden field was filled in."""
    data = data if isinstance(data, dict) else {}
    if str(data.get(HONEYPOT) or "").strip():
        return {"bot": True}, {}
    clean: dict = {}
    errors: dict = {}
    for field in clean_fields(fields):
        key = field["key"]
        _label, _kind, longest = FIELD_CATALOG[key]
        raw = " ".join(str(data.get(key) or "").split())
        if len(raw) > longest:
            errors[key] = f"{field['label']} is too long."
            continue
        if key == "email":
            value = normalize_email(raw)
            if not value:
                errors[key] = "Enter a valid email address."
                continue
        elif key == "phone":
            value = normalize_phone(raw) if raw else ""
            if raw and not value:
                errors[key] = "Enter a valid phone number."
                continue
        else:
            value = raw
        if field["required"] and not value:
            errors[key] = f"{field['label']} is required."
        elif value:
            clean[key] = value
    consent = str(data.get("consent") or "").lower() in ("1", "true", "on", "yes")
    if require_consent and not consent:
        errors["consent"] = "Please tick the box to agree."
    clean["consent"] = consent
    clean["sms_opt_in"] = bool(ask_sms and clean.get("phone") and str(data.get("sms_opt_in") or "").lower() in ("1", "true", "on", "yes"))
    clean["whatsapp_opt_in"] = bool(ask_whatsapp and clean.get("phone") and
                                    str(data.get("whatsapp_opt_in") or "").lower() in ("1", "true", "on", "yes"))
    return clean, errors


def person_name(clean: dict) -> str:
    return " ".join(p for p in (clean.get("first_name"), clean.get("last_name")) if p)


def rate_limited(recent: int, limit: int = MAX_PER_HOUR) -> bool:
    return recent >= limit


def consent_source(form_name: str, slug: str, on: str) -> str:
    """What is stored as the consent record: which form, and when."""
    return f"Signup form '{form_name}' ({slug}) on {on}"[:140]

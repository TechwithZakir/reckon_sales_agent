"""Normalisation, source policy and duplicate fingerprints (pure: no Frappe imports)."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date, timedelta
from difflib import SequenceMatcher
from urllib.parse import urlsplit

# Suffixes that do not distinguish one business from another.
NAME_NOISE = {
    "ltd", "limited", "pvt", "private", "plc", "co", "company", "inc", "llc", "corp",
    "corporation", "the", "and", "&", "bd", "bangladesh", "enterprise", "enterprises",
}

# Fields a prospect can carry; anything else from a connector is dropped.
PROSPECT_FIELDS = (
    "business_name", "industry", "website", "email", "phone", "address", "city", "country",
)


def normalize_space(value) -> str:
    return " ".join(str(value or "").split())


def normalize_name(name: str | None) -> str:
    text = unicodedata.normalize("NFKC", normalize_space(name)).lower()
    text = re.sub(r"[^\w\s&]", " ", text)
    words = [w for w in text.split() if w not in NAME_NOISE]
    return " ".join(words)


def normalize_domain(url_or_domain: str | None) -> str:
    value = normalize_space(url_or_domain).lower()
    if not value:
        return ""
    if "://" not in value:
        value = "http://" + value
    try:
        host = urlsplit(value).hostname or ""
    except ValueError:
        return ""
    host = host.strip(".")
    if host.startswith("www."):
        host = host[4:]
    # Social and directory hosts identify a platform, not the business.
    if host in {"facebook.com", "m.facebook.com", "instagram.com", "linkedin.com", "google.com",
                "maps.google.com", "goo.gl", "bit.ly", "wa.me", "youtube.com"}:
        return ""
    return host


def normalize_phone(phone: str | None, default_country: str = "880") -> str:
    """E.164-style digits for Bangladesh-first numbers: '01711-123456' -> '+8801711123456'."""
    digits = re.sub(r"\D", "", str(phone or ""))
    if not digits:
        return ""
    if digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0") and default_country == "880":
        digits = "880" + digits[1:]
    elif len(digits) == 10 and default_country == "880" and digits.startswith("1"):
        digits = "880" + digits
    if len(digits) < 8 or len(digits) > 15:
        return ""
    return "+" + digits


def normalize_email(email: str | None) -> str:
    value = normalize_space(email).lower()
    return value if re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", value) else ""


def mask(value: str) -> str:
    """For lists and logs: 'sales@acme.com' -> 's***@acme.com', '+88017...' -> '+880******56'."""
    if "@" in value:
        local, _, domain = value.partition("@")
        return f"{local[:1]}***@{domain}"
    return value[:4] + "*" * max(len(value) - 6, 0) + value[-2:] if len(value) > 6 else "***"


def value_hash(entry_type: str, value: str) -> str:
    normal = {
        "Email": normalize_email,
        "Phone": normalize_phone,
        "Domain": normalize_domain,
    }[entry_type](value)
    return hashlib.sha256(f"{entry_type}:{normal}".encode()).hexdigest() if normal else ""


def fingerprint(record: dict) -> str:
    """Stable key for exact duplicate checks: domain, else phone, else name+city."""
    domain = normalize_domain(record.get("website"))
    if domain:
        return f"domain:{domain}"
    phone = normalize_phone(record.get("phone"))
    if phone:
        return f"phone:{phone}"
    return f"name:{normalize_name(record.get('business_name'))}|{normalize_name(record.get('city'))}"


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, normalize_name(a), normalize_name(b)).ratio()


def apply_field_policy(fields: dict, policy: dict, retrieved_at: str, source: str, today: date) -> tuple[dict, dict, date | None]:
    """Keep only fields the source lets us store; return (fields, provenance, retention_until).

    ``policy`` maps field -> {"persist": bool, "retention_days": int|None,
    "attribution": str|None}. A field without a policy entry is not stored:
    the policy must opt fields in, so a new connector field fails closed.
    """
    kept: dict = {}
    provenance: dict = {}
    retention_until: date | None = None
    for field in PROSPECT_FIELDS:
        value = normalize_space(fields.get(field))
        if not value:
            continue
        rule = policy.get(field) or {}
        if not rule.get("persist"):
            continue
        kept[field] = value
        days = rule.get("retention_days")
        provenance[field] = {
            "source": source,
            "retrieved_at": retrieved_at,
            "retention_days": days,
            "attribution": rule.get("attribution"),
        }
        if days:
            expiry = today + timedelta(days=int(days))
            retention_until = min(retention_until, expiry) if retention_until else expiry
    return kept, provenance, retention_until

"""Tags on people (pure: no Frappe imports).

A tag is a short lowercase label such as ``newsletter`` or ``renewal-2026``. People carry them as comma separated text, so
forms, imports, automations and hands can all add them, and segments and automations can read them.
"""

from __future__ import annotations

import re

MAX_TAGS = 30
MAX_LENGTH = 40
_ALLOWED = re.compile(r"[^a-z0-9ঀ-৿ _:.&-]")  # letters, digits, Bangla, and a few separators


def clean(tag) -> str:
    """One tag: lowercase, trimmed, no odd characters, at most 40 characters ('' when nothing is left)."""
    text = _ALLOWED.sub("", str(tag or "").strip().lower())
    return " ".join(text.split())[:MAX_LENGTH].strip()


def normalize(value) -> list[str]:
    """Tags from text (comma or line separated) or a list: cleaned, without repeats, in order, at most 30."""
    parts = value if isinstance(value, (list, tuple, set)) else str(value or "").replace("\n", ",").split(",")
    out: list[str] = []
    for part in parts:
        tag = clean(part)
        if tag and tag not in out:
            out.append(tag)
    return out[:MAX_TAGS]


def to_text(tags) -> str:
    return ", ".join(normalize(tags))


def add(current, new) -> list[str]:
    return normalize(list(normalize(current)) + list(normalize(new)))


def remove(current, gone) -> list[str]:
    drop = set(normalize(gone))
    return [tag for tag in normalize(current) if tag not in drop]


def has(current, tag) -> bool:
    wanted = clean(tag)
    return bool(wanted) and wanted in normalize(current)

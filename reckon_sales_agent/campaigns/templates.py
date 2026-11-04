"""Message templates: merge fields with fallbacks, dynamic content and plain-text reading (pure: no Frappe imports).

Templates are tenant-authored, so they are never run through Jinja: only the listed fields are replaced, values are
HTML-escaped, and unknown fields are removed. A field can carry a fallback for the people it has no value for, so a
missing record never sends a blank greeting: ``{{first_name|there}}``.

A dynamic block shows different content to different people (for example one paragraph for pharma businesses and another
for everyone else). The builder writes it as a ``<div data-rsa-dynamic="...">`` holding the fallback content, and the
campaign engine picks the matching rule for each person when it writes their message.
"""

from __future__ import annotations

import html
import json
import re

# (group, key, label, sample value for previews, fallback offered when the field is inserted, needs a fallback)
FIELDS = (
    ("Business", "business_name", "Business name", "Acme Foods Ltd.", "your business", True),
    ("Business", "city", "City", "Dhaka", "your city", True),
    ("Business", "industry", "Industry", "food distribution", "your industry", True),
    ("Business", "website", "Website", "acmefoods.com", "", False),
    ("Contact", "first_name", "First name", "Rahim", "there", True),
    ("Contact", "contact_name", "Full name", "Rahim Uddin", "", True),
    ("Your team", "sender_name", "Sender name", "Nadia", "our team", False),
    ("Your team", "owner_name", "Record owner", "Nadia Rahman", "our team", True),
    ("Your team", "company", "Your company", "Reckon Technologies Ltd.", "", False),
    ("Campaign and AI", "offer", "Offer", "a 15-minute walkthrough", "", True),
    ("Campaign and AI", "personal_line", "AI opening line", "I saw you recently opened a second warehouse.", "", False),
)
PLACEHOLDERS = tuple(field[1] for field in FIELDS)
SAMPLES = {field[1]: field[3] for field in FIELDS}
NEEDS_FALLBACK = frozenset(field[1] for field in FIELDS if field[5])

PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-z_]+)\s*(?:\|([^{}]*?))?\s*\}\}")
# The template builder marks the HTML it writes, so the engine uses it as it is instead of wrapping it as plain text.
BUILDER_MARK = 'data-rsa-builder="1"'
DYNAMIC_ATTR = "data-rsa-dynamic"
DYNAMIC_RE = re.compile(r'<div ' + DYNAMIC_ATTR + r'="([^"]*)"([^>]*)>(.*?)</div>', re.S)
RULE_OPS = ("is", "contains", "not_empty", "empty")


def render(template: str, values: dict, *, escape: bool = True) -> str:
    """Fill the fields. A field with no value uses its fallback; an unknown field is removed."""
    def replace(match: re.Match) -> str:
        key = match.group(1)
        if key not in PLACEHOLDERS:
            return ""
        value = str(values.get(key) or "").strip() or (match.group(2) or "").strip()
        return html.escape(value) if escape else value

    return PLACEHOLDER_RE.sub(replace, template or "")


def sample_values() -> dict:
    return dict(SAMPLES)


def missing_fallbacks(text: str) -> list[str]:
    """Fields in the text that can be empty for some people and carry no fallback, in order of first use."""
    found: list[str] = []
    for match in PLACEHOLDER_RE.finditer(text or ""):
        name = match.group(1)
        if name in NEEDS_FALLBACK and not (match.group(2) or "").strip() and name not in found:
            found.append(name)
    return found


def is_builder_html(text: str) -> bool:
    return (text or "").lstrip().startswith("<div") and BUILDER_MARK in (text or "")[:120]


def text_to_html(text: str) -> str:
    """Rendered plain text (already escaped) to simple paragraphs."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
    return "".join(f"<p>{p.replace(chr(10), '<br>')}</p>" for p in paragraphs)


def footer(sender: str, address: str | None, unsubscribe_url: str) -> str:
    parts = [html.escape(sender or "")]
    if address:
        parts.append(html.escape(address))
    parts.append(f'<a href="{html.escape(unsubscribe_url, quote=True)}">Unsubscribe</a>')
    return '<p style="color:#888;font-size:12px">' + " · ".join(p for p in parts if p) + "</p>"


# Dynamic content ------------------------------------------------------------


def dynamic_attribute(spec: dict) -> str:
    """The attribute value that carries a dynamic block's rules (JSON, HTML-escaped)."""
    return html.escape(json.dumps(spec, ensure_ascii=False, separators=(",", ":")), quote=True)


def rule_matches(rule: dict, values: dict) -> bool:
    field = rule.get("field")
    if field not in PLACEHOLDERS or rule.get("op") not in RULE_OPS:
        return False
    actual = str(values.get(field) or "").strip().lower()
    expected = str(rule.get("value") or "").strip().lower()
    op = rule["op"]
    if op == "empty":
        return not actual
    if op == "not_empty":
        return bool(actual)
    if not expected:
        return False
    return actual == expected if op == "is" else expected in actual


def resolve_dynamic(body: str, values: dict) -> str:
    """Pick, for one person, the content of each dynamic block: the first rule that matches, else the fallback."""
    def pick(match: re.Match) -> str:
        try:
            spec = json.loads(html.unescape(match.group(1)))
        except ValueError:
            return match.group(0)  # unreadable rules: the fallback stays
        chosen = match.group(3)
        for rule in spec.get("rules") or []:
            if rule_matches(rule, values):
                chosen = str(rule.get("html") or "")
                break
        return f"<div{match.group(2)}>{chosen}</div>"

    return DYNAMIC_RE.sub(pick, body or "")


def dynamic_alternatives(body: str) -> list[str]:
    """The HTML of every rule's content: checkers read these too, because any of them can be sent."""
    out: list[str] = []
    for match in DYNAMIC_RE.finditer(body or ""):
        try:
            spec = json.loads(html.unescape(match.group(1)))
        except ValueError:
            continue
        out.extend(str(rule.get("html") or "") for rule in spec.get("rules") or [])
    return out


# Reading ---------------------------------------------------------------------


def _strip_tags(markup: str) -> str:
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", markup or "")
    text = re.sub(r"(?i)<br\s*/?>|</(p|h[1-6]|div|tr|li|table)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    lines = (" ".join(line.split()) for line in html.unescape(text).splitlines())
    return "\n".join(line for line in lines if line)


def strip_html(body: str) -> str:
    """The words in builder HTML, for the content checks: styles and tags are not content. Every dynamic
    alternative is included, because any of them can reach a customer."""
    parts = [_strip_tags(body)] + [_strip_tags(alternative) for alternative in dynamic_alternatives(body)]
    return "\n".join(part for part in parts if part)

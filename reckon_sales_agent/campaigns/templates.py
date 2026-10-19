"""Message templates with plain {{placeholder}} substitution (pure: no Frappe imports).

Templates are tenant-authored, so they are never run through Jinja: only the
listed placeholders are replaced, values are HTML-escaped, and unknown
placeholders are removed.
"""

from __future__ import annotations

import html
import re

PLACEHOLDERS = ("business_name", "city", "industry", "sender_name", "offer", "personal_line", "company")
PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")


def render(template: str, values: dict, *, escape: bool = True) -> str:
    def replace(match: re.Match) -> str:
        key = match.group(1)
        if key not in PLACEHOLDERS:
            return ""
        value = str(values.get(key) or "")
        return html.escape(value) if escape else value

    return PLACEHOLDER_RE.sub(replace, template or "")


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

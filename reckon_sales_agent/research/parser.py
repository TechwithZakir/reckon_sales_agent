"""Turn untrusted HTML into plain text and contact details (pure: no Frappe imports).

Scripts, styles, forms and hidden elements are dropped; nothing is executed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from reckon_sales_agent.discovery.normalize import normalize_email, normalize_phone

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:\+?880[\s-]?|0)1[3-9]\d{2}[\s-]?\d{3}[\s-]?\d{3}|\+?\d[\d\s().-]{8,16}\d")
MAX_TEXT = 20_000
INTERESTING_PATHS = ("about", "contact", "service", "product", "company", "career", "job", "team",
                     "আমাদের", "যোগাযোগ")


@dataclass
class ParsedPage:
    url: str
    title: str = ""
    description: str = ""
    text: str = ""
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    internal_links: list[str] = field(default_factory=list)


def parse_html(html: str, url: str) -> ParsedPage:
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "noscript", "template", "iframe", "svg", "form", "object", "embed"]):
        tag.decompose()
    for tag in soup.select('[hidden], [aria-hidden="true"], [style*="display:none"], [style*="display: none"]'):
        tag.decompose()
    page = ParsedPage(url=url)
    page.title = " ".join((soup.title.string or "").split())[:200] if soup.title and soup.title.string else ""
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        page.description = " ".join(meta["content"].split())[:500]
    text = " ".join(soup.get_text(" ").split())
    page.text = text[:MAX_TEXT]

    emails = {normalize_email(m) for m in EMAIL_RE.findall(text)}
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if href.lower().startswith("mailto:"):
            emails.add(normalize_email(href[7:].split("?")[0]))
    page.emails = sorted(e for e in emails if e and not e.endswith((".png", ".jpg", ".webp")))
    page.phones = sorted({p for p in (normalize_phone(m) for m in PHONE_RE.findall(text)) if p})

    base_host = (urlsplit(url).hostname or "").lower()
    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        target = urljoin(url, anchor["href"]).split("#")[0]
        parts = urlsplit(target)
        if parts.scheme in ("http", "https") and (parts.hostname or "").lower() == base_host:
            path = parts.path.lower()
            if any(word in path for word in INTERESTING_PATHS) and target not in links:
                links.append(target)
    page.internal_links = links[:20]
    return page

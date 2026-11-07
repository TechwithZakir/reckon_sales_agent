"""Open and click tracking for campaign messages (pure: no Frappe imports).

Every tracked link is a short code stored with the message it belongs to, so a click can be traced back to the
recipient and the campaign. The code is the only thing in the link: the destination is looked up on our side, so a
link can only ever lead where we put it (it is not an open redirect).

* Email: each ``href`` is replaced by a tracked link, and a 1x1 image records an open.
* SMS and WhatsApp: each plain-text link is replaced by a short tracked link.
* The unsubscribe link and our own tracked links are never rewritten.

Opens are approximate: some mail apps load images in advance for privacy (Apple Mail), and some security scanners
open links. Those visits are filtered when they identify themselves (``is_bot``) and the Studio says so.
"""

from __future__ import annotations

import html
import re
import secrets

# A 1x1 transparent GIF.
GIF = bytes.fromhex("47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b")

HREF_RE = re.compile(r"""(<a\b[^>]*?\bhref=)(["'])(https?://[^"']+)\2""", re.I)
TEXT_URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.I)
SKIP_MARKERS = ("/api/method/reckon_sales_agent.api.unsubscribe", "/l/", "api_track.open")
BOT_RE = re.compile(
    r"bot|spider|crawl|preview|scanner|facebookexternalhit|slackbot|whatsapp|telegram|proofpoint|mimecast|barracuda|"
    r"symantec|trendmicro|safelinks|python-requests|curl/|wget|headless|go-http-client|java/|okhttp|libwww|monitor",
    re.I)


def valid_domain(value) -> str:
    """A host name for tracked links ('track.example.com'), or '' when it is not one: no scheme, path or port, lowercase."""
    text = str(value or "").strip().lower()
    if not text or len(text) > 253 or "." not in text:
        return ""
    labels = text.split(".")
    ok = all(re.fullmatch(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels) and re.fullmatch(r"[a-z]{2,24}", labels[-1])
    return text if ok else ""


def new_code() -> str:
    """A short unguessable code: 8 characters of URL-safe text."""
    return secrets.token_urlsafe(6)


def should_track(url: str) -> bool:
    """http(s) links only; never the unsubscribe link or one of our own tracked links."""
    return url.lower().startswith(("http://", "https://")) and not any(marker in url for marker in SKIP_MARKERS)


def rewrite_html_links(body: str, make_link) -> str:
    """Replace each tracked-worthy ``href`` in HTML. ``make_link(url)`` returns the tracked address."""
    def swap(match: re.Match) -> str:
        url = html.unescape(match.group(3))
        if not should_track(url):
            return match.group(0)
        return f"{match.group(1)}{match.group(2)}{html.escape(make_link(url), quote=True)}{match.group(2)}"

    return HREF_RE.sub(swap, body or "")


def rewrite_text_links(body: str, make_link) -> str:
    """Replace each plain-text link (SMS, WhatsApp). Trailing punctuation stays with the sentence, not the link."""
    def swap(match: re.Match) -> str:
        url = match.group(0)
        trailing = ""
        while url and url[-1] in ".,;:!?":
            # A trailing ";" can end an entity such as &amp; inside the link, so only strip it if it is not one.
            if url[-1] == ";" and re.search(r"&[#\w]+;$", url):
                break
            trailing, url = url[-1] + trailing, url[:-1]
        if not should_track(url):
            return match.group(0)
        return make_link(html.unescape(url)) + trailing

    return TEXT_URL_RE.sub(swap, body or "")


def pixel_tag(url: str) -> str:
    return (f'<img src="{html.escape(url, quote=True)}" width="1" height="1" alt="" '
            'style="display:none;border:0;width:1px;height:1px">')


def add_pixel(body: str, url: str) -> str:
    """The open-tracking image goes at the end of the message."""
    return (body or "") + pixel_tag(url)


def is_bot(user_agent: str | None) -> bool:
    """A visit that says it is a scanner, a preview fetcher or a script, or that says nothing at all."""
    agent = (user_agent or "").strip()
    return not agent or bool(BOT_RE.search(agent))

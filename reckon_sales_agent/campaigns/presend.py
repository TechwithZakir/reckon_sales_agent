"""Pre-send checks: advice beside the builder before a template is used (pure: no Frappe imports).

These are not the rules that stop a template being approved (``campaigns.builder.check_*`` are those). They are what a
careful person would look at last: is the footer complete, does every field have a fallback, does every image have alt
text, is anything still a placeholder. Each check is ``{"ok": bool, "label": str}``; the label says what is wrong when
it is not ok.
"""

from __future__ import annotations

import re

from reckon_sales_agent.campaigns import builder
from reckon_sales_agent.campaigns.templates import missing_fallbacks

# Text in capitals inside square brackets, such as [PRODUCT AREA] or [SHORT LINK], is a placeholder still to fill.
BRACKET_RE = re.compile(r"\[[A-Z][A-Z0-9 _\-]{2,}\]")
SUBJECT_GOOD = 60
STOP_WORDS = re.compile(r"\b(stop|unsubscribe|opt[- ]?out|বন্ধ)\b", re.I)


def _check(ok: bool, good: str, bad: str) -> dict:
    return {"ok": bool(ok), "label": good if ok else bad}


def bracket_placeholders(*texts) -> list[str]:
    found: list[str] = []
    for text in texts:
        for match in BRACKET_RE.findall(str(text or "")):
            if match not in found:
                found.append(match)
    return found


def _fallback_check(text: str) -> dict:
    missing = missing_fallbacks(text)
    return _check(not missing, "Every merge field has a fallback value",
                  "Add a fallback to: " + ", ".join(missing) + " (for example {{first_name|there}})")


def _bracket_check(*texts) -> dict:
    found = bracket_placeholders(*texts)
    return _check(not found, "No placeholders left to fill", "Placeholders still to fill: " + ", ".join(found))


def email(subject: str, blocks: list[dict], variants=(), *, has_address: bool = True) -> list[dict]:
    variants = [str(v) for v in variants]
    text = builder.all_text(subject, blocks, variants)
    urls = [str(u) for b in blocks or [] for u in builder.block_urls(b) if u]
    longest = max([len(subject or ""), *(len(v) for v in variants)])
    unlabelled = sum(1 for b in blocks or []
                     if b.get("type") == "image" and b.get("src") and not (b.get("alt") or "").strip()
                     or b.get("type") == "product" and b.get("image") and not (b.get("alt") or "").strip())
    insecure = [u for u in urls if u and not u.startswith("https://")]
    return [
        _check(has_address, "Unsubscribe link and your business address are added to the footer",
               "Add your business address in Sales Agent Settings: it goes in the footer of every email"),
        _check(longest <= SUBJECT_GOOD, f"Subject line is {SUBJECT_GOOD} characters or fewer",
               f"A subject line is {longest} characters; under {SUBJECT_GOOD} shows in full on a phone"),
        _fallback_check(text),
        _check(not unlabelled, "Every image has alt text", f"{unlabelled} image(s) need alt text"),
        _check(not insecure, "Every link uses https://", "Some links do not use https://"),
        _check(any(b.get("type") in ("button", "product") for b in blocks or []), "There is a button for the next step",
               "Add a button so people know what to do next"),
        _bracket_check(text, *urls),
    ]


def sms(text: str, keyword: str = "STOP", window: str = "") -> list[dict]:
    parts = builder.sms_parts(text or "")
    word = (keyword or "STOP").strip()
    return [
        _check(re.search(rf"\b{re.escape(word)}\b", text or "", re.I) or STOP_WORDS.search(text or ""),
               "Opt-out instructions are included", f"Add an opt-out line, such as 'Reply {word} to opt out'"),
        _check(parts <= 2, f"{parts} SMS part(s): cheap and easy to read", f"{parts} SMS parts: shorten it to two or fewer"),
        _fallback_check(text or ""),
        _check(bool((window or "").strip()), "Sending hours are set, so nobody is texted at night",
               "Set the hours this SMS may be sent (for example 09:00-21:00)"),
        _bracket_check(text),
    ]


def whatsapp(header: str, body: str, footer: str, buttons: list[dict], samples: dict | None = None, *,
             category: str = "", header_type: str = "Text") -> list[dict]:
    samples = samples or {}
    params = builder.merge_tags(body or "")
    unsampled = [p for p in params if not str(samples.get(p) or "").strip()]
    optout = bool(STOP_WORDS.search(footer or "")) or any(STOP_WORDS.search(str(b.get("label") or "")) for b in buttons or [])
    return [
        _check(not unsampled, "Every variable has a sample value for Meta to review",
               "Add a sample value for: " + ", ".join(unsampled)),
        _check(bool(category), "A category is chosen (Marketing or Utility)", "Choose a category: Meta reviews it"),
        _check(optout, "People can opt out (footer or a button)", "Add an opt-out line to the footer, such as 'Reply STOP to unsubscribe'"),
        _fallback_check(body or ""),
        _bracket_check(header, body, footer),
    ]


def linkedin(subject: str, text: str) -> list[dict]:
    full = f"{subject or ''}\n{text or ''}"
    return [
        _fallback_check(full),
        _check(len(text or "") <= 1000, "Short enough to read in full", "Over 1000 characters: shorter messages get more replies"),
        _bracket_check(full),
    ]


def summary(items: list[dict]) -> dict:
    open_items = [i for i in items if not i["ok"]]
    return {"ok": not open_items, "open": len(open_items), "total": len(items)}

"""A pre-send spam score for an email (pure: no Frappe imports).

It is advice, not a filter: mailbox providers weigh hundreds of signals we cannot see, so this only counts the ones a writer
controls, each with the reason and what to change. The score is 0 to 10 (higher is worse): Low under 3, Medium under 6, High
above. It never stops an email; it tells the person writing it what a careful reader would fix.
"""

from __future__ import annotations

import re

LOW, MEDIUM = 3.0, 6.0
PHRASES = {
    "free": 0.7, "winner": 1.2, "you have won": 1.5, "congratulations": 0.8, "guarantee": 0.8, "guaranteed": 0.8, "act now": 1.2,
    "click here": 1.0, "buy now": 0.8, "order now": 0.8, "limited time": 0.8, "urgent": 0.8, "100%": 0.8, "risk-free": 1.0,
    "no obligation": 0.8, "cash": 0.6, "earn money": 1.2, "make money": 1.2, "double your": 1.2, "lowest price": 0.8,
    "once in a lifetime": 1.2, "this is not spam": 2.0, "dear friend": 1.0, "no cost": 0.8, "special promotion": 0.8,
    "lottery": 1.5, "লটারি": 1.5, "বিনামূল্যে": 0.7,
}
SHORTENERS = ("bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd", "cutt.ly", "buff.ly", "rebrand.ly", "shorturl.at")
_WORD = re.compile(r"[A-Za-z]{4,}")
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")


def _item(points: float, text: str, fix: str) -> dict:
    return {"points": round(points, 1), "text": text, "fix": fix}


def _phrases(text: str, cap: float) -> tuple[float, list[str]]:
    lowered = text.lower()
    hits = [(phrase, weight) for phrase, weight in PHRASES.items()
            if re.search(rf"(?<![a-z]){re.escape(phrase)}(?![a-z])", lowered)]
    return min(sum(w for _p, w in hits), cap), [p for p, _w in hits]


def level(score: float) -> str:
    return "Low" if score < LOW else ("Medium" if score < MEDIUM else "High")


def score(subject: str, body: str, urls=()) -> dict:
    """{score, level, reasons: [{points, text, fix}]} for one email. ``body`` is its text; ``urls`` are its links."""
    subject, body = str(subject or "").strip(), str(body or "").strip()
    urls = [str(u) for u in urls or [] if u]
    reasons: list[dict] = []

    def add(points, text, fix):
        reasons.append(_item(points, text, fix))

    if subject:
        shouted = [w for w in _WORD.findall(subject) if w.isupper()]
        if len(shouted) >= 2:
            add(1.5, "The subject shouts in capital letters.", "Write the subject in normal sentence case.")
        if subject.count("!") >= 2:
            add(1.5, "The subject has several exclamation marks.", "Keep at most one, or none.")
        elif "!" in subject:
            add(0.5, "The subject has an exclamation mark.", "A calm subject is delivered more often.")
        if re.match(r"^\s*(re|fwd?)\s*:", subject, re.I):
            add(2.0, "The subject pretends to be a reply or a forward.", "Say plainly what the email is.")
        points, hits = _phrases(subject, 2.0)
        if hits:
            add(points, "The subject uses sales phrases: " + ", ".join(hits[:3]) + ".", "Describe the benefit in plain words.")
        if len(subject) > 80:
            add(0.5, f"The subject is {len(subject)} characters long.", "Keep it under 60 so it shows in full.")
        if len(_EMOJI.findall(subject)) > 2:
            add(0.5, "The subject has many emoji.", "Use one at most.")
        if re.search(r"https?://", subject):
            add(1.0, "The subject contains a link.", "Put links in the body.")
    else:
        add(1.0, "There is no subject.", "Write a subject line.")

    words = re.findall(r"\S+", body)
    if not words:
        add(2.0, "There is no text, only images or nothing.", "Add real text: image-only emails are often filtered.")
    else:
        points, hits = _phrases(body, 3.0)
        if hits:
            add(points, "The text uses sales phrases: " + ", ".join(hits[:4]) + ".", "Replace them with specific, honest wording.")
        letters = [c for c in body if c.isalpha()]
        caps = sum(1 for c in letters if c.isupper())
        if len(letters) > 60 and caps / len(letters) > 0.25:
            add(1.0, "A lot of the text is in capital letters.", "Use capitals only at the start of sentences.")
        if body.count("!") > 3:
            add(1.0, "The text has many exclamation marks.", "Keep them to one or two.")
        if len(words) < 20 and urls:
            add(1.0, "Very little text around the links.", "Say more: short emails that are mostly links look like spam.")
        if re.search(r"\${2,}|₹{2,}|৳{2,}|\b\d+\s*%\s*off\b", body, re.I):
            add(0.5, "The text makes price or discount claims in a loud way.", "State the offer once, plainly.")
    if len(urls) > 8:
        add(2.0, f"{len(urls)} links.", "Keep to a few links, ideally one main call to action.")
    elif len(urls) > 5:
        add(1.0, f"{len(urls)} links.", "Fewer links are safer; keep one main call to action.")
    short = [u for u in urls if any(f"//{d}" in u.lower() or f".{d}" in u.lower() for d in SHORTENERS)]
    if short:
        add(2.0, "A link shortener is used.", "Use the full address: shorteners are a common spam signal.")
    if any(u.lower().startswith("http://") for u in urls):
        add(0.5, "A link is not https.", "Use https:// links.")

    total = min(10.0, round(sum(r["points"] for r in reasons), 1))
    return {"score": total, "level": level(total), "reasons": sorted(reasons, key=lambda r: -r["points"])}


def check_line(result: dict) -> dict:
    """The score as one pre-send check ({ok, label}) for the template builder."""
    if result["level"] == "Low":
        return {"ok": True, "label": f"Spam score {result['score']:g}/10: low risk"}
    top = result["reasons"][0] if result["reasons"] else {"text": "", "fix": ""}
    return {"ok": False, "label": f"Spam score {result['score']:g}/10 ({result['level']}): {top['text']} {top['fix']}".strip()}

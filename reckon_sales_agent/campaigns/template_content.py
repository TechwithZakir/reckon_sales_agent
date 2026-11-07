"""Template content: what the builder edits, what a template stores, and the checks on it (pure: no Frappe imports).

The builder works on one ``content`` dict per channel. ``normalize`` makes whatever the browser sent safe and bounded,
``fields_to_store`` turns it into the template's fields, ``content_from_fields`` does the reverse (including for templates
written before the builder existed), and ``compile_content`` returns everything the screen shows: the problems that stop
approval, the pre-send checks, and the preview.

Content by channel:

* Email: subject, preheader, variants (up to two alternative subjects), blocks.
* SMS: text, keyword (the opt-out word), window (sending hours).
* WhatsApp: header_type, header, body, footer, buttons, samples (a value per variable), category.
* LinkedIn: subject, text.
* All: actions (what the agent does with it) and ai (the brief, goal and tone that produced the draft).
"""

from __future__ import annotations

import html
import json
import re

from reckon_sales_agent.campaigns import builder, presend, spamscore
from reckon_sales_agent.campaigns import templates as t

MAX_BLOCKS = 60
ACTIONS = ("personalize", "besttime", "followup", "handoff")
# Which agent actions work today. The others are shown as not available, so a switch never promises what the system cannot do.
ACTIONS_AVAILABLE = ("personalize",)
CATEGORIES = ("Marketing", "Utility")
BUTTON_KINDS = ("quick", "url", "phone")

# per block type: key -> maximum length
BLOCK_KEYS = {
    "heading": {"text": 300}, "text": {"text": 5000}, "image": {"src": 500, "alt": 200, "url": 500},
    "button": {"label": 80, "url": 500}, "columns": {"left": 2000, "right": 2000}, "divider": {},
    "product": {"title": 150, "text": 500, "price": 60, "image": 500, "alt": 200, "label": 60, "url": 500},
    "dynamic": {"fallback": 2000}, "signature": {"closing": 40, "name": 100, "title": 100, "company": 100, "phone": 40, "email": 120},
    "social": {}, "spacer": {},
}


def _s(value, limit: int) -> str:
    return str(value or "")[:limit]


def _block(raw) -> dict | None:
    if not isinstance(raw, dict) or raw.get("type") not in BLOCK_KEYS:
        return None
    kind = raw["type"]
    block = {"type": kind, **{key: _s(raw.get(key), cap) for key, cap in BLOCK_KEYS[kind].items()}}
    if kind == "heading":
        block["level"] = 1 if str(raw.get("level")) == "1" else 2
    if kind == "spacer":
        block["height"] = min(max(int(raw.get("height") or 16), 4), 80) if str(raw.get("height") or "16").lstrip("-").isdigit() else 16
    if kind == "dynamic":
        block["rules"] = [{"field": _s(r.get("field"), 40), "op": _s(r.get("op"), 20), "value": _s(r.get("value"), 100),
                           "text": _s(r.get("text"), 2000)} for r in (raw.get("rules") or [])[:6] if isinstance(r, dict)]
    if kind == "social":
        block["links"] = [{"label": _s(link.get("label"), 40), "url": _s(link.get("url"), 500)}
                          for link in (raw.get("links") or [])[:6] if isinstance(link, dict)]
    return block


def _variants(raw) -> list[str]:
    return [_s(v, 200) for v in (raw or [])[:builder.MAX_VARIANTS + 1]] if isinstance(raw, list) else []


def _actions(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    return {name: bool(raw[name]) for name in ACTIONS if name in raw}


def normalize(channel: str, content) -> dict:
    """Bounded, typed content for the channel. Unknown keys and block types are dropped; nothing is trusted."""
    c = content if isinstance(content, dict) else {}
    ai = c.get("ai") if isinstance(c.get("ai"), dict) else {}
    out: dict = {"actions": _actions(c.get("actions")),
                 "ai": {"brief": _s(ai.get("brief"), 600), "goal": _s(ai.get("goal"), 40), "tone": _s(ai.get("tone"), 40)}}
    if channel == "Email":
        blocks = [b for b in (_block(r) for r in (c.get("blocks") or [])[:MAX_BLOCKS]) if b]
        out.update(subject=_s(c.get("subject"), 300), preheader=_s(c.get("preheader"), 300),
                   variants=_variants(c.get("variants")), blocks=blocks)
    elif channel == "SMS":
        out.update(text=_s(c.get("text"), 1000), keyword=_s(c.get("keyword") or "STOP", 20).strip() or "STOP",
                   window=_s(c.get("window"), 20))
    elif channel == "WhatsApp":
        header_type = c.get("header_type") if c.get("header_type") in builder.WA_HEADER_TYPES else "None"
        buttons = []
        for raw in (c.get("buttons") or [])[:5]:
            if isinstance(raw, dict):
                kind = raw.get("kind") if raw.get("kind") in BUTTON_KINDS else "quick"
                buttons.append({"kind": kind, "label": _s(raw.get("label"), 40), "url": _s(raw.get("url"), 500),
                                "phone": _s(raw.get("phone"), 25)})
        samples = c.get("samples") if isinstance(c.get("samples"), dict) else {}
        out.update(header_type=header_type, header=_s(c.get("header"), 500) if header_type != "None" else "",
                   body=_s(c.get("body"), 1100), footer=_s(c.get("footer"), 100), buttons=buttons,
                   samples={k: _s(v, 100) for k, v in samples.items() if k in t.PLACEHOLDERS},
                   category=c.get("category") if c.get("category") in CATEGORIES else "Marketing")
    elif channel == "LinkedIn":
        out.update(subject=_s(c.get("subject"), 300), text=_s(c.get("text"), 2500))
    return out


def new_content(channel: str) -> dict:
    """The starting point for a blank template."""
    base = {"actions": {"personalize": True}, "ai": {"brief": "", "goal": "", "tone": "Friendly"}}
    if channel == "Email":
        return {**base, "subject": "", "preheader": "", "variants": [],
                "blocks": [builder.new_block("heading"), builder.new_block("text"), builder.new_block("signature")]}
    if channel == "SMS":
        return {**base, "text": "Hi {{first_name|there}}, \nReply STOP to opt out.", "keyword": "STOP", "window": "09:00-21:00"}
    if channel == "WhatsApp":
        return {**base, "header_type": "None", "header": "", "body": "Hi {{first_name|there}}, ", "footer": "Reply STOP to unsubscribe",
                "buttons": [], "samples": {}, "category": "Marketing"}
    return {**base, "subject": "", "text": "Hi {{first_name|there}}, "}


def with_starter(channel: str, starter: dict | None) -> dict:
    """A starter's content for the channel on top of the blank skeleton (so nothing is missing)."""
    return normalize(channel, {**new_content(channel), **(starter or {})})


# Stored fields <-> content -----------------------------------------------------


def fields_to_store(channel: str, content: dict) -> dict:
    """The template's own fields for this content. The whole content is also kept, so the builder can reopen it exactly."""
    c = normalize(channel, content)
    fields: dict = {"builder_content": json.dumps(c, ensure_ascii=False), "agent_actions": json.dumps(c["actions"]),
                    "ai_brief": c["ai"]["brief"], "ai_goal": c["ai"]["goal"], "ai_tone": c["ai"]["tone"]}
    if channel == "Email":
        fields.update(subject=c["subject"].strip(), preheader=c["preheader"].strip(),
                      subject_variants=json.dumps([v for v in c["variants"] if v.strip()]) if any(v.strip() for v in c["variants"]) else "",
                      body=builder.email_html(c["blocks"], c["preheader"]))
    elif channel == "SMS":
        fields.update(body=builder.sms_text(c["text"]), opt_out_keyword=c["keyword"], sms_send_window=c["window"].strip())
    elif channel == "WhatsApp":
        samples = {p: c["samples"].get(p) or t.SAMPLES.get(p, "") for p in builder.merge_tags(c["body"])}
        fields.update(body=c["body"].strip(), whatsapp_params=",".join(builder.merge_tags(c["body"])),
                      whatsapp_header_type=c["header_type"], whatsapp_header=c["header"], whatsapp_footer=c["footer"],
                      whatsapp_buttons=json.dumps(c["buttons"]), whatsapp_samples=json.dumps(samples),
                      whatsapp_category=c["category"])
    else:
        fields.update(subject=c["subject"].strip(), body=c["text"].strip())
    if not fields.get("body"):
        fields["body"] = "-"  # the field is required; the checks say the message is empty
    return fields


def _json(value, default):
    try:
        data = json.loads(value or "")
    except ValueError:
        return default
    return data if isinstance(data, type(default)) else default


def _named(body: str, params: str) -> str:
    """Meta's {{1}} back to the field behind it, for templates stored in Meta's form."""
    names = [p.strip() for p in (params or "").split(",") if p.strip()]
    return re.sub(r"\{\{\s*(\d+)\s*\}\}", lambda m: "{{" + names[int(m.group(1)) - 1] + "}}" if int(m.group(1)) <= len(names) else "", body or "")


def content_from_fields(channel: str, f: dict) -> dict:
    """Builder content for a stored template: its own saved content, or one made from the plain fields of an older template."""
    saved = _json(f.get("builder_content"), {})
    if saved:
        content = normalize(channel, saved)
    elif channel == "Email":
        body = f.get("body") or ""
        paragraphs = "\n\n".join(p.strip() for p in re.split(r"\n\s*\n", t.strip_html(body) if t.is_builder_html(body) else body) if p.strip())
        content = normalize(channel, {"subject": f.get("subject"), "blocks": [{"type": "text", "text": paragraphs}]})
    elif channel == "SMS":
        content = normalize(channel, {"text": f.get("body")})
    elif channel == "WhatsApp":
        content = normalize(channel, {"body": _named(f.get("body"), f.get("whatsapp_params")), "category": f.get("whatsapp_category")})
    else:
        content = normalize(channel, {"subject": f.get("subject"), "text": f.get("body")})
    # The stored fields are authoritative where they exist, so an edit made in the form is not lost.
    if channel == "Email" and f.get("subject"):
        content["subject"] = f["subject"]
    content["actions"] = {**content.get("actions", {}), **_actions(_json(f.get("agent_actions"), {}))}
    if channel == "Email" and not content["variants"]:
        content["variants"] = _variants(_json(f.get("subject_variants"), []))
    return content


# Compile ---------------------------------------------------------------------


def chip_text(markup: str) -> str:
    """Wrap each merge field in the text of the markup in a chip, for the builder's preview (never inside a tag)."""
    def wrap(match: re.Match) -> str:
        text = t.PLACEHOLDER_RE.sub(lambda m: f'<span class="tb-tag">{html.escape(m.group(0))}</span>', match.group(1))
        return f">{text}<"

    return re.sub(r">([^<>]+)<", wrap, markup)


def _sample_text(text: str, samples: dict | None = None) -> str:
    return t.render(text, {**t.sample_values(), **(samples or {})}, escape=False)


def compile_content(channel: str, content: dict, *, has_address: bool = True) -> dict:
    """Everything the screen shows for this content: ``issues`` (they stop approval), ``checks`` (advice before a send),
    and the preview for the channel."""
    c = normalize(channel, content)
    if channel == "Email":
        variants = [v for v in c["variants"] if v.strip()] if any(v.strip() for v in c["variants"]) else []
        issues = builder.check_email(c["subject"], c["blocks"], c["variants"])
        checks = presend.email(c["subject"], c["blocks"], variants, has_address=has_address)
        urls = [u for b in c["blocks"] for u in builder.block_urls(b) if u]
        spam = spamscore.score(c["subject"], builder.email_text(c["blocks"]), urls)
        checks.append(spamscore.check_line(spam))  # advice, never a block
        body = builder.email_html(c["blocks"], c["preheader"])
        sample = t.render(t.resolve_dynamic(body, t.sample_values()), t.sample_values())
        return {"issues": issues, "checks": checks, "summary": presend.summary(checks), "body": body,
                "previews": [chip_text(h) for h in builder.email_blocks(c["blocks"])], "text": builder.email_text(c["blocks"]),
                "sample_html": sample, "sample_subject": _sample_text(c["subject"]), "spam": spam}
    if channel == "SMS":
        text = builder.sms_text(c["text"])
        checks = presend.sms(text, c["keyword"], c["window"])
        return {"issues": builder.check_sms(text, c["keyword"]), "checks": checks, "summary": presend.summary(checks),
                "body": text, "chars": builder.sms_length(text), "parts": builder.sms_parts(text),
                "encoding": builder.sms_encoding(text), "sample": _sample_text(text)}
    if channel == "WhatsApp":
        samples = {**t.sample_values(), **c["samples"]}
        compiled = builder.whatsapp_components(c["header"], c["body"], c["footer"], c["buttons"], c["header_type"])
        checks = presend.whatsapp(c["header"], c["body"], c["footer"], c["buttons"], samples, category=c["category"],
                                  header_type=c["header_type"])
        return {"issues": builder.check_whatsapp(c["header"], c["body"], c["footer"], c["buttons"], c["header_type"]),
                "checks": checks, "summary": presend.summary(checks), "components": compiled["components"],
                "params": compiled["params"], "body": c["body"], "sample": _sample_text(c["body"], samples),
                "sample_header": _sample_text(c["header"], samples) if c["header_type"] == "Text" else c["header"]}
    checks = presend.linkedin(c["subject"], c["text"])
    return {"issues": builder.check_linkedin(c["subject"], c["text"]), "checks": checks, "summary": presend.summary(checks),
            "sample": _sample_text(c["text"]), "sample_subject": _sample_text(c["subject"])}

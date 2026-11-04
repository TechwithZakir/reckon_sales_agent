"""Template builder for Email, SMS, WhatsApp and LinkedIn (pure: no Frappe imports, so it is unit-tested directly).

Each channel has its own rules, so each has its own compiler and checks:

* Email: a list of blocks (heading, text, image, button, columns, divider, product card, dynamic content, signature,
  social links) compiled to email-safe HTML with inline styles, plus a plain-text version. The subject is required.
* SMS: one text. Its length is counted the way carriers count it: GSM-7 gives 160 characters per message (153 per
  part when it is split), anything else, such as Bangla, gives 70 (67 per part). The opt-out line is required.
* WhatsApp: header, body, footer and buttons, compiled to Meta's template components. Meta wants numbered variables,
  so the merge fields become ``{{1}}``, ``{{2}}``, ... and the matching field names go in ``whatsapp_params``.
* LinkedIn: a subject and a message a salesperson sends (the agent does not send it).

Merge fields are the ones the campaign engine fills in (``campaigns.templates.FIELDS``) and may carry a fallback:
``{{first_name|there}}``. A problem that stops a template being approved is an *issue* (``check_*``); advice before a
send (a missing fallback, an image without alt text) is a pre-send check (``campaigns.presend``).
"""

from __future__ import annotations

import html
import re

from reckon_sales_agent.campaigns.templates import (
    BUILDER_MARK,
    DYNAMIC_ATTR,
    PLACEHOLDER_RE,
    PLACEHOLDERS,
    RULE_OPS,
    dynamic_attribute,
)

OPT_OUT_RE = re.compile(r"\b(stop|unsubscribe|বন্ধ)\b", re.I)
ACCENT = "#3451D1"

# Email
PALETTE = ("heading", "text", "image", "button", "columns", "divider", "product", "dynamic", "signature", "social")
EMAIL_BLOCKS = PALETTE + ("spacer",)  # spacer is still understood, but not offered
SUBJECT_MAX = 150
MAX_VARIANTS = 2  # alternative subject lines for an A/B test, besides the main one
# SMS (GSM 03.38 basic set; the extension characters count as two)
GSM_BASIC = ("@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡"
             "ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà")
GSM_EXTENDED = "^{}\\[~]|€"
SMS_MAX_PARTS = 3
# WhatsApp (Meta template limits). The installed WhatsApp app has no video header, so it is not offered.
WA_HEADER_MAX = 60
WA_BODY_MAX = 1024
WA_FOOTER_MAX = 60
WA_BUTTON_MAX = 3
WA_QUICK_REPLY_MAX = 25
WA_HEADER_TYPES = ("None", "Text", "Image", "Document")
# LinkedIn InMail
LI_SUBJECT_MAX = 200
LI_BODY_MAX = 1900


def merge_tags(text: str) -> list[str]:
    """Merge fields used in the text, in order of first use, without repeats."""
    seen: list[str] = []
    for match in PLACEHOLDER_RE.finditer(text or ""):
        if match.group(1) not in seen:
            seen.append(match.group(1))
    return seen


def unknown_tags(text: str) -> list[str]:
    return [name for name in merge_tags(text) if name not in PLACEHOLDERS]


def _esc(value) -> str:
    return html.escape(str(value or ""))


def _attr(value) -> str:
    return html.escape(str(value or ""), quote=True)


def _https(url) -> bool:
    return str(url or "").startswith("https://") and len(str(url)) > len("https://")


# ----------------------------------------------------------------------------------------------------------- Email blocks

def new_block(kind: str) -> dict:
    """A block with starting content, so a new block is already a working example."""
    blocks = {
        "heading": {"type": "heading", "text": "Hi {{first_name|there}}", "level": 2},
        "text": {"type": "text", "text": "Write your message here. You can use fields such as {{business_name|your business}}."},
        "image": {"type": "image", "src": "", "alt": "", "url": ""},
        "button": {"type": "button", "label": "Book a 15-minute call", "url": "https://"},
        "columns": {"type": "columns", "left": "Left column", "right": "Right column"},
        "divider": {"type": "divider"},
        "product": {"type": "product", "title": "Product name", "text": "One line about it.", "price": "", "image": "",
                    "alt": "", "label": "View details", "url": "https://"},
        "dynamic": {"type": "dynamic", "rules": [{"field": "industry", "op": "contains", "value": "", "text": ""}],
                    "fallback": "What everyone else sees."},
        "signature": {"type": "signature", "closing": "Best,", "name": "{{owner_name|our team}}", "title": "",
                      "company": "{{company}}", "phone": "", "email": ""},
        "social": {"type": "social", "links": [{"label": "LinkedIn", "url": "https://"}]},
        "spacer": {"type": "spacer", "height": 16},
    }
    return dict(blocks[kind])


def _paras(text, style="margin:0 0 14px;font-size:15px;line-height:1.6;color:#222") -> str:
    parts = [p.strip() for p in re.split(r"\n\s*\n", str(text or "")) if p.strip()]
    return "".join(f'<p style="{style}">{_esc(p).replace(chr(10), "<br>")}</p>' for p in parts)


def _heading(b) -> str:
    level = 1 if int(b.get("level") or 2) == 1 else 2
    size = 28 if level == 1 else 22
    return (f'<h{level} style="margin:0 0 12px;font-size:{size}px;line-height:1.3;color:#111">'
            f'{_esc(b.get("text"))}</h{level}>')


def _button(b) -> str:
    return (f'<p style="margin:18px 0"><a href="{_attr(b.get("url") or "#")}" style="display:inline-block;padding:12px 22px;'
            f'border-radius:8px;background:{ACCENT};color:#ffffff;text-decoration:none;font-weight:700">'
            f'{_esc(b.get("label"))}</a></p>')


def _image_tag(src, alt, width=600) -> str:
    return (f'<img src="{_attr(src)}" alt="{_attr(alt)}" width="{width}" '
            'style="max-width:100%;height:auto;display:block;border:0">')


def _image(b) -> str:
    if not b.get("src"):
        return ('<p style="margin:14px 0;padding:36px 12px;border:1px dashed #a7b1c6;border-radius:8px;'
                'text-align:center;color:#475569;font-size:12px">Image: add its https address</p>')
    tag = _image_tag(b["src"], b.get("alt"))
    if _https(b.get("url")):
        tag = f'<a href="{_attr(b["url"])}">{tag}</a>'
    return f'<p style="margin:14px 0">{tag}</p>'


def _columns(b) -> str:
    cell = "font-size:15px;line-height:1.6;color:#222"
    return ('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 14px"><tr>'
            f'<td width="50%" valign="top" style="padding-right:10px;{cell}">{_paras(b.get("left"), "margin:0 0 10px")}</td>'
            f'<td width="50%" valign="top" style="padding-left:10px;{cell}">{_paras(b.get("right"), "margin:0 0 10px")}</td>'
            '</tr></table>')


def _product(b) -> str:
    image = ""
    if _https(b.get("image")):
        image = f'<td width="140" valign="top" style="padding:12px">{_image_tag(b["image"], b.get("alt"), 120)}</td>'
    lines = [f'<div style="font-weight:700;font-size:16px;color:#111">{_esc(b.get("title"))}</div>']
    if b.get("text"):
        lines.append(f'<div style="margin-top:4px;font-size:14px;line-height:1.5;color:#334155">{_esc(b["text"])}</div>')
    if b.get("price"):
        lines.append(f'<div style="margin-top:6px;font-weight:700;color:#111">{_esc(b["price"])}</div>')
    if _https(b.get("url")) and b.get("label"):
        lines.append(f'<div style="margin-top:10px"><a href="{_attr(b["url"])}" style="display:inline-block;padding:8px 16px;'
                     f'border-radius:6px;background:{ACCENT};color:#ffffff;text-decoration:none;font-weight:700;'
                     f'font-size:13px">{_esc(b["label"])}</a></div>')
    return ('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            'style="margin:14px 0;border:1px solid #e5e7eb;border-radius:8px"><tr>'
            f'{image}<td valign="top" style="padding:12px">{"".join(lines)}</td></tr></table>')


def _dynamic(b) -> str:
    rules = [{"field": r.get("field"), "op": r.get("op") or "contains", "value": str(r.get("value") or ""),
              "html": _paras(r.get("text"))} for r in b.get("rules") or [] if isinstance(r, dict)]
    return (f'<div {DYNAMIC_ATTR}="{dynamic_attribute({"rules": rules})}" style="margin:0 0 14px">'
            f'{_paras(b.get("fallback"))}</div>')


def _signature(b) -> str:
    lines = []
    if b.get("closing"):
        lines.append(_esc(b["closing"]))
    if b.get("name"):
        lines.append(f'<b>{_esc(b["name"])}</b>')
    lines += [_esc(b[k]) for k in ("title", "company") if b.get(k)]
    contact = " · ".join(_esc(b[k]) for k in ("phone", "email") if b.get(k))
    if contact:
        lines.append(contact)
    return f'<p style="margin:18px 0 0;font-size:15px;line-height:1.6;color:#222">{"<br>".join(lines)}</p>'


def _social(b) -> str:
    links = [f'<a href="{_attr(link.get("url"))}" style="color:{ACCENT}">{_esc(link.get("label"))}</a>'
             for link in b.get("links") or [] if isinstance(link, dict) and _https(link.get("url")) and link.get("label")]
    return f'<p style="margin:14px 0;font-size:13px">{" · ".join(links)}</p>' if links else ""


def _spacer(b) -> str:
    height = min(max(int(b.get("height") or 16), 4), 80)
    return f'<div style="height:{height}px;line-height:{height}px">&nbsp;</div>'


COMPILERS = {
    "heading": _heading, "text": lambda b: _paras(b.get("text")), "button": _button, "image": _image,
    "columns": _columns, "divider": lambda b: '<hr style="border:0;border-top:1px solid #e5e7eb;margin:20px 0">',
    "product": _product, "dynamic": _dynamic, "signature": _signature, "social": _social, "spacer": _spacer,
}


def email_blocks(blocks: list[dict]) -> list[str]:
    """The HTML of each block on its own (the builder shows them one by one, and joins them for sending)."""
    return [COMPILERS[b["type"]](b) if b.get("type") in COMPILERS else "" for b in blocks or []]


def email_html(blocks: list[dict], preheader: str = "") -> str:
    """Email-safe HTML: a single column, inline styles, the text escaped (merge fields stay as {{fields}})."""
    hidden = ""
    if (preheader or "").strip():
        hidden = ('<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;font-size:1px">'
                  f'{_esc(preheader)}</div>')
    return (f'<div {BUILDER_MARK} style="max-width:600px;margin:0 auto;padding:24px;font-family:Arial,Helvetica,sans-serif">'
            f'{hidden}{"".join(email_blocks(blocks))}</div>')


def block_texts(block: dict) -> list[str]:
    """What a person wrote in a block (not its addresses), for the checks that read the words."""
    kind = block.get("type")
    if kind in ("heading", "text"):
        return [block.get("text")]
    if kind == "button":
        return [block.get("label")]
    if kind == "image":
        return [block.get("alt")]
    if kind == "columns":
        return [block.get("left"), block.get("right")]
    if kind == "product":
        return [block.get(k) for k in ("title", "text", "price", "label", "alt")]
    if kind == "dynamic":
        return [block.get("fallback")] + [r.get("text") for r in block.get("rules") or [] if isinstance(r, dict)]
    if kind == "signature":
        return [block.get(k) for k in ("closing", "name", "title", "company", "phone", "email")]
    if kind == "social":
        return [link.get("label") for link in block.get("links") or [] if isinstance(link, dict)]
    return []


def block_urls(block: dict) -> list[str]:
    kind = block.get("type")
    if kind in ("button",):
        return [block.get("url")]
    if kind == "image":
        return [block.get("src"), block.get("url")]
    if kind == "product":
        return [block.get("image"), block.get("url")]
    if kind == "social":
        return [link.get("url") for link in block.get("links") or [] if isinstance(link, dict)]
    return []


def all_text(subject: str, blocks: list[dict], variants=()) -> str:
    return "\n".join([subject or "", *variants, *(str(t or "") for b in blocks or [] for t in block_texts(b))])


def email_text(blocks: list[dict]) -> str:
    """The plain-text version: the same content, one block per paragraph, links written out."""
    lines: list[str] = []
    for block in blocks or []:
        kind = block.get("type")
        if kind in ("heading", "text"):
            lines.append((block.get("text") or "").strip())
        elif kind == "button":
            lines.append(f'{block.get("label") or ""}: {block.get("url") or ""}'.strip())
        elif kind == "columns":
            lines += [(block.get("left") or "").strip(), (block.get("right") or "").strip()]
        elif kind == "product":
            head = " · ".join(str(block[k]) for k in ("title", "text", "price") if block.get(k))
            lines.append(head + (f'\n{block.get("label") or "Details"}: {block["url"]}' if _https(block.get("url")) else ""))
        elif kind == "dynamic":
            lines.append((block.get("fallback") or "").strip())
        elif kind == "signature":
            lines.append("\n".join(str(block[k]) for k in ("closing", "name", "title", "company", "phone", "email") if block.get(k)))
        elif kind == "social":
            lines.append("\n".join(f'{link.get("label")}: {link.get("url")}' for link in block.get("links") or []
                                   if isinstance(link, dict) and link.get("label")))
    return "\n\n".join(line for line in lines if line)


def _check_block(index: int, block: dict) -> list[str]:
    kind = block.get("type")
    where = f"Block {index}"
    issues: list[str] = []
    if kind not in EMAIL_BLOCKS:
        return [f"{where}: unknown type '{kind}'."]
    if kind in ("heading", "text") and not (block.get("text") or "").strip():
        issues.append(f"{where}: the {kind} is empty.")
    if kind == "button":
        if not (block.get("label") or "").strip():
            issues.append(f"{where}: the button needs a label.")
        if not _https(block.get("url")):
            issues.append(f"{where}: the button link must start with https://.")
    if kind == "image" and not _https(block.get("src")):
        issues.append(f"{where}: the image must be an https:// address.")
    if kind == "image" and (block.get("url") or "").strip() and not _https(block.get("url")):
        issues.append(f"{where}: the image link must start with https://.")
    if kind == "columns" and not ((block.get("left") or "").strip() or (block.get("right") or "").strip()):
        issues.append(f"{where}: the columns are empty.")
    if kind == "product":
        if not (block.get("title") or "").strip():
            issues.append(f"{where}: the product card needs a title.")
        if (block.get("image") or "").strip() and not _https(block.get("image")):
            issues.append(f"{where}: the product image must be an https:// address.")
        if not _https(block.get("url")):
            issues.append(f"{where}: the product link must start with https://.")
    if kind == "dynamic":
        rules = [r for r in block.get("rules") or [] if isinstance(r, dict)]
        if not rules:
            issues.append(f"{where}: add a rule, or use a text block instead of dynamic content.")
        if not (block.get("fallback") or "").strip():
            issues.append(f"{where}: say what everyone else sees (the fallback).")
        for number, rule in enumerate(rules, start=1):
            if rule.get("field") not in PLACEHOLDERS:
                issues.append(f"{where}, rule {number}: choose a field.")
            if rule.get("op") not in RULE_OPS:
                issues.append(f"{where}, rule {number}: choose how to compare it.")
            elif rule["op"] in ("is", "contains") and not (rule.get("value") or "").strip():
                issues.append(f"{where}, rule {number}: enter the value to look for.")
            if not (rule.get("text") or "").strip():
                issues.append(f"{where}, rule {number}: write what these people see.")
    if kind == "signature" and not (block.get("name") or "").strip():
        issues.append(f"{where}: the signature needs a name.")
    if kind == "social":
        links = [link for link in block.get("links") or [] if isinstance(link, dict)]
        if not links:
            issues.append(f"{where}: add at least one social link.")
        for link in links:
            if not (link.get("label") or "").strip() or not _https(link.get("url")):
                issues.append(f"{where}: each social link needs a name and an https:// address.")
                break
    return issues


def check_email(subject: str, blocks: list[dict], variants=()) -> list[str]:
    issues: list[str] = []
    if not (subject or "").strip():
        issues.append("The email needs a subject.")
    elif len(subject) > SUBJECT_MAX:
        issues.append(f"The subject is {len(subject)} characters; keep it under {SUBJECT_MAX}.")
    for number, variant in enumerate(variants, start=1):
        if not str(variant or "").strip():
            issues.append(f"Subject variant {number} is empty.")
        elif len(str(variant)) > SUBJECT_MAX:
            issues.append(f"Subject variant {number} is {len(str(variant))} characters; keep it under {SUBJECT_MAX}.")
    if len(list(variants)) > MAX_VARIANTS:
        issues.append(f"Use at most {MAX_VARIANTS} subject variants besides the main subject.")
    if not blocks:
        issues.append("Add at least one block to the email.")
    for index, block in enumerate(blocks or [], start=1):
        issues += _check_block(index, block)
    for name in unknown_tags(all_text(subject, blocks, [str(v) for v in variants])):
        issues.append(f"Unknown merge tag {{{{{name}}}}}.")
    return issues


# -------------------------------------------------------------------------------------------------------------- SMS

def sms_encoding(text: str) -> str:
    """GSM-7 when every character is in the GSM alphabet, otherwise UCS-2 (Unicode, e.g. Bangla)."""
    return "GSM-7" if all(ch in GSM_BASIC or ch in GSM_EXTENDED for ch in text) else "UCS-2"


def sms_length(text: str) -> int:
    """Characters as the network counts them: GSM extension characters count twice."""
    if sms_encoding(text) == "UCS-2":
        return len(text)
    return sum(2 if ch in GSM_EXTENDED else 1 for ch in text)


def sms_parts(text: str) -> int:
    """How many SMS parts the text needs: 160 (GSM-7) or 70 (Unicode) for one part, 153 or 67 per part when split."""
    length = sms_length(text)
    if length == 0:
        return 0
    single, multi = (70, 67) if sms_encoding(text) == "UCS-2" else (160, 153)
    return 1 if length <= single else -(-length // multi)


def check_sms(text: str, keyword: str = "STOP") -> list[str]:
    issues: list[str] = []
    if not (text or "").strip():
        issues.append("The SMS needs a message.")
        return issues
    parts = sms_parts(text)
    if parts > SMS_MAX_PARTS:
        issues.append(f"The SMS needs {parts} parts; keep it to {SMS_MAX_PARTS} or fewer.")
    word = (keyword or "STOP").strip()
    # The chosen keyword, or any of the usual opt-out words (STOP, unsubscribe, বন্ধ), counts.
    if not (re.search(rf"\b{re.escape(word)}\b", text, re.I) or OPT_OUT_RE.search(text)):
        issues.append(f"Add an opt-out line, such as 'Reply {word} to opt out'.")
    for name in unknown_tags(text):
        issues.append(f"Unknown merge tag {{{{{name}}}}}.")
    return issues


def sms_text(text: str) -> str:
    """The SMS body with merge fields left in place; the sending path fills them, values escaped as plain text."""
    return (text or "").strip()


# ----------------------------------------------------------------------------------------------------------- WhatsApp

def whatsapp_components(header: str, body: str, footer: str, buttons: list[dict], header_type: str = "Text") -> dict:
    """Meta's template components, with merge fields turned into numbered variables. ``params`` gives the field
    behind each number, in the order Meta expects (it is stored as the template's whatsapp_params). The header is
    text, or the address of a sample image or document that Meta reviews."""
    params = merge_tags(body or "")
    components: dict = {"body": {"text": _number_tags(body or "", params)}}
    if header and header_type == "Text":
        components["header"] = {"type": "text", "text": header}
    elif header and header_type in ("Image", "Document"):
        components["header"] = {"type": header_type.lower(), "example": header}
    if footer:
        components["footer"] = {"text": footer}
    if buttons:
        components["buttons"] = [_button_component(b) for b in buttons]
    return {"components": components, "params": params}


def _button_component(button: dict) -> dict:
    if button.get("kind") == "url":
        return {"type": "url", "text": button.get("label"), "url": button.get("url")}
    if button.get("kind") == "phone":
        return {"type": "phone", "text": button.get("label"), "phone": button.get("phone")}
    return {"type": "quick_reply", "text": button.get("label")}


def check_whatsapp(header: str, body: str, footer: str, buttons: list[dict], header_type: str = "Text") -> list[str]:
    issues: list[str] = []
    if not (body or "").strip():
        issues.append("The WhatsApp template needs a body.")
    if len(body or "") > WA_BODY_MAX:
        issues.append(f"The body is {len(body)} characters; Meta allows {WA_BODY_MAX}.")
    if header_type == "Text" and len(header or "") > WA_HEADER_MAX:
        issues.append(f"The header is {len(header)} characters; Meta allows {WA_HEADER_MAX}.")
    if header_type in ("Image", "Document") and not _https(header):
        issues.append(f"A {header_type.lower()} header needs the https:// address of a sample for Meta to review.")
    if len(footer or "") > WA_FOOTER_MAX:
        issues.append(f"The footer is {len(footer)} characters; Meta allows {WA_FOOTER_MAX}.")
    text_body = (body or "").strip()
    if text_body.startswith("{{"):
        issues.append("Meta does not accept a body that starts with a variable; add text before it.")
    if text_body.endswith("}}"):
        issues.append("Meta does not accept a body that ends with a variable; add text after it.")
    if header_type == "Text" and merge_tags(header or ""):
        issues.append("The header cannot use merge tags; put personal details in the body.")
    if len(buttons or []) > WA_BUTTON_MAX:
        issues.append(f"Meta allows up to {WA_BUTTON_MAX} buttons.")
    kinds = [b.get("kind") if b.get("kind") in ("url", "phone") else "quick" for b in buttons or []]
    if "quick" in kinds and ("url" in kinds or "phone" in kinds):
        issues.append("Use quick replies, or call-to-action buttons, not both kinds together.")
    if kinds.count("url") > 1 or kinds.count("phone") > 1:
        issues.append("Meta allows one link button and one phone button.")
    for index, button in enumerate(buttons or [], start=1):
        label = str(button.get("label") or "")
        if not label.strip():
            issues.append(f"Button {index} needs a label.")
        elif len(label) > WA_QUICK_REPLY_MAX:
            issues.append(f"Button {index} is {len(label)} characters; Meta allows {WA_QUICK_REPLY_MAX}.")
        if button.get("kind") == "url" and not _https(button.get("url")):
            issues.append(f"Button {index}: the link must start with https://.")
        if button.get("kind") == "phone" and not re.fullmatch(r"\+?\d[\d ]{6,18}", str(button.get("phone") or "")):
            issues.append(f"Button {index}: enter the phone number with its country code.")
    for name in unknown_tags(" ".join([header or "", body or "", footer or ""])):
        issues.append(f"Unknown merge tag {{{{{name}}}}}.")
    return issues


# ----------------------------------------------------------------------------------------------------------- LinkedIn

def check_linkedin(subject: str, text: str) -> list[str]:
    issues: list[str] = []
    if not (text or "").strip():
        issues.append("The LinkedIn message needs text.")
    if len(text or "") > LI_BODY_MAX:
        issues.append(f"The message is {len(text)} characters; LinkedIn allows {LI_BODY_MAX}.")
    if len(subject or "") > LI_SUBJECT_MAX:
        issues.append(f"The subject is {len(subject)} characters; LinkedIn allows {LI_SUBJECT_MAX}.")
    for name in unknown_tags(f"{subject or ''} {text or ''}"):
        issues.append(f"Unknown merge tag {{{{{name}}}}}.")
    return issues


# ----------------------------------------------------------------------------------------------------------- shared

def _number_tags(text: str, params: list[str]) -> str:
    """Replace each merge field with Meta's {{n}}, n counted in the order of ``params``."""
    def number(match: re.Match) -> str:
        name = match.group(1)
        return "{{" + str(params.index(name) + 1) + "}}" if name in params else ""

    return PLACEHOLDER_RE.sub(number, text or "")

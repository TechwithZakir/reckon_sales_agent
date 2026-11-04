"""Template builder for Email, SMS and WhatsApp (pure: no Frappe imports, so it is unit-tested directly).

Each channel has its own rules, so each has its own compiler and checks:

* Email: a list of blocks (heading, text, button, image, divider, spacer) compiled to email-safe HTML with inline
  styles, plus a plain-text version. The subject is required.
* SMS: one text. Its length is counted the way carriers count it: GSM-7 gives 160 characters per message (153 per
  part when it is split), anything else, such as Bangla, gives 70 (67 per part). The opt-out line is required.
* WhatsApp: header, body, footer and buttons, compiled to Meta's template components. Meta wants numbered variables,
  so the merge tags become ``{{1}}``, ``{{2}}``, ... and the matching placeholder names go in ``whatsapp_params``.

Merge tags are the placeholders the campaign engine already fills in (``campaigns.templates.PLACEHOLDERS``), so a
template built here renders the same way wherever it is sent.
"""

from __future__ import annotations

import html
import re

from reckon_sales_agent.campaigns.templates import BUILDER_MARK, PLACEHOLDERS

TAG_RE = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")
OPT_OUT_RE = re.compile(r"\b(stop|unsubscribe|বন্ধ)\b", re.I)

# Email
EMAIL_BLOCKS = ("heading", "text", "button", "image", "divider", "spacer")
SUBJECT_MAX = 150
# SMS (GSM 03.38 basic set; the extension characters count as two)
GSM_BASIC = ("@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡"
             "ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà")
GSM_EXTENDED = "^{}\\[~]|€"
SMS_MAX_PARTS = 3
# WhatsApp (Meta template limits)
WA_HEADER_MAX = 60
WA_BODY_MAX = 1024
WA_FOOTER_MAX = 60
WA_BUTTON_MAX = 3
WA_QUICK_REPLY_MAX = 25


def merge_tags(text: str) -> list[str]:
    """Merge tags used in the text, in order of first use, without repeats."""
    seen: list[str] = []
    for name in TAG_RE.findall(text or ""):
        if name not in seen:
            seen.append(name)
    return seen


def unknown_tags(text: str) -> list[str]:
    return [name for name in merge_tags(text) if name not in PLACEHOLDERS]


# ------------------------------------------------------------------------------------------------------------ Email

def email_html(blocks: list[dict]) -> str:
    """Email-safe HTML: a single column, inline styles, the text escaped (merge tags stay as {{tags}})."""
    rows = []
    for block in blocks or []:
        kind = block.get("type")
        if kind == "heading":
            level = 1 if int(block.get("level") or 2) == 1 else 2
            size = 24 if level == 1 else 19
            rows.append(f'<h{level} style="margin:0 0 12px;font-size:{size}px;line-height:1.3;color:#111">'
                        f'{_esc(block.get("text"))}</h{level}>')
        elif kind == "text":
            paragraphs = [p.strip() for p in re.split(r"\n\s*\n", block.get("text") or "") if p.strip()]
            rows.extend(f'<p style="margin:0 0 14px;font-size:15px;line-height:1.6;color:#222">'
                        f'{_esc(p).replace(chr(10), "<br>")}</p>' for p in paragraphs)
        elif kind == "button":
            rows.append(f'<p style="margin:18px 0"><a href="{html.escape(block.get("url") or "#", quote=True)}" '
                        f'style="display:inline-block;padding:12px 22px;border-radius:6px;background:#2563eb;'
                        f'color:#fff;text-decoration:none;font-weight:600">{_esc(block.get("label"))}</a></p>')
        elif kind == "image":
            rows.append(f'<p style="margin:14px 0"><img src="{html.escape(block.get("src") or "", quote=True)}" '
                        f'alt="{html.escape(block.get("alt") or "", quote=True)}" '
                        f'style="max-width:100%;height:auto;display:block;border:0"></p>')
        elif kind == "divider":
            rows.append('<hr style="border:0;border-top:1px solid #e5e7eb;margin:20px 0">')
        elif kind == "spacer":
            height = min(max(int(block.get("height") or 16), 4), 80)
            rows.append(f'<div style="height:{height}px;line-height:{height}px">&nbsp;</div>')
    body = "".join(rows)
    return (f'<div {BUILDER_MARK} style="max-width:600px;margin:0 auto;padding:24px;font-family:Arial,Helvetica,sans-serif">'
            f"{body}</div>")


def email_text(blocks: list[dict]) -> str:
    """The plain-text version: the same content, one block per paragraph, buttons as "label: url"."""
    lines: list[str] = []
    for block in blocks or []:
        kind = block.get("type")
        if kind in ("heading", "text"):
            lines.append((block.get("text") or "").strip())
        elif kind == "button":
            lines.append(f'{block.get("label") or ""}: {block.get("url") or ""}'.strip())
    return "\n\n".join(line for line in lines if line)


def check_email(subject: str, blocks: list[dict]) -> list[str]:
    issues: list[str] = []
    if not (subject or "").strip():
        issues.append("The email needs a subject.")
    elif len(subject) > SUBJECT_MAX:
        issues.append(f"The subject is {len(subject)} characters; keep it under {SUBJECT_MAX}.")
    if not blocks:
        issues.append("Add at least one block to the email.")
    for index, block in enumerate(blocks or [], start=1):
        kind = block.get("type")
        if kind not in EMAIL_BLOCKS:
            issues.append(f"Block {index}: unknown type '{kind}'.")
        if kind in ("heading", "text") and not (block.get("text") or "").strip():
            issues.append(f"Block {index}: the {kind} is empty.")
        if kind == "button":
            if not (block.get("label") or "").strip():
                issues.append(f"Block {index}: the button needs a label.")
            if not str(block.get("url") or "").startswith("https://"):
                issues.append(f"Block {index}: the button link must start with https://.")
        if kind == "image" and not str(block.get("src") or "").startswith("https://"):
            issues.append(f"Block {index}: the image must be an https:// address.")
    text = (subject or "") + " " + " ".join(str(b.get("text") or "") for b in blocks or [])
    for name in unknown_tags(text):
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


def check_sms(text: str) -> list[str]:
    issues: list[str] = []
    if not (text or "").strip():
        issues.append("The SMS needs a message.")
        return issues
    parts = sms_parts(text)
    if parts > SMS_MAX_PARTS:
        issues.append(f"The SMS needs {parts} parts; keep it to {SMS_MAX_PARTS} or fewer.")
    if not OPT_OUT_RE.search(text):
        issues.append("Add an opt-out line, such as 'Reply STOP to opt out'.")
    for name in unknown_tags(text):
        issues.append(f"Unknown merge tag {{{{{name}}}}}.")
    return issues


def sms_text(text: str) -> str:
    """The SMS body with merge tags left in place; the sending path fills them, values escaped as plain text."""
    return (text or "").strip()


# ----------------------------------------------------------------------------------------------------------- WhatsApp

def whatsapp_components(header: str, body: str, footer: str, buttons: list[dict]) -> dict:
    """Meta's template components, with merge tags turned into numbered variables. ``params`` gives the placeholder
    behind each number, in the order Meta expects (it is stored as the template's whatsapp_params)."""
    params = merge_tags(body or "")
    components: dict = {"body": {"text": _number_tags(body or "", params)}}
    if header:
        components["header"] = {"type": "text", "text": header}
    if footer:
        components["footer"] = {"text": footer}
    if buttons:
        components["buttons"] = [
            ({"type": "url", "text": b.get("label"), "url": b.get("url")} if b.get("kind") == "url"
             else {"type": "quick_reply", "text": b.get("label")}) for b in buttons]
    return {"components": components, "params": params}


def check_whatsapp(header: str, body: str, footer: str, buttons: list[dict]) -> list[str]:
    issues: list[str] = []
    if not (body or "").strip():
        issues.append("The WhatsApp template needs a body.")
    if len(body or "") > WA_BODY_MAX:
        issues.append(f"The body is {len(body)} characters; Meta allows {WA_BODY_MAX}.")
    if len(header or "") > WA_HEADER_MAX:
        issues.append(f"The header is {len(header)} characters; Meta allows {WA_HEADER_MAX}.")
    if len(footer or "") > WA_FOOTER_MAX:
        issues.append(f"The footer is {len(footer)} characters; Meta allows {WA_FOOTER_MAX}.")
    text_body = (body or "").strip()
    if text_body.startswith("{{"):
        issues.append("Meta does not accept a body that starts with a variable; add text before it.")
    if text_body.endswith("}}"):
        issues.append("Meta does not accept a body that ends with a variable; add text after it.")
    if merge_tags(header or ""):
        issues.append("The header cannot use merge tags; put personal details in the body.")
    if len(buttons or []) > WA_BUTTON_MAX:
        issues.append(f"Meta allows up to {WA_BUTTON_MAX} buttons.")
    kinds = {b.get("kind") for b in buttons or []}
    if "url" in kinds and len(buttons) > 1:
        issues.append("Use one link button, or quick replies, not both kinds together.")
    for index, button in enumerate(buttons or [], start=1):
        label = str(button.get("label") or "")
        if not label.strip():
            issues.append(f"Button {index} needs a label.")
        elif button.get("kind") != "url" and len(label) > WA_QUICK_REPLY_MAX:
            issues.append(f"Button {index} is {len(label)} characters; quick replies allow {WA_QUICK_REPLY_MAX}.")
        if button.get("kind") == "url" and not str(button.get("url") or "").startswith("https://"):
            issues.append(f"Button {index}: the link must start with https://.")
    for name in unknown_tags(" ".join([header or "", body or "", footer or ""])):
        issues.append(f"Unknown merge tag {{{{{name}}}}}.")
    return issues


# ----------------------------------------------------------------------------------------------------------- shared

def _esc(value) -> str:
    return html.escape(str(value or ""))


def _number_tags(text: str, params: list[str]) -> str:
    """Replace each merge tag with Meta's {{n}}, n counted in the order of ``params``."""
    def number(match: re.Match) -> str:
        name = match.group(1)
        return "{{" + str(params.index(name) + 1) + "}}" if name in params else ""

    return TAG_RE.sub(number, text or "")

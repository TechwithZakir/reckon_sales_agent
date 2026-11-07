"""Signup forms on the Frappe side: take a submission, ask for confirmation, and confirm.

A visitor is untrusted and unauthenticated. Nothing here trusts what a visitor sends: it is checked by ``campaigns.capture``,
limited per form and per address, and recorded as a Sales Prospect with the form named as the consent record. With double
opt-in the person is not emailed by any campaign until they click the link in the confirmation email.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import escape_html, get_url, now_datetime, nowdate

from reckon_sales_agent.campaigns import capture, person_store
from reckon_sales_agent.campaigns import tags as tag_rules
from reckon_sales_agent.usage import get_settings

PER_FORM_HOUR = 600


def get_form(slug: str):
    """The published form with this public key, or None."""
    slug = str(slug or "").strip().lower()[:20]
    if not slug.isalnum():
        return None
    name = frappe.db.get_value("Sales Capture Form", {"slug": slug, "status": "Published"})
    return frappe.get_doc("Sales Capture Form", name) if name else None


def public_config(form) -> dict:
    """What the public page may know about a form. Never the Company, the tags or the settings behind it."""
    import json

    try:
        fields = capture.clean_fields(json.loads(form.fields_json or "[]"))
    except ValueError:
        fields = capture.clean_fields([])
    return {
        "slug": form.slug, "headline": form.headline or "", "description": form.description or "",
        "button": form.button_label or "Subscribe", "fields": [{**f, "type": capture.FIELD_CATALOG[f["key"]][1]} for f in fields],
        "require_consent": bool(form.require_consent), "consent_text": form.consent_text or "",
        "ask_sms": bool(form.ask_sms), "ask_whatsapp": bool(form.ask_whatsapp), "accent": capture.accent(form.accent_color),
        "thank_you": form.thank_you_message or "", "redirect": capture.safe_redirect(form.redirect_url),
        "form_type": form.form_type, "popup_trigger": form.popup_trigger, "popup_delay": int(form.popup_delay or 8),
    }


def _hit(key: str, limit: int) -> bool:
    """Count one use of ``key`` this hour; True when the limit is already reached."""
    count = int(frappe.cache.get_value(key) or 0)
    if count >= limit:
        return True
    frappe.cache.set_value(key, count + 1, expires_in_sec=3600)
    return False


def submit(slug: str, data: dict, ip: str = "") -> dict:
    """Record one signup. Returns {ok, message, redirect} or {ok: False, errors}."""
    form = get_form(slug)
    if not form:
        return {"ok": False, "errors": {"form": _("This form is not available.")}}
    hour = now_datetime().strftime("%Y%m%d%H")
    if _hit(f"rsa_form:{form.slug}:{hour}", PER_FORM_HOUR) or (ip and _hit(f"rsa_form_ip:{form.slug}:{ip}:{hour}", capture.MAX_PER_HOUR)):
        return {"ok": False, "errors": {"form": _("Too many signups just now. Please try again in a little while.")}}
    import json

    clean, errors = capture.validate_submission(json.loads(form.fields_json or "[]"), data, require_consent=bool(form.require_consent),
                                                ask_sms=bool(form.ask_sms), ask_whatsapp=bool(form.ask_whatsapp))
    ok = {"ok": True, "message": form.thank_you_message or _("Thank you!"), "redirect": capture.safe_redirect(form.redirect_url)}
    if clean.get("bot"):
        return ok  # a bot learns nothing
    if errors:
        return {"ok": False, "errors": errors}
    token = frappe.generate_hash(length=32) if form.double_opt_in else ""
    person = {"email": clean["email"], "phone": clean.get("phone", ""), "contact_name": capture.person_name(clean),
              "business_name": clean.get("business_name", ""), "city": clean.get("city", ""), "industry": clean.get("industry", "")}
    prospect, outcome = person_store.upsert(
        form.company, person, source_type=f"form:{form.slug}", tags=tag_rules.normalize(form.tags), unconfirmed=bool(form.double_opt_in),
        optin_token=token, form=form.slug, sms_opt_in=clean["sms_opt_in"], whatsapp_opt_in=clean["whatsapp_opt_in"],
        consent_source=capture.consent_source(form.form_name, form.slug, nowdate()))
    if outcome in ("suppressed", "do_not_contact") or not prospect:
        return ok  # opted out before: the same answer, so a form cannot be used to find out who opted out
    from reckon_sales_agent.campaigns.verify_service import check_later

    check_later(prospect)
    frappe.db.set_value("Sales Capture Form", form.name, {"submissions": (form.submissions or 0) + 1,
                                                          "last_submission": now_datetime()}, update_modified=False)
    state = frappe.db.get_value("Sales Prospect", prospect, ["optin_status", "optin_token"], as_dict=True)
    if form.double_opt_in and state.optin_status == "Unconfirmed" and state.optin_token:
        _send_confirmation(form, prospect, clean["email"], state.optin_token)
    else:
        _signed_up(form.company, prospect, form.slug)
    for tag in tag_rules.normalize(form.tags):
        _tag_event(form.company, prospect, tag, form.slug)
    from reckon_sales_agent.campaigns.webhook_service import emit_person

    emit_person(form.company, "signup", prospect, form=form.slug)
    return ok


def _tag_event(company: str, prospect: str, tag: str, slug: str) -> None:
    try:
        from reckon_sales_agent.automation.engine import fire

        fire(company, "tag_added", prospect, tag=tag, source=f"form:{slug}")
    except Exception:
        frappe.log_error(title="Sales Agent automation trigger failed", message=f"tag_added {tag} for {prospect}")


def _signed_up(company: str, prospect: str, slug: str) -> None:
    try:
        from reckon_sales_agent.automation.engine import fire

        fire(company, "signup", prospect, form=slug, source=f"form:{slug}")
    except Exception:
        frappe.log_error(title="Sales Agent automation trigger failed", message=f"signup for {prospect}")


def confirmation_url(token: str) -> str:
    return get_url(f"/api/method/reckon_sales_agent.api_capture.confirm?token={token}")


def _send_confirmation(form, prospect: str, email: str, token: str) -> None:
    """The one email a person gets before they have confirmed. It is not a campaign message, so it carries no tracking."""
    settings = get_settings(form.company)
    sender = None
    if settings.get("email_account"):
        sender = frappe.db.get_value("Email Account", {"name": settings.email_account, "enable_outgoing": 1}, "email_id")
    name = escape_html(settings.get("sender_name") or form.company)
    link = escape_html(confirmation_url(token))
    html = (f"<p>Please confirm your email address to join {name}.</p>"
            f'<p><a href="{link}" style="background:{capture.accent(form.accent_color)};color:#fff;padding:10px 18px;'
            f'border-radius:6px;text-decoration:none;display:inline-block">Confirm my email</a></p>'
            "<p style='color:#666;font-size:13px'>If you did not ask for this, ignore this email and nothing will happen.</p>")
    try:
        frappe.sendmail(recipients=[email], sender=sender, subject=f"Confirm your email for {settings.get('sender_name') or form.company}",
                        message=html, reference_doctype="Sales Prospect", reference_name=prospect, now=False)
    except Exception:
        frappe.log_error(title="Sales Agent confirmation email failed", reference_doctype="Sales Prospect",
                         reference_name=prospect)


def confirm(token: str) -> dict | None:
    """Confirm the person behind this key (a POST from the confirmation page). Returns {form, company} or None."""
    token = str(token or "")
    if len(token) != 32 or not token.isalnum():
        return None
    row = frappe.db.get_value("Sales Prospect", {"optin_token": token}, ["name", "company", "signup_form", "optin_status"], as_dict=True)
    if not row:
        return None
    frappe.db.set_value("Sales Prospect", row.name, {"optin_status": "Confirmed", "optin_token": None, "confirmed_at": now_datetime()})
    form = frappe.db.get_value("Sales Capture Form", {"slug": row.signup_form, "company": row.company}, ["name", "confirmed_count"],
                               as_dict=True) if row.signup_form else None
    if form:
        frappe.db.set_value("Sales Capture Form", form.name, "confirmed_count", (form.confirmed_count or 0) + 1, update_modified=False)
    if row.optin_status == "Unconfirmed":
        _signed_up(row.company, row.name, row.signup_form or "")
        from reckon_sales_agent.campaigns.webhook_service import emit_person

        emit_person(row.company, "confirmed", row.name, form=row.signup_form or "")
    return {"form": row.signup_form, "company": row.company}

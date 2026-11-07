"""Signup forms: the public endpoints visitors use, and the management endpoints of Capture Studio.

Public endpoints (guest) never trust the visitor: see campaigns.capture and capture_service. They answer the same way for a
person who opted out before, so a form cannot be used to find out who did. Management endpoints need a Sales Agent manager
and are limited to the session's Company.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import escape_html, get_url
from werkzeug.wrappers import Response

from reckon_sales_agent.api_studio import _can_manage
from reckon_sales_agent.campaigns import capture, capture_service
from reckon_sales_agent.tenant import current_company, get_tenant_doc
from reckon_sales_agent.usage import assert_entitled

FORM_FIELDS = ("form_name", "status", "form_type", "headline", "description", "button_label", "consent_text", "require_consent",
               "ask_sms", "ask_whatsapp", "double_opt_in", "tags", "thank_you_message", "redirect_url", "accent_color",
               "allowed_origins", "popup_trigger", "popup_delay")
RECENT = 25


def _require_manager() -> None:
    if not _can_manage():
        frappe.throw(_("Ask a Sales Agent admin or manager to do this."), frappe.PermissionError)


def _json(value):
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value or "{}")
    except ValueError:
        frappe.throw(_("That request is not valid."))


# Public --------------------------------------------------------------------


def _cors(form) -> None:
    """Let a website the form allows read and submit it from the browser (a form is public; the sites are the owner's choice)."""
    origin = (frappe.get_request_header("Origin") or "").strip().rstrip("/")
    if not origin:
        return
    allowed = [o.strip().rstrip("/") for o in (form.allowed_origins or "").splitlines() if o.strip()]
    if not allowed or origin in allowed:
        frappe.local.response_headers["Access-Control-Allow-Origin"] = origin
        frappe.local.response_headers["Vary"] = "Origin"


@frappe.whitelist(allow_guest=True, methods=["GET"])
def config(slug: str | None = None) -> dict:
    form = capture_service.get_form(slug)
    if not form:
        frappe.local.response.http_status_code = 404
        return {}
    _cors(form)
    return capture_service.public_config(form)


def _posted() -> dict:
    """What the visitor sent. Frappe hands a function only the arguments in its signature, so the rest is read from the request
    body itself (live test: reading ``form_dict`` alone saw nothing but the key)."""
    data: dict = {}
    request = getattr(frappe, "request", None)
    if request is not None:
        try:
            data.update({k: v for k, v in request.form.items() if isinstance(v, str)})
        except Exception:
            pass
    for key, value in frappe.form_dict.items():
        if isinstance(value, (str, int, float)):
            data.setdefault(key, value)
    return data


@frappe.whitelist(allow_guest=True, methods=["POST"])
def submit(slug: str | None = None) -> dict:
    """A visitor's signup. The form's key says which Company it is; everything else is untrusted."""
    form = capture_service.get_form(slug)
    if not form:
        frappe.local.response.http_status_code = 404
        return {"ok": False, "errors": {"form": _("This form is not available.")}}
    _cors(form)
    frappe.set_user("Administrator")  # the visitor is nobody; the Company is decided by the form, never by the visitor
    data = _posted()
    ip = str(getattr(frappe.local, "request_ip", "") or "")[:64]
    try:
        result = capture_service.submit(slug, data, ip)
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        frappe.log_error(title="Sales Agent signup failed")
        frappe.local.response.http_status_code = 500
        return {"ok": False, "errors": {"form": _("Something went wrong. Please try again.")}}
    return result


def _page(title: str, body: str, accent: str = capture.DEFAULT_ACCENT, status: int = 200) -> Response:
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>{escape_html(title)}</title><style>
body{{margin:0;font-family:system-ui,-apple-system,Segoe UI,sans-serif;background:#f6f7fb;color:#1f2430}}
main{{max-width:460px;margin:8vh auto;padding:0 16px}}.card{{background:#fff;border-radius:12px;padding:28px;box-shadow:0 2px 14px rgba(0,0,0,.07)}}
h1{{margin:0 0 8px;font-size:1.4rem}}p{{line-height:1.5;color:#4a5160}}button,.btn{{background:{capture.accent(accent)};color:#fff;border:0;border-radius:8px;
padding:11px 20px;font-size:1rem;cursor:pointer;text-decoration:none;display:inline-block}}</style></head><body><main><div class="card">{body}</div></main></body></html>"""
    return Response(html, status=status, mimetype="text/html")


@frappe.whitelist(allow_guest=True, methods=["GET"])
def page(slug: str | None = None):
    """The hosted page of a form: a page of its own that shows the form (the form script does the rest)."""
    form = capture_service.get_form(slug)
    if not form:
        return _page("Form not found", "<h1>This form is not available</h1><p>The link may be old.</p>", status=404)
    accent = capture.accent(form.accent_color)
    base = get_url()
    body = (f'<h1>{escape_html(form.headline or form.form_name)}</h1><p>{escape_html(form.description or "")}</p><div id="rsa-form"></div>'
            f'<noscript><p>Please turn on JavaScript to sign up.</p></noscript>'
            f'<script src="{escape_html(base)}/assets/reckon_sales_agent/js/rsa_form.js" data-form="{escape_html(form.slug)}" '
            f'data-mode="inline" data-target="#rsa-form" data-bare="1" defer></script>')
    return _page(form.headline or form.form_name, body, accent)


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def confirm(token: str | None = None):
    """GET shows a button; only the POST confirms, because mail scanners open links in advance."""
    token = str(token or "")
    exists = len(token) == 32 and token.isalnum() and frappe.db.exists("Sales Prospect", {"optin_token": token})
    if not exists:
        return _page("Link not valid", "<h1>This link is not valid</h1><p>It may already have been used.</p>", status=404)
    if frappe.request and frappe.request.method == "POST":
        frappe.set_user("Administrator")
        capture_service.confirm(token)
        frappe.db.commit()
        return _page("Confirmed", "<h1>You're confirmed</h1><p>Thank you. You will hear from us soon.</p>")
    return _page("Confirm your email", f'<h1>Confirm your email</h1><p>One click and you are on the list.</p>'
                 f'<form method="post" action="/api/method/reckon_sales_agent.api_capture.confirm">'
                 f'<input type="hidden" name="token" value="{escape_html(token)}"><button type="submit">Confirm my email</button></form>')


# Management ----------------------------------------------------------------


def _form_row(doc) -> dict:
    return {"name": doc.name, "slug": doc.slug, "form_name": doc.form_name, "status": doc.status, "form_type": doc.form_type,
            "submissions": doc.submissions or 0, "confirmed": doc.confirmed_count or 0,
            "last_submission": str(doc.last_submission or ""), "double_opt_in": bool(doc.double_opt_in)}


@frappe.whitelist()
def forms() -> list[dict]:
    company = current_company()
    assert_entitled(company)
    names = frappe.get_all("Sales Capture Form", filters={"company": company}, pluck="name", order_by="modified desc", limit=200)
    return [_form_row(frappe.get_doc("Sales Capture Form", n)) for n in names]


@frappe.whitelist()
def form(name: str) -> dict:
    doc = get_tenant_doc("Sales Capture Form", name, "read")
    data = {k: doc.get(k) for k in FORM_FIELDS}
    data.update(name=doc.name, slug=doc.slug, fields=capture.clean_fields(json.loads(doc.fields_json or "[]")),
                submissions=doc.submissions or 0, confirmed=doc.confirmed_count or 0)
    recent = frappe.get_all("Sales Prospect", filters={"company": doc.company, "signup_form": doc.slug},
                            fields=["name", "email", "contact_name", "signup_at", "optin_status"], order_by="signup_at desc", limit=RECENT)
    data["recent"] = [{"name": r.name, "email": r.email, "person": r.contact_name or "", "at": str(r.signup_at or ""),
                       "status": r.optin_status or "Subscribed"} for r in recent]
    return data


@frappe.whitelist(methods=["POST"])
def save_form(data) -> dict:
    _require_manager()
    company = current_company()
    assert_entitled(company)
    values = _json(data)
    doc = get_tenant_doc("Sales Capture Form", values["name"], "write") if values.get("name") else frappe.new_doc("Sales Capture Form")
    if doc.is_new():
        doc.company = company
    for field in FORM_FIELDS:
        if field in values:
            doc.set(field, values[field])
    rows = capture.clean_fields(values.get("fields") or [])
    keys = {r["key"] for r in rows}
    if (doc.ask_sms or doc.ask_whatsapp) and "phone" not in keys:
        rows.append({"key": "phone", "label": "Phone", "required": False})  # an opt-in needs a number to apply to
    doc.fields_json = json.dumps(rows)
    doc.save()
    return {"name": doc.name, "slug": doc.slug}


@frappe.whitelist(methods=["POST"])
def delete_form(name: str) -> None:
    _require_manager()
    doc = get_tenant_doc("Sales Capture Form", name, "delete")
    frappe.delete_doc("Sales Capture Form", doc.name)


@frappe.whitelist()
def embed_paths(name: str) -> dict:
    """Paths only: the page builds the full addresses from the domain it is open on, so a new domain needs no change."""
    doc = get_tenant_doc("Sales Capture Form", name, "read")
    return {"slug": doc.slug, "hosted": f"/f/{doc.slug}", "script": "/assets/reckon_sales_agent/js/rsa_form.js",
            "mode": "popup" if doc.form_type == "Popup" else "inline"}

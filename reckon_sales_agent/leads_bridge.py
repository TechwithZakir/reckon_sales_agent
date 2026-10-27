"""Meta lead ads bridge: a lead from a Facebook or Instagram lead form gets a fast, governed follow-up.

Frappe CRM's own Lead Syncing pulls the form submissions into CRM Leads (Settings → Lead Syncing). This module:

- gives those leads their Company (``crm_tenancy.lead_form_company``), since background syncs carry none;
- turns each one into an approved Sales Prospect: the person asked to be contacted, so no review is
  needed, and the form is recorded as the consent source;
- starts the speed-to-lead flow at once: a high-priority call task due today with the form's answers, website
  research when there is a site, and an AI-drafted first reply waiting for approval (omni-channel agent).

``prospect_fields`` is pure.
"""

from __future__ import annotations

import json

SOURCE = "meta_lead_ads"
CONSENT = "Meta lead form"


def prospect_fields(lead: dict, form: str = "Meta") -> dict:
    """Sales Prospect values from a synced CRM Lead (or another lead form's answers)."""
    person = " ".join(filter(None, [lead.get("first_name"), lead.get("last_name")])).strip()
    name = (lead.get("organization") or person or lead.get("email") or lead.get("mobile_no") or "Meta lead").strip()
    provided = {"source": "lead_form", "retrieved_at": str(lead.get("creation") or ""), "retention_days": None,
                "attribution": f"Submitted by the person on a {form} lead form"}
    fields = {"business_name": name[:140], "email": lead.get("email"), "phone": lead.get("mobile_no") or lead.get("phone"),
              "website": lead.get("website"), "industry": lead.get("industry"),
              "contact_person": person or None}
    return {**{k: v for k, v in fields.items() if v},
            "provenance_json": json.dumps({k: provided for k, v in fields.items() if v}, sort_keys=True)}


# --------------------------------------------------------------------------- Frappe side


def on_crm_lead_insert(doc, method=None) -> None:
    """``CRM Lead.after_insert``: a lead synced from a Meta lead form starts the speed-to-lead flow."""
    import frappe

    if not doc.get("facebook_lead_id") or not doc.get("rsa_company"):
        return
    frappe.enqueue("reckon_sales_agent.leads_bridge.speed_to_lead", queue="short", enqueue_after_commit=True,
                   lead=doc.name)


def speed_to_lead(lead: str) -> str | None:
    import frappe

    doc = frappe.get_doc("CRM Lead", lead)
    company = doc.get("rsa_company")
    if not company or frappe.db.exists("Sales Prospect", {"crm_lead": lead}):
        return None
    lead_id = doc.get("facebook_lead_id")
    known = frappe.db.get_value("Sales Prospect", {"company": company, "external_id": lead_id}) if lead_id else None
    if known:
        # Already received in real time through the Page webhook: just link the CRM's synced lead.
        frappe.db.set_value("Sales Prospect", known, "crm_lead", lead, update_modified=False)
        return known
    return inbound_lead(company, prospect_fields(doc.as_dict()), SOURCE, CONSENT, lead_id, crm_lead=lead,
                        label="Meta ad", note=f"Lead form {doc.get('facebook_form_id') or ''}")


def inbound_lead(company: str, values: dict, source: str, consent: str, external_id: str | None,
                 crm_lead: str | None = None, label: str = "lead form", note: str = "") -> str | None:
    """A person asked to be contacted: an approved prospect, a call task due now, research and a first reply draft."""
    import frappe
    from frappe.utils import now_datetime

    from reckon_sales_agent.usage import get_settings, log_activity

    if external_id and frappe.db.exists("Sales Prospect", {"company": company, "external_id": external_id}):
        return None  # delivered twice (webhook retry, or both the webhook and the scheduled sync)
    meta = frappe.get_meta("Sales Prospect")
    prospect = frappe.get_doc({
        "doctype": "Sales Prospect", "company": company, "source_type": source, "review_status": "Approved",
        "consent_source": consent, "crm_lead": crm_lead, "first_seen": now_datetime(), "last_seen": now_datetime(),
        "external_id": external_id,
        **{k: v for k, v in values.items() if meta.has_field(k)},
    }).insert(ignore_permissions=True)
    if crm_lead and frappe.db.has_column("CRM Lead", "rsa_prospect"):
        frappe.db.set_value("CRM Lead", crm_lead, "rsa_prospect", prospect.name, update_modified=False)
    log_activity(company, f"{source}_received", prospect, note or label, actor_type="agent", agent="Conversations",
                 policy_outcome="automatic (inbound lead asked for contact)")
    settings = get_settings(company)
    if prospect.phone or prospect.email:
        from reckon_sales_agent.providers.channels import create_task

        answers = "\n".join(f"{k}: {v}" for k, v in values.items() if k not in ("provenance_json",) and v)
        create_task(prospect.name, f"New lead from a {label}: call now · {prospect.business_name}",
                    "They filled in your lead form, so call while it is fresh.\n" + answers,
                    frappe._dict({**settings.as_dict(), "task_due_days": 0}), priority="High")
    if prospect.website:
        from reckon_sales_agent.jobs import enqueue_research

        enqueue_research(company, [prospect.name])
    if settings.ai_enabled:
        from reckon_sales_agent.agents.omni import draft_reply

        try:
            draft_reply(prospect.name, reason=f"new inbound lead from a {label}")
        except frappe.ValidationError:
            frappe.clear_messages()  # no channel to answer on yet: the call task covers it
    frappe.db.commit()
    return prospect.name


# --------------------------------------------------------------------------- real-time Meta lead ads


def meta_lead_values(field_data: list[dict]) -> dict:
    """Prospect values from a Graph API lead's ``field_data`` ([{name, values: [...]}])."""
    raw = {}
    for item in field_data or []:
        name = str(item.get("name") or "").lower()
        values = item.get("values") or []
        if name and values and str(values[0]).strip():
            raw[name] = str(values[0]).strip()
    person = raw.get("full_name") or " ".join(filter(None, [raw.get("first_name"), raw.get("last_name")])).strip()
    lead = {"first_name": person or None, "organization": raw.get("company_name"), "email": raw.get("email")
            or raw.get("work_email"), "mobile_no": raw.get("phone_number") or raw.get("work_phone_number"),
            "website": raw.get("website")}
    values = prospect_fields(lead)
    if raw.get("city"):
        values["city"] = raw["city"][:140]
    return values


def leadgen_events(payload: dict) -> list[dict]:
    """New lead ad submissions from a Page webhook call: [{page_id, leadgen_id, form_id}]."""
    if payload.get("object") != "page":
        return []
    out = []
    for entry in payload.get("entry") or []:
        for change in (entry.get("changes") or []) if isinstance(entry, dict) else []:
            value = change.get("value") if isinstance(change, dict) else None
            if change.get("field") == "leadgen" and isinstance(value, dict) and value.get("leadgen_id"):
                out.append({"page_id": str(value.get("page_id") or entry.get("id") or ""),
                            "leadgen_id": str(value["leadgen_id"]), "form_id": str(value.get("form_id") or "")})
    return out


def receive_meta_lead(page_id: str, leadgen_id: str, form_id: str = "") -> str | None:
    """Fetch one lead ad submission with the Page's token and start the speed-to-lead flow at once."""
    import frappe
    import requests

    row = frappe.db.get_value("Sales Social Account", {"platform": "Facebook Page", "account_id": page_id,
                                                       "enabled": 1}, ["name", "company"], as_dict=True)
    if not row or frappe.db.exists("Sales Prospect", {"company": row.company, "external_id": leadgen_id}):
        return None
    token = frappe.get_doc("Sales Social Account", row.name).get_password("access_token", raise_exception=False)
    response = requests.get(f"https://graph.facebook.com/v23.0/{leadgen_id}",
                            params={"fields": "field_data,created_time,form_id", "access_token": token}, timeout=30)
    if response.status_code >= 400:
        from reckon_sales_agent.providers.llm import http_reason

        frappe.throw(f"Meta refused the lead: {http_reason(response)}")
    values = meta_lead_values((response.json() or {}).get("field_data") or [])
    return inbound_lead(row.company, values, SOURCE, CONSENT, leadgen_id, label="Meta ad",
                        note=f"Lead form {form_id} (real time)")


# --------------------------------------------------------------------------- LinkedIn Lead Gen forms


LINKEDIN_SOURCE = "linkedin_lead_gen"
LINKEDIN_CONSENT = "LinkedIn lead form"
LINKEDIN_FIELDS = {"FIRST_NAME": "first_name", "LAST_NAME": "last_name", "EMAIL": "email",
                   "PHONE_NUMBER": "mobile_no", "COMPANY_NAME": "organization", "CITY": "city",
                   "COMPANY_WEBSITE": "website", "WEBSITE": "website", "JOB_TITLE": "job_title"}


def linkedin_lead_values(response: dict, questions: dict[str, str]) -> dict:
    """Prospect values from one ``leadFormResponses`` element; ``questions`` maps questionId -> predefined field."""
    lead: dict = {}
    for answer in ((response.get("formResponse") or {}).get("answers") or []):
        field = LINKEDIN_FIELDS.get(questions.get(str(answer.get("questionId")), ""))
        text = ((answer.get("answerDetails") or {}).get("textQuestionAnswer") or {}).get("answer")
        if field and text:
            lead[field] = str(text).strip()
    city = lead.pop("city", None)
    values = prospect_fields(lead, form="LinkedIn")
    if city:
        values["city"] = city[:140]
    return values


def form_questions(form: dict) -> dict[str, str]:
    """questionId -> predefined field (FIRST_NAME, EMAIL...) from a ``leadForms`` record."""
    out = {}
    for question in ((form.get("content") or {}).get("questions") or form.get("questions") or []):
        predefined = question.get("predefinedField") or question.get("name")
        if question.get("questionId") is not None and predefined:
            out[str(question["questionId"])] = str(predefined)
    return out


def sync_linkedin_leads() -> int:
    """Hourly: new LinkedIn lead form responses for every connected LinkedIn Lead Gen account."""
    import frappe
    from frappe.utils import now_datetime

    total = 0
    for row in frappe.get_all("Sales Social Account", filters={"platform": "LinkedIn Lead Gen", "enabled": 1},
                              pluck="name"):
        account = frappe.get_doc("Sales Social Account", row)
        try:
            total += _sync_linkedin_account(account)
            account.db_set({"last_error": None, "synced_until": now_datetime()})
        except Exception as exc:
            frappe.db.rollback()
            frappe.db.set_value("Sales Social Account", row, "last_error", str(exc)[:500])
        frappe.db.commit()
    return total


def _sync_linkedin_account(account) -> int:
    import time
    from urllib.parse import quote

    import frappe
    import requests
    from frappe.utils import get_datetime

    from reckon_sales_agent.agents.social_connect import LINKEDIN_VERSION

    token = account.get_password("access_token", raise_exception=False)
    headers = {"Authorization": f"Bearer {token}", "LinkedIn-Version": LINKEDIN_VERSION,
               "X-Restli-Protocol-Version": "2.0.0"}
    since = int(get_datetime(account.get("synced_until")).timestamp() * 1000) if account.get("synced_until") \
        else int((time.time() - 7 * 86400) * 1000)
    owner = quote(f"urn:li:organization:{account.account_id}", safe="")
    base = (f"https://api.linkedin.com/rest/leadFormResponses?q=owner&owner=(organization:{owner})"
            f"&leadType=(leadType:SPONSORED)&submittedAtTimeRange=(start:{since},end:{int(time.time() * 1000)})"
            "&limitedToTestLeads=false&count=100")
    elements: list = []
    for page in range(20):  # up to 2,000 answers an hour
        response = requests.get(f"{base}&start={page * 100}", headers=headers, timeout=30)
        if response.status_code >= 400:
            from reckon_sales_agent.providers.llm import http_reason

            raise RuntimeError(f"LinkedIn refused the lead sync: {http_reason(response)}")
        batch = (response.json() or {}).get("elements") or []
        elements += batch
        if len(batch) < 100:
            break
    forms: dict[str, dict] = {}
    created = 0
    for element in elements:
        form_urn = str(element.get("versionedLeadGenFormUrn") or element.get("leadGenFormUrn") or "")
        form_id = form_urn.split(":")[-1].split(",")[0].strip("()")
        if form_id and form_id not in forms:
            form = requests.get(f"https://api.linkedin.com/rest/leadForms/{form_id}", headers=headers, timeout=30)
            forms[form_id] = form_questions(form.json() if form.status_code < 400 else {})
        values = linkedin_lead_values(element, forms.get(form_id, {}))
        if inbound_lead(account.company, values, LINKEDIN_SOURCE, LINKEDIN_CONSENT,
                        f"linkedin:{element.get('id')}"[:140], label="LinkedIn ad", note=f"LinkedIn form {form_id}"):
            created += 1
    frappe.db.commit()
    return created

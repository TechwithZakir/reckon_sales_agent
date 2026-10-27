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


def prospect_fields(lead: dict) -> dict:
    """Sales Prospect values from a synced CRM Lead."""
    person = " ".join(filter(None, [lead.get("first_name"), lead.get("last_name")])).strip()
    name = (lead.get("organization") or person or lead.get("email") or lead.get("mobile_no") or "Meta lead").strip()
    provided = {"source": "lead_form", "retrieved_at": str(lead.get("creation") or ""), "retention_days": None,
                "attribution": "Submitted by the person on a Meta lead form"}
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
    from frappe.utils import now_datetime

    from reckon_sales_agent.usage import get_settings, log_activity

    doc = frappe.get_doc("CRM Lead", lead)
    company = doc.get("rsa_company")
    if not company or frappe.db.exists("Sales Prospect", {"crm_lead": lead}):
        return None
    values = prospect_fields(doc.as_dict())
    meta = frappe.get_meta("Sales Prospect")
    prospect = frappe.get_doc({
        "doctype": "Sales Prospect", "company": company, "source_type": SOURCE, "review_status": "Approved",
        "consent_source": CONSENT, "crm_lead": lead, "first_seen": now_datetime(), "last_seen": now_datetime(),
        "external_id": doc.get("facebook_lead_id"),
        **{k: v for k, v in values.items() if meta.has_field(k)},
    }).insert(ignore_permissions=True)
    if frappe.db.has_column("CRM Lead", "rsa_prospect"):
        frappe.db.set_value("CRM Lead", lead, "rsa_prospect", prospect.name, update_modified=False)
    log_activity(company, "meta_lead_received", prospect, f"Lead form {doc.get('facebook_form_id') or ''}",
                 actor_type="agent", agent="Engagement", policy_outcome="automatic (inbound lead asked for contact)")
    settings = get_settings(company)
    if prospect.phone or prospect.email:
        from reckon_sales_agent.providers.channels import create_task

        answers = "\n".join(f"{k}: {v}" for k, v in values.items() if k not in ("provenance_json",) and v)
        create_task(prospect.name, f"New lead from a Meta ad: call now · {prospect.business_name}",
                    "They filled in your lead form, so call while it is fresh.\n" + answers,
                    frappe._dict({**settings.as_dict(), "task_due_days": 0}), priority="High")
    if prospect.website:
        from reckon_sales_agent.jobs import enqueue_research

        enqueue_research(company, [prospect.name])
    if settings.ai_enabled:
        from reckon_sales_agent.agents.omni import draft_reply

        try:
            draft_reply(prospect.name, reason="new inbound lead from a Meta lead form")
        except frappe.ValidationError:
            frappe.clear_messages()  # no channel to answer on yet: the call task covers it
    frappe.db.commit()
    return prospect.name

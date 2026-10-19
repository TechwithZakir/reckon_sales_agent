"""Background job entry points: idempotent enqueueing and scheduled maintenance."""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import add_days, getdate, nowdate

from reckon_sales_agent.usage import get_settings, log_activity

RESEARCH_BATCH = 10
EXPIRED_NAME = "Expired source record"


def enqueue_discovery(campaign) -> str:
    """Start (or return the already running) discovery job for a campaign."""
    existing = frappe.db.get_value("Sales Discovery Job", {"discovery_campaign": campaign.name,
                                                           "status": ["in", ["Queued", "Running"]]})
    if existing:
        return existing
    settings = get_settings(campaign.company)
    active = frappe.db.count("Sales Discovery Job", {"company": campaign.company,
                                                     "status": ["in", ["Queued", "Running"]]})
    if active >= (settings.max_concurrent_jobs or 1):
        frappe.throw(_("Too many jobs are running for your Company. Try again when one finishes."))
    if not campaign.planned_queries:
        frappe.throw(_("Preview the planned searches first."))
    job = frappe.get_doc({
        "doctype": "Sales Discovery Job",
        "company": campaign.company,
        "job_type": "Discovery",
        "discovery_campaign": campaign.name,
        "status": "Queued",
        "idempotency_key": f"discovery:{campaign.name}:{frappe.generate_hash(length=10)}",
        "progress_total": len(campaign.planned_queries),
    }).insert(ignore_permissions=True)
    frappe.enqueue(
        "reckon_sales_agent.discovery.runner.run_discovery_job",
        queue="long",
        timeout=3600,
        job_id=f"sales_agent_discovery_{job.name}",
        deduplicate=True,
        enqueue_after_commit=True,
        job_name=job.name,
    )
    log_activity(campaign.company, "discovery_queued", job, campaign.name)
    return job.name


def next_run_date(schedule: str):
    from frappe.utils import add_months

    today = nowdate()
    return {"Daily": add_days(today, 1), "Weekly": add_days(today, 7)}.get(schedule) or add_months(today, 1)


def run_scheduled_discovery() -> None:
    """Daily: re-plan and start campaigns whose automatic run is due.

    Each run rebuilds the plan from the targeting profile (with AI expansion
    when enabled), so new keywords and locations apply; deduplication keeps
    re-runs from creating duplicates.
    """
    from reckon_sales_agent.discovery.runner import build_plan
    from reckon_sales_agent.usage import NotEntitled, assert_entitled

    today = getdate(nowdate())
    for name in frappe.get_all("Sales Discovery Campaign",
                               filters={"schedule": ["in", ["Daily", "Weekly", "Monthly"]],
                                        "status": ["!=", "Running"]}, pluck="name"):
        campaign = frappe.get_doc("Sales Discovery Campaign", name)
        if campaign.next_run_on and getdate(campaign.next_run_on) > today:
            continue
        try:
            assert_entitled(campaign.company)
            build_plan(campaign)
            campaign.flags.ignore_permissions = True
            campaign.save()
            campaign.db_set({"status": "Planned", "next_run_on": next_run_date(campaign.schedule)})
            enqueue_discovery(campaign)
            frappe.db.commit()
        except NotEntitled:
            frappe.db.rollback()
        except Exception:
            frappe.db.rollback()
            frappe.log_error(title="Sales Agent scheduled discovery failed",
                             reference_doctype="Sales Discovery Campaign", reference_name=name)


def enqueue_research(company: str, prospect_names: list[str]) -> None:
    for start in range(0, len(prospect_names), RESEARCH_BATCH):
        batch = prospect_names[start:start + RESEARCH_BATCH]
        for name in batch:
            frappe.db.set_value("Sales Prospect", name, "research_status", "Queued", update_modified=False)
        frappe.enqueue(
            "reckon_sales_agent.jobs.research_batch",
            queue="long",
            timeout=1800,
            enqueue_after_commit=True,
            prospect_names=batch,
        )


def research_batch(prospect_names: list[str]) -> None:
    from reckon_sales_agent.research.runner import research_prospect

    for name in prospect_names:
        try:
            research_prospect(name)
        except Exception:
            frappe.db.rollback()
            frappe.db.set_value("Sales Prospect", name, "research_status", "Failed")
            frappe.log_error(title="Sales Agent research failed", reference_doctype="Sales Prospect",
                             reference_name=name)
        frappe.db.commit()


def purge_expired_source_data() -> None:
    """Daily: drop fields whose source-allowed retention has passed, and old rejected prospects."""
    today = getdate(nowdate())
    for name in frappe.get_all("Sales Prospect", filters={"retention_until": ["<", today]}, pluck="name",
                               limit=5000):
        prospect = frappe.get_doc("Sales Prospect", name)
        provenance = json.loads(prospect.provenance_json or "{}")
        updates = {}
        for field, info in list(provenance.items()):
            info = info or {}
            if info.get("retention_days") and info.get("source") != "company_website":
                updates[field] = EXPIRED_NAME if field == "business_name" else None
                provenance.pop(field)
        updates.update({"provenance_json": json.dumps(provenance, sort_keys=True), "retention_until": None})
        if "website" in updates:
            updates["domain"] = None
        if "phone" in updates:
            updates["normalized_phone"] = None
        if "business_name" in updates:
            updates["normalized_name"] = None
        prospect.db_set(updates, update_modified=False)
        log_activity(prospect.company, "source_data_expired", prospect,
                     ", ".join(sorted(k for k in updates if k not in ("provenance_json", "retention_until"))),
                     "system")
    for company in frappe.get_all("Sales Agent Settings", pluck="name"):
        days = get_settings(company).retention_days or 365
        cutoff = add_days(today, -days)
        for name in frappe.get_all("Sales Prospect", filters={"company": company, "review_status": "Rejected",
                                                              "modified": ["<", cutoff]}, pluck="name", limit=2000):
            if frappe.db.exists("Sales Campaign Member", {"prospect": name}):
                continue  # keep outreach history intact
            for doctype in ("Sales Research Report", "Sales Qualification"):
                for linked in frappe.get_all(doctype, filters={"prospect": name}, pluck="name"):
                    frappe.delete_doc(doctype, linked, ignore_permissions=True, force=True)
            frappe.delete_doc("Sales Prospect", name, ignore_permissions=True, force=True)
    frappe.db.commit()


def recover_stuck_jobs() -> None:
    """Hourly: jobs still 'Running' after the worker died are failed so they can be re-run."""
    cutoff = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=-3)
    for name in frappe.get_all("Sales Discovery Job", filters={"status": "Running", "modified": ["<", cutoff]},
                               pluck="name"):
        frappe.db.set_value("Sales Discovery Job", name, {"status": "Failed", "error_code": "worker_lost",
                                                          "error_detail": "No progress for 3 hours."})
    frappe.db.commit()

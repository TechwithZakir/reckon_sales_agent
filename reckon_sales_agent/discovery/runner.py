"""Background discovery: planned searches -> policy-checked, deduplicated prospects.

Jobs work query by query. After each query the job commits its checkpoint
(the planned row's status and the counters), so a retry resumes where it
stopped and a re-run creates no duplicates. The transaction is committed
before every network call, so no database transaction is held open while
waiting on a source.
"""

from __future__ import annotations

import json
import time

import frappe
from frappe import _
from frappe.utils import getdate, now_datetime, nowdate

from reckon_sales_agent.connectors.base import ConnectorError, DiscoveryQuery
from reckon_sales_agent.connectors.registry import build_connector, field_policy
from reckon_sales_agent.constants import USAGE_DISCOVERY
from reckon_sales_agent.discovery.dedup import find_duplicate, find_possible_duplicate
from reckon_sales_agent.discovery.normalize import (
    apply_field_policy,
    normalize_domain,
    normalize_email,
    normalize_name,
    normalize_phone,
)
from reckon_sales_agent.discovery.planner import plan_queries
from reckon_sales_agent.usage import get_settings, log_activity, remaining, reserve

MAX_ATTEMPTS = 3


def _targeting(campaign) -> dict | None:
    if not campaign.get("targeting_profile"):
        return None
    profile = frappe.get_doc("Sales Targeting Profile", campaign.targeting_profile)
    data = profile.as_dict()
    if campaign.get("use_ai_planner"):
        from reckon_sales_agent.discovery.ai_planner import suggest
        from reckon_sales_agent.discovery.targeting import merge_lines

        suggestions = suggest(profile, raise_errors=False)
        if suggestions:
            data["keywords"] = merge_lines(data.get("keywords"),
                                           suggestions["keywords"] + suggestions["bangla_keywords"])
            data["exclude_keywords"] = merge_lines(data.get("exclude_keywords"), suggestions["exclude_keywords"])
    return data


def build_plan(campaign) -> None:
    """Fill the campaign's planned searches (a preview the user sees before running).

    With a targeting profile, the plan comes from its locations, keywords,
    segments and industries, optionally widened by Claude's suggestions.
    """
    from reckon_sales_agent.discovery.targeting import plan_from_profile

    settings = get_settings(campaign.company)
    targeting = _targeting(campaign)
    if targeting:
        plan = plan_from_profile(targeting, campaign.target_count or 0, campaign.per_query_limit or 20,
                                 settings.max_results_per_job or 100)
    else:
        plan = plan_queries(
            campaign.industries,
            campaign.keywords,
            campaign.locations,
            campaign.target_count or 0,
            campaign.per_query_limit or 20,
            settings.max_results_per_job or 100,
        )
    if not plan:
        frappe.throw(_("Add at least one keyword or industry."))
    campaign.set("planned_queries", [])
    for item in plan:
        campaign.append("planned_queries", {
            "keyword": item.keyword,
            "location": item.location,
            "query_text": item.query_text,
            "max_results": item.max_results,
            "status": "Planned",
        })
    campaign.status = "Planned"


def run_discovery_job(job_name: str) -> None:
    job = frappe.get_doc("Sales Discovery Job", job_name)
    if job.status not in ("Queued", "Running"):
        return
    campaign = frappe.get_doc("Sales Discovery Campaign", job.discovery_campaign)
    _start(job, campaign)
    try:
        connector_doc = frappe.get_doc("Sales Source Connector", campaign.source_connector)
        connector = build_connector(connector_doc)
        policy = field_policy(connector_doc, connector)
    except ConnectorError as exc:
        _finish(job, campaign, "Failed", exc.code, str(exc))
        return

    from reckon_sales_agent.discovery.targeting import excluded

    targeting = (frappe.get_doc("Sales Targeting Profile", campaign.targeting_profile).as_dict()
                 if campaign.get("targeting_profile") else {})
    new_prospects: list[str] = []
    for row in campaign.planned_queries:
        if row.status != "Planned":
            continue
        if frappe.db.get_value("Sales Discovery Job", job.name, "cancel_requested"):
            _finish(job, campaign, "Cancelled")
            return
        allowed = remaining(job.company, USAGE_DISCOVERY)
        if allowed <= 0:
            _finish(job, campaign, "Failed", "quota_exceeded", _("Monthly discovery limit reached."))
            return
        query = DiscoveryQuery(row.keyword, row.location or "", row.query_text,
                               min(row.max_results or 20, allowed))
        frappe.db.commit()  # never hold a transaction across the network call
        try:
            records = _discover_with_retry(connector, query, job)
        except ConnectorError as exc:
            row.db_set("status", "Failed")
            frappe.db.commit()
            if exc.permanent:
                _finish(job, campaign, "Failed", exc.code, str(exc))
                return
            continue
        created = updated = 0
        for record in records:
            if targeting and excluded(" ".join(str(v) for v in record.fields.values() if v), targeting):
                continue
            outcome, prospect = upsert_prospect(job.company, campaign, connector_doc, record, policy)
            if outcome == "created":
                created += 1
                new_prospects.append(prospect)
            elif outcome == "duplicate":
                updated += 1
        if records:
            reserve(job.company, USAGE_DISCOVERY, len(records), job)
        row.db_set({"status": "Done", "results": len(records)})
        job.db_set({
            "progress_done": (job.progress_done or 0) + 1,
            "created_count": (job.created_count or 0) + created,
            "duplicate_count": (job.duplicate_count or 0) + updated,
        })
        frappe.db.commit()

    _finish(job, campaign, "Completed")
    if campaign.get("schedule"):
        from reckon_sales_agent.jobs import next_run_date

        campaign.db_set({"last_run_on": now_datetime(), "next_run_on": next_run_date(campaign.schedule)})
        frappe.db.commit()
    if campaign.auto_research and new_prospects:
        from reckon_sales_agent.jobs import enqueue_research

        enqueue_research(job.company, new_prospects)


def _discover_with_retry(connector, query: DiscoveryQuery, job) -> list:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return list(connector.discover(query))
        except ConnectorError as exc:
            if exc.permanent or attempt == MAX_ATTEMPTS:
                raise
            job.db_set("retry_count", (job.retry_count or 0) + 1)
            frappe.db.commit()
            time.sleep(2 ** attempt)
    return []


def upsert_prospect(company: str, campaign, connector_doc, record, policy: dict) -> tuple[str, str | None]:
    """Store one source record; returns ("created" | "duplicate" | "skipped", prospect)."""
    kept, provenance, retention_until = apply_field_policy(
        record.fields, policy, record.retrieved_at, connector_doc.connector_type, getdate(nowdate())
    )
    if not kept.get("business_name"):
        return "skipped", None
    existing, reason = find_duplicate(company, connector_doc.name, record.external_id, kept)
    now = now_datetime()
    if existing:
        prospect = frappe.get_doc("Sales Prospect", existing)
        changed = False
        for field, value in kept.items():
            if not prospect.get(field):  # fill gaps only; never overwrite reviewed data
                prospect.set(field, value)
                changed = True
        merged = json.loads(prospect.provenance_json or "{}")
        for field, info in provenance.items():
            merged.setdefault(field, info)
        prospect.provenance_json = json.dumps(merged, sort_keys=True)
        prospect.last_seen = now
        if changed:
            _set_normalized(prospect)
        prospect.save(ignore_permissions=True)
        return "duplicate", prospect.name

    prospect = frappe.get_doc({
        "doctype": "Sales Prospect",
        "company": company,
        **kept,
        "discovery_campaign": campaign.name,
        "source_connector": connector_doc.name,
        "source_type": connector_doc.connector_type,
        "external_id": record.external_id,
        "source_url": record.source_url,
        "first_seen": now,
        "last_seen": now,
        "retention_until": retention_until,
        "provenance_json": json.dumps(provenance, sort_keys=True),
        "review_status": "Pending",
        "possible_duplicate_of": find_possible_duplicate(company, kept),
    })
    _set_normalized(prospect)
    from reckon_sales_agent.campaigns.suppression import is_suppressed

    if is_suppressed(company, email=prospect.email, phone=prospect.phone, website=prospect.website):
        prospect.do_not_contact = 1
        prospect.contactability = "Suppressed"
    prospect.insert(ignore_permissions=True)
    return "created", prospect.name


def _set_normalized(prospect) -> None:
    prospect.domain = normalize_domain(prospect.website)
    prospect.normalized_name = normalize_name(prospect.business_name)
    prospect.normalized_phone = normalize_phone(prospect.phone)
    if prospect.email:
        prospect.email = normalize_email(prospect.email) or None


def _start(job, campaign) -> None:
    job.db_set({
        "status": "Running",
        "started_at": job.started_at or now_datetime(),
        "progress_total": len(campaign.planned_queries),
    })
    campaign.db_set({"status": "Running", "last_job": job.name})
    frappe.db.commit()


def _finish(job, campaign, status: str, code: str | None = None, detail: str | None = None) -> None:
    job.db_set({"status": status, "finished_at": now_datetime(), "error_code": code,
                "error_detail": (detail or "")[:500] or None})
    counts = frappe.db.get_all(
        "Sales Prospect",
        filters={"company": job.company, "discovery_campaign": campaign.name},
        fields=["count(name) as total", "sum(case when qualification_status='Qualified' then 1 else 0 end) as qualified"],
    )[0]
    campaign.db_set({
        "status": {"Completed": "Completed", "Cancelled": "Cancelled"}.get(status, "Planned"),
        "prospects_found": counts.total or 0,
        "qualified_count": counts.qualified or 0,
        "duplicates_found": (campaign.duplicates_found or 0) + (job.duplicate_count or 0),
    })
    log_activity(job.company, f"discovery_{status.lower()}", job, detail or "", actor_type="system")
    frappe.db.commit()

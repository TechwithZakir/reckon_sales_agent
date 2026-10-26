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
    URL_FIELDS,
    apply_field_policy,
    fit_length,
    normalize_domain,
    normalize_email,
    normalize_name,
    normalize_phone,
)
from reckon_sales_agent.discovery.planner import split_lines
from reckon_sales_agent.research.identity import identity_confidence, merge_sources
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
    from reckon_sales_agent.discovery.planner import spread_plan
    from reckon_sales_agent.discovery.targeting import plan_with_cursor

    settings = get_settings(campaign.company)
    targeting = _targeting(campaign)
    start = int(campaign.get("plan_cursor") or 0)  # continue where the last completed run stopped
    if targeting:
        plan, next_start = plan_with_cursor(targeting, campaign.target_count or 0, campaign.per_query_limit or 20,
                                            settings.max_results_per_job or 100, start)
    else:
        terms = split_lines(campaign.keywords) or split_lines(campaign.industries)
        plan, next_start = spread_plan(terms, split_lines(campaign.locations), campaign.target_count or 0,
                                       campaign.per_query_limit or 20, settings.max_results_per_job or 100, start)
    campaign.plan_cursor_next = next_start
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


def run_discovery_job(discovery_job: str | None = None, **kwargs) -> None:
    # Not called ``job_name``: frappe.enqueue reserves that argument for the RQ job label.
    discovery_job = discovery_job or kwargs.get("job_name")
    if not discovery_job:
        frappe.throw(_("No discovery job given."))
    job = frappe.get_doc("Sales Discovery Job", discovery_job)
    if job.status not in ("Queued", "Running"):
        return
    campaign = frappe.get_doc("Sales Discovery Campaign", job.discovery_campaign)
    _start(job, campaign)
    try:
        _run(job, campaign)
    except Exception as exc:
        # Never leave a job "Running" after a crash; the traceback goes to the Error Log.
        frappe.db.rollback()
        frappe.log_error(title="Sales Agent discovery job crashed", reference_doctype="Sales Discovery Job",
                         reference_name=job.name)
        job.reload()
        _finish(job, campaign, "Failed", "internal_error", str(exc))


def _run(job, campaign) -> None:
    if not any(row.status == "Planned" for row in campaign.planned_queries):
        _finish(job, campaign, "Failed", "nothing_planned",
                _("Every planned search has already run. Preview the searches again, then start."))
        return
    try:
        connector_doc = frappe.get_doc("Sales Source Connector", campaign.source_connector)
        connector = build_connector(connector_doc)
        policy = field_policy(connector_doc, connector)
    except ConnectorError as exc:
        _finish(job, campaign, "Failed", exc.code, str(exc))
        return

    from reckon_sales_agent.discovery.targeting import excluded, foreign_business, market_country

    targeting = (frappe.get_doc("Sales Targeting Profile", campaign.targeting_profile).as_dict()
                 if campaign.get("targeting_profile") else {})
    country = market_country(targeting)
    new_prospects: list[str] = []
    failed: list[ConnectorError] = []  # searches that still failed after retries
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
            failed.append(exc)
            continue
        created = updated = 0
        for record in records:
            if targeting and excluded(" ".join(str(v) for v in record.fields.values() if v), targeting):
                continue
            if foreign_business(record.fields, country):
                continue  # outside the market this campaign targets (e.g. an Indian company for Bangladesh)
            frappe.db.savepoint("sales_agent_record")
            try:
                outcome, prospect = upsert_prospect(job.company, campaign, connector_doc, record, policy)
            except Exception:
                # One malformed source record must not stop the rest of the search.
                frappe.db.rollback(save_point="sales_agent_record")
                frappe.log_error(title="Sales Agent could not store a discovered record",
                                 reference_doctype="Sales Discovery Job", reference_name=job.name)
                continue
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

    if failed and not (job.progress_done or 0):
        # Every search failed: say so, with the source's own reason, instead of "Completed".
        _finish(job, campaign, "Failed", failed[-1].code, str(failed[-1]))
        return
    if campaign.get("plan_cursor_next") is not None:
        campaign.db_set("plan_cursor", campaign.plan_cursor_next)  # next run searches the next pairs
    if failed:
        _finish(job, campaign, "Completed", failed[-1].code,
                _("{0} search(es) failed: {1}").format(len(failed), failed[-1]))
    else:
        _finish(job, campaign, "Completed")
    from reckon_sales_agent.jobs import next_run_date

    # Recorded for every run, so the autopilot knows when a segment was last searched.
    campaign.db_set({"last_run_on": now_datetime(),
                     **({"next_run_on": next_run_date(campaign.schedule)} if campaign.get("schedule") else {})})
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
        record.fields, policy, record.retrieved_at, record.source_key or connector_doc.connector_type, getdate(nowdate())
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
        prospect.sources_seen = merge_sources(prospect.get("sources_seen"), record.source_key, *record.corroborated_by)
        prospect.last_seen = now
        if changed:
            _set_normalized(prospect)
        _fit_lengths(prospect)
        prospect.save(ignore_permissions=True)
        return "duplicate", prospect.name

    prospect = frappe.get_doc({
        "doctype": "Sales Prospect",
        "company": company,
        **kept,
        "discovery_campaign": campaign.name,
        "source_connector": connector_doc.name,
        "source_type": record.source_key or connector_doc.connector_type,  # the provider that found it (Smart Sources)
        "external_id": record.external_id,
        "source_url": record.source_url,
        "first_seen": now,
        "last_seen": now,
        "retention_until": retention_until,
        "provenance_json": json.dumps(provenance, sort_keys=True),
        "review_status": "Pending",
        "possible_duplicate_of": find_possible_duplicate(company, kept),
        "sources_seen": merge_sources(None, record.source_key or connector_doc.connector_type, *record.corroborated_by),
    })
    confidence, reasons = identity_confidence(prospect.sources_seen.splitlines())
    prospect.identity_confidence = confidence
    prospect.identity_notes = " ".join(reasons)
    _set_normalized(prospect)
    from reckon_sales_agent.campaigns.suppression import is_suppressed

    if is_suppressed(company, email=prospect.email, phone=prospect.phone, website=prospect.website):
        prospect.do_not_contact = 1
        prospect.contactability = "Suppressed"
    _fit_lengths(prospect)
    prospect.insert(ignore_permissions=True)
    return "created", prospect.name


def _fit_lengths(doc) -> None:
    """Clip source text to its column so one long value cannot reject a whole record.

    Links are dropped rather than cut, since a truncated URL points somewhere else.
    """
    for df in doc.meta.get("fields", {"fieldtype": "Data"}):
        value = doc.get(df.fieldname)
        if isinstance(value, str):
            doc.set(df.fieldname, fit_length(value, df.length or 140, url=df.fieldname in URL_FIELDS
                                             or df.options == "URL"))


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
    in_campaign = {"company": job.company, "discovery_campaign": campaign.name}
    campaign.db_set({
        "status": {"Completed": "Completed", "Cancelled": "Cancelled"}.get(status, "Planned"),
        "prospects_found": frappe.db.count("Sales Prospect", in_campaign),
        "qualified_count": frappe.db.count("Sales Prospect", {**in_campaign, "qualification_status": "Qualified"}),
        "duplicates_found": (campaign.duplicates_found or 0) + (job.duplicate_count or 0),
    })
    log_activity(job.company, f"discovery_{status.lower()}", job, detail or "", actor_type="system")
    frappe.db.commit()

"""Backend for Lead Finder Studio: one page from source to running discovery job.

Every method resolves the user's Company on the server, checks document
permissions, and never returns secrets: connector availability is reported
as yes/no with a reason, not as keys.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import now_datetime

from reckon_sales_agent.constants import APPROVER_ROLES
from reckon_sales_agent.tenant import current_company, get_tenant_doc
from reckon_sales_agent.usage import (
    assert_entitled,
    get_settings,
    log_activity,
    platform_settings,
    usage_summary,
)

# Connector catalogue shown as icon cards. ``vendor`` lists the Platform
# Settings flags that must all be on; ``maps`` adds the Maps responsibility tick
# and ``ack`` names any other responsibility tick (Google Search).
CATALOG = (
    {"type": "scrapingbee_google_maps", "title": "Google Maps · ScrapingBee", "group": "Google Maps",
     "icon": "map", "subtitle": "Reliable Maps search through ScrapingBee's API.",
     "vendor": ("scrapingbee_enabled",), "maps": True},
    {"type": "scrapingdog_google_maps", "title": "Google Maps · Scrapingdog", "group": "Google Maps",
     "icon": "map", "subtitle": "Maps search through Scrapingdog's API.",
     "vendor": ("scrapingdog_enabled",), "maps": True},
    {"type": "serpapi_google_maps", "title": "Google Maps · SerpAPI", "group": "Google Maps",
     "icon": "map", "subtitle": "Maps search through SerpAPI.",
     "vendor": ("serpapi_enabled",), "maps": True},
    {"type": "apify_google_maps", "title": "Google Maps · Apify", "group": "Google Maps",
     "icon": "map", "subtitle": "Apify's Google Maps scraper; slower, very detailed.",
     "vendor": ("apify_enabled",), "maps": True},
    {"type": "google_places_api", "title": "Google Places API", "group": "Google Maps",
     "icon": "pin", "subtitle": "Google's official Places API.",
     "vendor": ("places_enabled", "places_terms_reviewed"), "maps": False},
    {"type": "google_maps_browser_experimental", "title": "Maps Browser Bot", "group": "Google Maps",
     "icon": "browser", "subtitle": "Experimental headless browser on maps.google.com.",
     "vendor": ("maps_browser_enabled",), "maps": True, "experimental": True},
    {"type": "scrapingdog_google_search", "title": "Google Search · Scrapingdog", "group": "Google Search",
     "icon": "search", "subtitle": "Business websites from Google results via Scrapingdog.",
     "vendor": ("search_scrapingdog_enabled",), "maps": False, "ack": "search_terms_ack"},
    {"type": "scrapingbee_google_search", "title": "Google Search · ScrapingBee", "group": "Google Search",
     "icon": "search", "subtitle": "Business websites from Google results via ScrapingBee.",
     "vendor": ("search_scrapingbee_enabled",), "maps": False, "ack": "search_terms_ack"},
    {"type": "serpapi_google_search", "title": "Google Search · SerpAPI", "group": "Google Search",
     "icon": "search", "subtitle": "Business websites from Google results via SerpAPI.",
     "vendor": ("search_serpapi_enabled",), "maps": False, "ack": "search_terms_ack"},
    {"type": "google_search_browser_experimental", "title": "Search Browser Bot", "group": "Google Search",
     "icon": "browser", "subtitle": "Experimental headless browser on google.com.",
     "vendor": ("search_browser_enabled",), "maps": False, "ack": "search_terms_ack", "experimental": True},
    {"type": "permitted_directory", "title": "Directory Crawler", "group": "Web",
     "icon": "globe", "subtitle": "Crawl a business directory you may use.",
     "vendor": ("research_enabled",), "maps": False, "needs_urls": True},
    {"type": "manual_import", "title": "CSV Import", "group": "Your data",
     "icon": "file", "subtitle": "Upload your own list of businesses.", "vendor": (), "maps": False},
    {"type": "fixture", "title": "Demo Data", "group": "Your data",
     "icon": "spark", "subtitle": "Fictional businesses for training. No network.", "vendor": (), "maps": False},
)
CATALOG_TYPES = {item["type"]: item for item in CATALOG}


def _payload(value) -> dict:
    if isinstance(value, str):
        value = json.loads(value or "{}")
    if not isinstance(value, dict):
        frappe.throw(_("Invalid request."))
    return value


def _lines(value) -> str:
    if isinstance(value, list):
        value = "\n".join(str(v) for v in value)
    lines = []
    for line in str(value or "").splitlines():
        item = " ".join(line.split())[:120]
        if item and item.lower() not in {x.lower() for x in lines}:
            lines.append(item)
    return "\n".join(lines[:60])


def _availability(item: dict, platform) -> tuple[bool, str]:
    missing = [flag for flag in item["vendor"] if not platform.get(flag)]
    if missing:
        return False, _("Not enabled by your provider yet.")
    if item["maps"] and not platform.get("maps_terms_ack"):
        return False, _("Your provider has not enabled Google Maps sources yet.")
    if item.get("ack") and not platform.get(item["ack"]):
        return False, _("Your provider has not enabled this source yet.")
    return True, _("Ready")


def _can_manage() -> bool:
    return frappe.session.user == "Administrator" or bool(set(frappe.get_roles()) & APPROVER_ROLES)


@frappe.whitelist()
def bootstrap() -> dict:
    company = current_company()
    platform = platform_settings()
    settings = get_settings(company)
    existing = {
        row.connector_type: row
        for row in frappe.get_list("Sales Source Connector",
                                   fields=["name", "connector_type", "enabled", "policy_reviewed", "last_health_status"],
                                   filters={"company": company}, order_by="modified desc", limit_page_length=100)
    }
    catalog = []
    for item in CATALOG:
        available, reason = _availability(item, platform)
        row = existing.get(item["type"])
        catalog.append({
            "type": item["type"], "title": _(item["title"]), "subtitle": _(item["subtitle"]), "group": _(item["group"]),
            "icon": item["icon"], "experimental": item.get("experimental", False),
            "needs_urls": item.get("needs_urls", False), "available": available, "reason": reason,
            "connector": row.name if row else None,
            "ready": bool(row and row.enabled and (row.policy_reviewed or item["type"] in ("fixture", "manual_import"))),
        })
    from reckon_sales_agent.jobs import worker_status

    return {
        "company": company,
        "can_manage": _can_manage(),
        "catalog": catalog,
        "profiles": frappe.get_list("Sales Targeting Profile", filters={"company": company},
                                    fields=["name", "profile_name", "market", "keywords", "b2b_segments", "industries",
                                            "interests", "exclude_keywords", "ai_suggestions"],
                                    order_by="modified desc", limit_page_length=50),
        "campaigns": frappe.get_list("Sales Discovery Campaign", filters={"company": company},
                                     fields=["name", "campaign_name", "status", "schedule", "next_run_on",
                                             "run_at_time", "last_job", "prospects_found", "targeting_profile",
                                             "source_connector"],
                                     order_by="modified desc", limit_page_length=20),
        "ai_available": bool(platform.get("ai_enabled") and settings.ai_enabled),
        "max_results_per_job": settings.max_results_per_job or 100,
        "usage": usage_summary(company),
        "workers": worker_status(),
    }


@frappe.whitelist()
def profile_locations(profile: str) -> list[dict]:
    doc = get_tenant_doc("Sales Targeting Profile", profile, "read")
    return [{"city": r.city, "area": r.area, "region": r.region} for r in doc.locations]


@frappe.whitelist()
def setup_connector(connector_type: str, confirm_policy: int = 0, start_urls: str | None = None) -> dict:
    """Create or enable the Company's connector of this type and report whether it can run."""
    from reckon_sales_agent.connectors.base import ConnectorError
    from reckon_sales_agent.connectors.registry import build_connector

    if connector_type not in CATALOG_TYPES:
        frappe.throw(_("Unknown source."))
    if not _can_manage():
        frappe.throw(_("Ask a Sales Agent admin or manager to set up sources."), frappe.PermissionError)
    company = current_company()
    item = CATALOG_TYPES[connector_type]
    name = frappe.db.get_value("Sales Source Connector", {"company": company, "connector_type": connector_type})
    doc = get_tenant_doc("Sales Source Connector", name, "write") if name else frappe.get_doc({
        "doctype": "Sales Source Connector", "company": company, "connector_type": connector_type,
        "connector_name": item["title"],
    })
    doc.enabled = 1
    if int(confirm_policy or 0) or connector_type in ("fixture", "manual_import"):
        doc.policy_reviewed = 1
    if item.get("needs_urls") and start_urls is not None:
        doc.start_urls = _lines(start_urls)
    doc.save() if name else doc.insert()
    try:
        build_connector(doc).validate_configuration()
        status, error = "ready", None
    except ConnectorError as exc:
        status, error = "not_ready", str(exc)
    doc.db_set({"last_health_status": f"{'OK' if status == 'ready' else 'Not ready'} · {now_datetime():%Y-%m-%d %H:%M}",
                "last_error": error})
    log_activity(company, "connector_setup", doc, status)
    return {"connector": doc.name, "status": status, "error": error}


@frappe.whitelist()
def save_targeting(data) -> str:
    data = _payload(data)
    company = current_company()
    if data.get("name"):
        doc = get_tenant_doc("Sales Targeting Profile", data["name"], "write")
    else:
        doc = frappe.get_doc({"doctype": "Sales Targeting Profile", "company": company})
    doc.profile_name = " ".join(str(data.get("profile_name") or "").split())[:140] or _("Targeting profile")
    if data.get("market") in ("B2B", "B2B2C", "B2G"):
        doc.market = data["market"]
    for field in ("keywords", "b2b_segments", "industries", "interests", "exclude_keywords"):
        doc.set(field, _lines(data.get(field)))
    doc.set("locations", [])
    for row in (data.get("locations") or [])[:40]:
        city = " ".join(str((row or {}).get("city") or "").split())[:80]
        if city:
            doc.append("locations", {"city": city, "area": " ".join(str(row.get("area") or "").split())[:80],
                                     "country": "Bangladesh"})
    if not (doc.keywords or doc.b2b_segments or doc.industries):
        frappe.throw(_("Add at least one keyword, segment or industry."))
    doc.save() if not doc.is_new() else doc.insert()
    return doc.name


@frappe.whitelist()
def launch(data) -> dict:
    """Create or update the campaign, plan its searches, then run now and/or schedule it."""
    from reckon_sales_agent.discovery.runner import build_plan
    from reckon_sales_agent.discovery.schedule import SCHEDULES, first_run
    from reckon_sales_agent.jobs import enqueue_discovery

    data = _payload(data)
    company = current_company()
    mode = data.get("mode") if data.get("mode") in ("now", "schedule", "both") else "now"
    schedule = data.get("schedule") if data.get("schedule") in SCHEDULES else None
    if mode in ("schedule", "both") and not schedule:
        frappe.throw(_("Choose how often to run."))
    connector = data.get("connector")
    profile = data.get("targeting_profile")
    get_tenant_doc("Sales Source Connector", connector, "read")
    get_tenant_doc("Sales Targeting Profile", profile, "read")

    if data.get("name"):
        campaign = get_tenant_doc("Sales Discovery Campaign", data["name"], "write")
    else:
        campaign = frappe.get_doc({"doctype": "Sales Discovery Campaign", "company": company})
    campaign.campaign_name = " ".join(str(data.get("campaign_name") or "").split())[:140] or _("Lead discovery")
    campaign.source_connector = connector
    campaign.targeting_profile = profile
    campaign.target_count = max(1, min(int(data.get("target_count") or 50), 5000))
    campaign.per_query_limit = max(1, min(int(data.get("per_query_limit") or 20), 60))
    campaign.auto_research = 1 if data.get("auto_research", True) else 0
    campaign.use_ai_planner = 1 if data.get("use_ai_planner") else 0
    campaign.schedule = schedule if mode in ("schedule", "both") else None
    campaign.run_at_time = (data.get("run_at_time") or None) if campaign.schedule else None
    if not campaign.qualification_profile:
        campaign.qualification_profile = frappe.db.get_value("Sales Qualification Profile", {"company": company})
    build_plan(campaign)
    campaign.save() if not campaign.is_new() else campaign.insert()
    updates = {"status": "Planned"}
    if campaign.schedule:
        updates["next_run_on"] = first_run(campaign.run_at_time, now_datetime())
    campaign.db_set(updates)

    job = None
    if mode in ("now", "both"):
        assert_entitled(company)
        job = enqueue_discovery(frappe.get_doc("Sales Discovery Campaign", campaign.name))
        if campaign.schedule:
            from reckon_sales_agent.jobs import next_run_date

            campaign.db_set("next_run_on", next_run_date(campaign.schedule))
    log_activity(company, "studio_launch", campaign, f"mode={mode} schedule={campaign.schedule or '-'}")
    campaign.reload()
    return {
        "campaign": campaign.name,
        "job": job,
        "next_run_on": str(campaign.next_run_on) if campaign.next_run_on else None,
        "run_at_time": str(campaign.run_at_time) if campaign.run_at_time else None,
        "planned": [{"query_text": r.query_text, "max_results": r.max_results} for r in campaign.planned_queries],
    }


@frappe.whitelist()
def progress(job: str) -> dict:
    doc = get_tenant_doc("Sales Discovery Job", job, "read")
    campaign = frappe.get_doc("Sales Discovery Campaign", doc.discovery_campaign) if doc.discovery_campaign else None
    prospects = frappe.get_list(
        "Sales Prospect",
        filters={"discovery_campaign": doc.discovery_campaign} if campaign else {"name": ""},
        fields=["name", "business_name", "city", "phone", "website", "fit_score", "deal_probability",
                "research_status", "review_status"],
        order_by="creation desc", page_length=8,
    )
    from reckon_sales_agent.jobs import worker_status

    return {
        "job": {k: doc.get(k) for k in ("name", "status", "progress_done", "progress_total", "created_count",
                                        "duplicate_count", "retry_count", "error_code", "error_detail",
                                        "started_at", "finished_at", "cancel_requested")},
        "searches": [{"query_text": r.query_text, "status": r.status, "results": r.results}
                     for r in (campaign.planned_queries if campaign else [])],
        "prospects": prospects,
        "researched": frappe.db.count("Sales Prospect", {"discovery_campaign": doc.discovery_campaign,
                                                          "research_status": "Done"}) if campaign else 0,
        "workers": worker_status() if doc.status == "Queued" else None,
    }

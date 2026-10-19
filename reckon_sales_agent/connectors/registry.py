"""Build a connector from a Sales Source Connector record, failing closed."""

from __future__ import annotations

import json

import frappe
from frappe import _

from reckon_sales_agent.connectors.base import ConnectorNotPermitted
from reckon_sales_agent.connectors.csv_import import CSVImportConnector
from reckon_sales_agent.connectors.fixture import FixtureConnector
from reckon_sales_agent.connectors.google_places import GooglePlacesConnector

MAPS_SOURCES = frozenset({"google_places_api", "serpapi_google_maps", "scrapingdog_google_maps",
                          "apify_google_maps", "google_maps_browser_experimental"})
# Sources whose terms we do not control: tenants may only tighten their policy.
RESTRICTED_SOURCES = MAPS_SOURCES
# Sources that need an explicit "policy reviewed" confirmation before running.
EXTERNAL_SOURCES = MAPS_SOURCES | {"permitted_directory"}


def _json(value) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except ValueError:
        frappe.throw(_("Connector JSON is not valid."))
    if not isinstance(parsed, dict):
        frappe.throw(_("Connector JSON must be an object."))
    return parsed


def build_connector(connector_doc):
    """The connector object for ``connector_doc``; raises ConnectorNotPermitted."""
    if not connector_doc.enabled:
        raise ConnectorNotPermitted(_("Connector {0} is disabled.").format(connector_doc.connector_name))
    kind = connector_doc.connector_type
    if kind in EXTERNAL_SOURCES and not connector_doc.policy_reviewed:
        raise ConnectorNotPermitted(_("Review the source policy before enabling {0}.").format(connector_doc.connector_name))
    config = _json(connector_doc.config_json)
    if kind == "fixture":
        return FixtureConnector(config)
    if kind == "manual_import":
        return CSVImportConnector(_attached_csv(connector_doc))
    if kind in MAPS_SOURCES:
        return _maps_connector(kind)
    if kind == "permitted_directory":
        from reckon_sales_agent.connectors.directory_crawler import DirectoryCrawler
        from reckon_sales_agent.usage import platform_settings

        settings = platform_settings()
        if not settings.research_enabled:
            raise ConnectorNotPermitted(_("Web crawling is disabled by the platform vendor."))
        return DirectoryCrawler(
            (connector_doc.start_urls or "").splitlines(),
            user_agent=settings.user_agent or "ReckonSalesAgent/1.0",
            allowed_path_prefix=connector_doc.allowed_path_prefix,
            max_pages=connector_doc.max_pages or 10,
            delay=connector_doc.crawl_delay_seconds or 2,
            timeout=settings.fetch_timeout or 10,
            max_bytes=(settings.max_page_kb or 1024) * 1024,
            ai_extractor=_ai_extractor(connector_doc) if connector_doc.get("ai_extraction") else None,
        )
    raise ConnectorNotPermitted(_("Connector type {0} is not available yet.").format(kind))


def _maps_connector(kind: str):
    from reckon_sales_agent.connectors.apify_maps import ApifyMapsConnector
    from reckon_sales_agent.connectors.maps_browser import GoogleMapsBrowserConnector
    from reckon_sales_agent.connectors.scrapingdog_maps import ScrapingdogMapsConnector
    from reckon_sales_agent.connectors.serpapi_maps import SerpAPIMapsConnector
    from reckon_sales_agent.usage import platform_settings

    s = platform_settings()
    ack = bool(s.maps_terms_ack)
    retention = s.maps_data_retention_days if s.maps_data_retention_days is not None else 30
    secret = lambda field: s.get_password(field, raise_exception=False)  # noqa: E731
    if kind == "serpapi_google_maps":
        return SerpAPIMapsConnector(secret("serpapi_api_key"), enabled=bool(s.serpapi_enabled), terms_ack=ack,
                                    retention_days=retention)
    if kind == "scrapingdog_google_maps":
        return ScrapingdogMapsConnector(secret("scrapingdog_api_key"), enabled=bool(s.scrapingdog_enabled),
                                        terms_ack=ack, retention_days=retention)
    if kind == "apify_google_maps":
        return ApifyMapsConnector(secret("apify_api_token"), enabled=bool(s.apify_enabled), terms_ack=ack,
                                  actor=s.apify_actor, retention_days=retention)
    if kind == "google_maps_browser_experimental":
        return GoogleMapsBrowserConnector(enabled=bool(s.maps_browser_enabled), terms_ack=ack,
                                          max_results=s.maps_browser_max_results or 40,
                                          delay=s.maps_browser_delay or 3, language=s.maps_browser_language or "en",
                                          retention_days=retention)
    return GooglePlacesConnector(
        secret("google_places_api_key"),
        enabled=bool(s.places_enabled),
        terms_reviewed=bool(s.places_terms_reviewed),
        retention_days=s.places_retention_days or 30,
    )


AI_LISTING_SCHEMA = {
    "type": "object",
    "properties": {"businesses": {"type": "array", "items": {
        "type": "object",
        "properties": {k: {"type": "string"} for k in
                       ("business_name", "website", "phone", "email", "address", "city", "industry")},
        "required": ["business_name", "website", "phone", "email", "address", "city", "industry"],
        "additionalProperties": False,
    }}},
    "required": ["businesses"],
    "additionalProperties": False,
}


def _ai_extractor(connector_doc):
    """Claude reads a listing page with no structured data and returns the businesses on it."""
    from reckon_sales_agent.constants import USAGE_AI
    from reckon_sales_agent.providers.factory import get_llm
    from reckon_sales_agent.providers.llm import UNTRUSTED_RULES, LLMError, untrusted
    from reckon_sales_agent.usage import remaining, reserve

    llm = get_llm(connector_doc.company)
    if not llm:
        return None

    def extract(page_text: str, url: str) -> list[dict]:
        if remaining(connector_doc.company, USAGE_AI) <= 0:
            return []
        reserve(connector_doc.company, USAGE_AI, 1, connector_doc)
        frappe.db.commit()
        try:
            data = llm.complete_json(
                "You extract business listings from a directory page. Return each business exactly as "
                "written on the page; use an empty string for anything not shown. Never invent websites, "
                f"phones or emails. {UNTRUSTED_RULES}",
                untrusted(url, page_text),
                AI_LISTING_SCHEMA,
                max_tokens=8000,
            )
        except LLMError:
            return []
        return data.get("businesses") or []

    return extract


def field_policy(connector_doc, connector) -> dict:
    """Default policy, with the tenant's overrides (tighten-only for restricted sources)."""
    policy = {field: dict(rule) for field, rule in connector.default_field_policy().items()}
    overrides = _json(connector_doc.field_policy)
    restricted = connector_doc.connector_type in RESTRICTED_SOURCES
    for field, rule in overrides.items():
        if not isinstance(rule, dict):
            continue
        base = policy.get(field)
        if restricted:
            if not base:
                continue  # cannot opt in a field the source does not allow
            base["persist"] = bool(base.get("persist")) and bool(rule.get("persist", True))
            days = [d for d in (base.get("retention_days"), rule.get("retention_days")) if d]
            base["retention_days"] = min(days) if days else None
            base["crm_sync"] = bool(base.get("crm_sync")) and bool(rule.get("crm_sync", True))
        else:
            policy[field] = {**(base or {}), **rule}
    return policy


def _attached_csv(connector_doc) -> str | None:
    file_name = frappe.db.get_value(
        "File",
        {"attached_to_doctype": connector_doc.doctype, "attached_to_name": connector_doc.name,
         "file_name": ["like", "%.csv"]},
        "name",
        order_by="creation desc",
    )
    if not file_name:
        return None
    content = frappe.get_doc("File", file_name).get_content()
    return content.decode("utf-8-sig") if isinstance(content, bytes) else content

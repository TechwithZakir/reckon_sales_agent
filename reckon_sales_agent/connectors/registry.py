"""Build a connector from a Sales Source Connector record, failing closed."""

from __future__ import annotations

import json

import frappe
from frappe import _

from reckon_sales_agent.connectors.base import ConnectorNotPermitted
from reckon_sales_agent.connectors.csv_import import CSVImportConnector
from reckon_sales_agent.connectors.fixture import FixtureConnector
from reckon_sales_agent.connectors.google_places import GooglePlacesConnector

# Sources whose terms we do not control: tenants may only tighten their policy.
RESTRICTED_SOURCES = frozenset({"google_places_api"})
# Sources that need an explicit "policy reviewed" confirmation before running.
EXTERNAL_SOURCES = frozenset({"google_places_api", "permitted_directory"})


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
    if kind == "google_places_api":
        from reckon_sales_agent.usage import platform_settings

        settings = platform_settings()
        return GooglePlacesConnector(
            settings.get_password("google_places_api_key", raise_exception=False),
            enabled=bool(settings.places_enabled),
            terms_reviewed=bool(settings.places_terms_reviewed),
            retention_days=settings.places_retention_days or 30,
        )
    if kind == "manual_import":
        return CSVImportConnector(_attached_csv(connector_doc))
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
        )
    raise ConnectorNotPermitted(_("Connector type {0} is not available yet.").format(kind))


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

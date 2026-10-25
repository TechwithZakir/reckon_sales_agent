"""Route lead-search work to the active providers, within each provider's monthly budget.

``places`` and ``page_context`` feed discovery (Smart Sources fans out to
all of them); ``web_search`` and ``page_context`` serve market research and
verification, trying the default provider first and falling back to the
next active one. Every HTTP request a provider makes is counted per billing
family and month, and refused once the vendor's budget is reached.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import now_datetime

from reckon_sales_agent.connectors.base import ConnectorError, ConnectorNotPermitted
from reckon_sales_agent.providers.routing import (
    BudgetExceeded,
    CountingSession,
    active_providers,
    family_of,
    over_budget,
)

USAGE_DOCTYPE = "Sales Provider Usage"


def active(capability: str) -> list[str]:
    from reckon_sales_agent.usage import platform_settings

    settings = platform_settings()
    return active_providers(capability, settings.get, settings.get(f"default_{capability}_provider") or None)


def monthly_cap(family: str) -> int:
    from reckon_sales_agent.usage import platform_settings

    for row in platform_settings().get("provider_budgets") or []:
        if row.provider == family:
            return int(row.monthly_request_cap or 0)
    return 0


def used_this_month(family: str, period: str | None = None) -> int:
    from reckon_sales_agent.usage import current_period

    return int(frappe.db.get_value(USAGE_DOCTYPE, f"{family}-{period or current_period()}", "requests") or 0)


def _count(family: str, period: str) -> None:
    name = f"{family}-{period}"
    if not frappe.db.exists(USAGE_DOCTYPE, name):
        try:
            frappe.get_doc({"doctype": USAGE_DOCTYPE, "usage_key": name, "provider": family, "period": period,
                            "requests": 1}).insert(ignore_permissions=True)
            return
        except frappe.DuplicateEntryError:
            pass  # another worker created it first
    frappe.db.sql(f"update `tab{USAGE_DOCTYPE}` set requests = requests + 1, modified = %s where name = %s",
                  (now_datetime(), name))


def budget_session(family: str) -> CountingSession:
    """An HTTP session that counts each request and refuses it once the month's budget is used."""
    from reckon_sales_agent.usage import current_period

    cap = monthly_cap(family)

    def before_request() -> None:
        period = current_period()
        if over_budget(used_this_month(family, period), cap):
            raise BudgetExceeded(family, cap)
        _count(family, period)

    return CountingSession(before_request)


def build_provider(connector_type: str):
    """The provider's connector from Platform Settings, with request counting."""
    from reckon_sales_agent.connectors.registry import provider_connector

    family = family_of(connector_type)
    return provider_connector(connector_type, session=budget_session(family) if family else None)


def _first_working(capability: str, call):
    """Run ``call(connector)`` on the default provider, then the next ones until one works."""
    last: ConnectorError | None = None
    for kind in active(capability):
        try:
            return call(build_provider(kind)), kind
        except ConnectorError as exc:
            last = exc
    if last:
        raise last
    raise ConnectorNotPermitted(_("No {0} provider is switched on in Sales Agent Platform Settings.").format(
        capability.replace("_", " ")))


def web_search(text: str, count: int = 10) -> tuple[list[dict], str]:
    """[{url, title, text}] from the first working web search provider, and which one answered."""
    return _first_working("web_search", lambda connector: connector.search(text, count))


def page_context(text: str, location: str = "", count: int = 10) -> tuple[list[dict], str]:
    """Search results with page text; plain web search results when no page-context provider is on."""
    if active("page_context"):
        try:
            return _first_working("page_context", lambda connector: connector.context(text, location, count))
        except ConnectorError:
            pass  # fall back to web search snippets
    return web_search(text, count)


def provider_status() -> list[dict]:
    """Per family: switched-on providers, budget and use this month (for settings and Studio)."""
    from reckon_sales_agent.providers.routing import FAMILIES, PROVIDERS

    out = []
    for family in FAMILIES:
        kinds = [kind for kind, spec in PROVIDERS.items() if spec[1] == family]
        on = [kind for kind in kinds if kind in set(active("places") + active("page_context") + active("web_search"))]
        out.append({"family": family, "active": on, "cap": monthly_cap(family), "used": used_this_month(family)})
    return out

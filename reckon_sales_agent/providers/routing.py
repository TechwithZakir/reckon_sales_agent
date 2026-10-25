"""Lead search providers grouped by what they can do (pure: no Frappe imports).

The agent asks for a *capability*, not a vendor:

* ``places``       local businesses (lead discovery)
* ``page_context`` search results with page text (discovery and contact extraction)
* ``web_search``   plain search results (market research and verification)

Brave is the default for each capability. Any other provider the platform
vendor has switched on joins in: discovery fans out to every active
provider, while research and verification use the default and fall back to
the next active provider when one fails or runs out of budget. Experimental
browser bots are never chosen automatically.
"""

from __future__ import annotations

from collections.abc import Callable

import requests

from reckon_sales_agent.connectors.base import ConnectorError

CAPABILITIES = ("places", "page_context", "web_search")

# connector_type -> (capability, billing family, Platform Settings flags that must all be on)
PROVIDERS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "brave_place_search": ("places", "brave", ("brave_enabled",)),
    "google_places_api": ("places", "google_places", ("places_enabled", "places_terms_reviewed")),
    "scrapingdog_google_maps": ("places", "scrapingdog", ("scrapingdog_enabled", "maps_terms_ack")),
    "scrapingbee_google_maps": ("places", "scrapingbee", ("scrapingbee_enabled", "maps_terms_ack")),
    "serpapi_google_maps": ("places", "serpapi", ("serpapi_enabled", "maps_terms_ack")),
    "apify_google_maps": ("places", "apify", ("apify_enabled", "maps_terms_ack")),
    "brave_llm_context": ("page_context", "brave", ("brave_enabled",)),
    "brave_web_search": ("web_search", "brave", ("brave_enabled",)),
    "scrapingdog_google_search": ("web_search", "scrapingdog", ("search_scrapingdog_enabled", "search_terms_ack")),
    "scrapingbee_google_search": ("web_search", "scrapingbee", ("search_scrapingbee_enabled", "search_terms_ack")),
    "serpapi_google_search": ("web_search", "serpapi", ("search_serpapi_enabled", "search_terms_ack")),
}
DEFAULTS = {"places": "brave_place_search", "page_context": "brave_llm_context", "web_search": "brave_web_search"}
FAMILIES = ("brave", "google_places", "scrapingdog", "scrapingbee", "serpapi", "apify")


def family_of(connector_type: str) -> str | None:
    spec = PROVIDERS.get(connector_type)
    return spec[1] if spec else None


def active_providers(capability: str, flags: Callable[[str], object], default: str | None = None) -> list[str]:
    """Connector types for ``capability`` whose vendor flags are all on; the default comes first."""
    active = [kind for kind, (cap, _family, needed) in PROVIDERS.items()
              if cap == capability and all(flags(flag) for flag in needed)]
    first = default or DEFAULTS.get(capability)
    return sorted(active, key=lambda kind: (kind != first, list(PROVIDERS).index(kind)))


def over_budget(used: int, cap: int | None) -> bool:
    """A cap of 0 or empty means no limit."""
    return bool(cap) and used >= int(cap)


class BudgetExceeded(ConnectorError):
    """Raised before a request when the provider's monthly request budget is used up."""

    def __init__(self, family: str, cap: int):
        super().__init__(f"The monthly request budget for {family} ({cap} requests) is used up. "
                         "Raise it in Sales Agent Platform Settings or wait for next month.",
                         permanent=True, code="provider_budget")
        self.family = family


class CountingSession(requests.Session):
    """A requests session that calls ``before_request`` ahead of every HTTP request.

    The hook counts the request against the provider's monthly budget and
    raises ``BudgetExceeded`` when the budget is spent, so no paid request
    goes out over budget.
    """

    def __init__(self, before_request: Callable[[], None]):
        super().__init__()
        self.before_request = before_request

    def request(self, method, url, *args, **kwargs):
        self.before_request()
        return super().request(method, url, *args, **kwargs)

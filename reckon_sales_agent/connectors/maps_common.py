"""Shared rules for every Google Maps-derived source (pure: no Frappe imports).

Whichever way Maps data arrives (Places API, SerpAPI, Apify, browser), the
same field policy applies: fields are kept for the vendor's retention window
unless the company's own website confirms them, are attributed to Google
Maps, and are not copied into the CRM until confirmed. A retention of 0
means the vendor decided, after legal review, to keep them.
"""

from __future__ import annotations

import re

from reckon_sales_agent.connectors.base import ConnectorNotPermitted
from reckon_sales_agent.discovery.normalize import PROSPECT_FIELDS

ATTRIBUTION = "Google Maps"
BLOCK_MARKERS = ("/sorry/", "unusual traffic", "our systems have detected", "recaptcha", "consent.google.")


def maps_field_policy(retention_days: int | None) -> dict:
    days = int(retention_days or 0) or None
    return {
        field: {"persist": True, "retention_days": days, "crm_sync": days is None, "attribution": ATTRIBUTION}
        for field in PROSPECT_FIELDS
    }


def require_maps_terms(terms_ack: bool, enabled: bool, credential: str | None, name: str,
                       needs_credential: bool = True) -> None:
    if not enabled:
        raise ConnectorNotPermitted(f"{name} is disabled by the platform vendor.")
    if not terms_ack:
        raise ConnectorNotPermitted("The vendor has not accepted responsibility for Google Maps data use.")
    if needs_credential and not credential:
        raise ConnectorNotPermitted(f"No {name} credential is configured.")


def city_from_address(address: str | None, fallback: str = "") -> str:
    """'House 5, Road 2, Gulshan, Dhaka 1212, Bangladesh' -> 'Dhaka'."""
    parts = [p.strip() for p in (address or "").split(",") if p.strip()]
    if parts and parts[-1].lower() in {"bangladesh", "bd"}:
        parts = parts[:-1]
    if parts:
        return re.sub(r"\s*\d{3,}.*$", "", parts[-1]).strip() or fallback
    return fallback


def provider_message(response, secret: str | None = None, limit: int = 200) -> str:
    """The provider's own error text (JSON message/error or body), with the secret redacted."""
    text = ""
    try:
        data = response.json()
        if isinstance(data, dict):
            text = str(data.get("message") or data.get("error") or data.get("detail") or data)
        else:
            text = str(data)
    except Exception:
        text = getattr(response, "text", "") or ""
    text = " ".join(text.split())
    if secret:
        text = text.replace(secret, "***")
    return text[:limit]


def http_error(provider: str, response, secret: str | None = None):
    """A ConnectorError explaining an HTTP failure, using the provider's documented meanings."""
    from reckon_sales_agent.connectors.base import ConnectorError

    status = response.status_code
    meaning = {
        401: "the API key is invalid or missing",
        402: "the account has no credit left",
        403: "the plan does not include this API, or credits are used up",
        429: "the rate limit was reached",
    }.get(status, "the request failed")
    detail = provider_message(response, secret)
    return ConnectorError(
        f"{provider} HTTP {status}: {meaning}." + (f" Provider says: {detail}" if detail else ""),
        permanent=status in (400, 401, 402, 403, 404),
        code={401: "auth", 402: "billing", 403: "forbidden", 429: "rate_limited"}.get(status, "http_error"),
    )


def looks_blocked(url: str, text: str = "") -> bool:
    haystack = f"{url} {text[:5000]}".lower()
    return any(marker in haystack for marker in BLOCK_MARKERS)

"""Source connector contract (pure: no Frappe imports).

A connector turns a :class:`DiscoveryQuery` into :class:`SourceRecord` objects.
It declares what it can do and, per field, what the source lets us keep. The
discovery runner applies that policy before anything is stored, so a connector
never decides on its own what ends up in the CRM.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol


class ConnectorError(Exception):
    """A temporary or permanent source failure; ``permanent`` stops retries."""

    def __init__(self, message: str, *, permanent: bool = False, code: str = "source_error"):
        super().__init__(message)
        self.permanent = permanent
        self.code = code


class ConnectorNotPermitted(ConnectorError):
    def __init__(self, message: str):
        super().__init__(message, permanent=True, code="not_permitted")


@dataclass(frozen=True)
class DiscoveryQuery:
    keyword: str
    location: str
    query_text: str
    max_results: int = 20
    filters: dict[str, Any] = field(default_factory=dict)


@dataclass
class SourceRecord:
    source_key: str
    external_id: str | None
    source_url: str | None
    fields: dict[str, Any]
    retrieved_at: str
    warnings: list[str] = field(default_factory=list)


class BusinessSourceConnector(Protocol):
    source_key: str

    def capabilities(self) -> dict[str, Any]: ...

    def default_field_policy(self) -> dict[str, dict[str, Any]]: ...

    def validate_configuration(self) -> None: ...

    def discover(self, query: DiscoveryQuery) -> Iterable[SourceRecord]: ...


def keep_all_policy(attribution: str | None = None) -> dict[str, dict[str, Any]]:
    """Policy for sources the tenant owns or licenses outright."""
    from reckon_sales_agent.discovery.normalize import PROSPECT_FIELDS

    return {
        name: {"persist": True, "retention_days": None, "crm_sync": True, "attribution": attribution}
        for name in PROSPECT_FIELDS
    }

"""Tenant-owned list import: a CSV file the tenant attached to the connector.

The tenant asserts it may use this list; every row is kept with "Tenant
import" provenance. Columns: business_name, website, email, phone, industry,
address, city, country (extra columns are ignored).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from datetime import datetime, timezone

from reckon_sales_agent.connectors.base import (
    ConnectorNotPermitted,
    DiscoveryQuery,
    SourceRecord,
    keep_all_policy,
)
from reckon_sales_agent.discovery.normalize import PROSPECT_FIELDS, normalize_space

MAX_ROWS = 5000


class CSVImportConnector:
    source_key = "manual_import"

    def __init__(self, content: str | None):
        self.content = content

    def capabilities(self) -> dict:
        return {"live": False, "network": False, "max_rows": MAX_ROWS}

    def default_field_policy(self) -> dict:
        return keep_all_policy(attribution="Tenant import")

    def validate_configuration(self) -> None:
        if not self.content:
            raise ConnectorNotPermitted("Attach a CSV file to this connector first.")

    def discover(self, query: DiscoveryQuery) -> Iterable[SourceRecord]:
        """Rows matching the keyword and location (blank filters match all)."""
        self.validate_configuration()
        now = datetime.now(timezone.utc).isoformat()
        keyword, location = query.keyword.lower(), query.location.lower()
        returned = 0
        for index, row in enumerate(csv.DictReader(io.StringIO(self.content))):
            if index >= MAX_ROWS or returned >= query.max_results:
                return
            fields = {k: normalize_space(row.get(k)) for k in PROSPECT_FIELDS}
            if not fields["business_name"]:
                continue
            haystack = " ".join(fields.values()).lower()
            if keyword and keyword not in haystack:
                continue
            if location and location not in haystack:
                continue
            returned += 1
            yield SourceRecord(
                source_key=self.source_key,
                external_id=f"row-{index + 2}",
                source_url=None,
                fields=fields,
                retrieved_at=now,
            )

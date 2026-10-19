"""Offline demo/test source: deterministic fictional businesses, no network.

Every record is clearly fictional: ``.example`` domains (reserved by RFC 2606)
and phone numbers in the unallocated Bangladesh ``010`` range, so demo data
can never reach a real company or person.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import datetime, timezone

from reckon_sales_agent.connectors.base import DiscoveryQuery, SourceRecord, keep_all_policy

PREFIXES = ("Nova", "Padma", "Meghna", "Sonar", "Green", "Delta", "Bengal", "Prime", "Rupali", "Jamuna",
            "Star", "Royal", "Shapla", "Karnaphuli", "Unity", "Apex")
SUFFIXES = ("Traders", "Enterprise", "Distribution", "Pharma", "Foods", "Textiles", "Agro",
            "Electronics", "Solutions", "Industries")


class FixtureConnector:
    source_key = "fixture"

    def __init__(self, config: dict | None = None):
        self.config = config or {}

    def capabilities(self) -> dict:
        return {"live": False, "network": False, "fields": list(keep_all_policy())}

    def default_field_policy(self) -> dict:
        return keep_all_policy(attribution="Demo data")

    def validate_configuration(self) -> None:
        return None

    def discover(self, query: DiscoveryQuery) -> Iterable[SourceRecord]:
        now = datetime.now(timezone.utc).isoformat()
        count = min(int(self.config.get("results_per_query", query.max_results)), query.max_results)
        for index in range(count):
            seed = hashlib.sha256(f"{query.query_text}|{index}".encode()).hexdigest()
            n = int(seed[:8], 16)
            name = f"{PREFIXES[n % len(PREFIXES)]} {query.keyword.title()} {SUFFIXES[(n // 7) % len(SUFFIXES)]}"
            slug = "-".join(name.lower().split())
            # Every fifth record repeats an earlier one to exercise deduplication.
            if index and index % 5 == 0:
                seed = hashlib.sha256(f"{query.query_text}|{index - 1}".encode()).hexdigest()
                n = int(seed[:8], 16)
                name = f"{PREFIXES[n % len(PREFIXES)]} {query.keyword.title()} {SUFFIXES[(n // 7) % len(SUFFIXES)]}"
                slug = "-".join(name.lower().split())
            yield SourceRecord(
                source_key=self.source_key,
                external_id=f"fixture-{seed[:12]}",
                source_url=None,
                fields={
                    "business_name": name,
                    "industry": query.keyword.title(),
                    "website": f"https://{slug}.example",
                    "email": f"info@{slug}.example",
                    "phone": f"+880100{n % 10_000_000:07d}",
                    "city": query.location or "Dhaka",
                    "country": "Bangladesh",
                    "address": f"{n % 200 + 1} Demo Road, {query.location or 'Dhaka'}",
                },
                retrieved_at=now,
                warnings=["Fictional demo record"],
            )

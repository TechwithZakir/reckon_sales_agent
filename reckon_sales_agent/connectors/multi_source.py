"""Smart Sources: one discovery search across every active lead provider (pure: no Frappe imports).

Each provider (Brave Places, Brave LLM Context, Google Places, ...) runs the
same "keyword in location" search. Results are interleaved so every source
contributes, the same business found twice is kept once, and the run stops
at the requested number of leads. One failing provider does not stop the
others; the search fails only when every provider fails.
"""

from __future__ import annotations

from collections.abc import Iterable

from reckon_sales_agent.connectors.base import ConnectorError, DiscoveryQuery, SourceRecord
from reckon_sales_agent.discovery.normalize import normalize_domain, normalize_name, normalize_phone


def _keys(record: SourceRecord) -> set[str]:
    fields = record.fields
    keys = set()
    if normalize_domain(fields.get("website")):
        keys.add("d:" + normalize_domain(fields.get("website")))
    if normalize_phone(fields.get("phone")):
        keys.add("p:" + normalize_phone(fields.get("phone")))
    if normalize_name(fields.get("business_name")):
        keys.add("n:" + normalize_name(fields.get("business_name")) + "|" + str(fields.get("city") or "").lower())
    return keys


def strictest_policy(policies: list[dict]) -> dict:
    """Merge field policies so every rule of every source holds (shortest retention, no CRM sync if any forbids)."""
    merged: dict[str, dict] = {}
    for policy in policies:
        for field, rule in policy.items():
            if field not in merged:
                merged[field] = dict(rule)
                continue
            base = merged[field]
            base["persist"] = bool(base.get("persist")) and bool(rule.get("persist"))
            days = [d for d in (base.get("retention_days"), rule.get("retention_days")) if d]
            base["retention_days"] = min(days) if days else None
            base["crm_sync"] = bool(base.get("crm_sync")) and bool(rule.get("crm_sync"))
            if rule.get("attribution") and rule.get("attribution") != base.get("attribution"):
                base["attribution"] = ", ".join(filter(None, (base.get("attribution"), rule["attribution"])))
    return merged


class MultiSourceConnector:
    source_key = "multi_source"

    def __init__(self, sources: list[tuple[str, object]]):
        self.sources = sources  # [(connector_type, connector)]
        self.warnings: list[str] = []

    def capabilities(self) -> dict:
        return {"live": True, "network": True, "sources": [kind for kind, _ in self.sources]}

    def default_field_policy(self) -> dict:
        return strictest_policy([connector.default_field_policy() for _kind, connector in self.sources])

    def validate_configuration(self) -> None:
        if not self.sources:
            from reckon_sales_agent.connectors.base import ConnectorNotPermitted

            raise ConnectorNotPermitted("No lead source is switched on. Ask your provider to enable Brave Search "
                                        "or another lead source.")
        errors = []
        for kind, connector in self.sources:
            try:
                connector.validate_configuration()
            except ConnectorError as exc:
                errors.append(f"{kind}: {exc}")
        if len(errors) == len(self.sources):
            raise ConnectorError("; ".join(errors), permanent=True, code="not_permitted")

    def discover(self, query: DiscoveryQuery) -> Iterable[SourceRecord]:
        results: list[list[SourceRecord]] = []
        failures: list[ConnectorError] = []
        for kind, connector in self.sources:
            try:
                results.append(list(connector.discover(query)))
            except ConnectorError as exc:
                failures.append(exc)
                self.warnings.append(f"{kind}: {exc}")
        if failures and len(failures) == len(self.sources):
            last = failures[-1]
            raise ConnectorError(f"Every lead source failed. Last: {last}", permanent=last.permanent, code=last.code)
        kept: list[SourceRecord] = []
        owner: dict[str, SourceRecord] = {}  # dedup key -> the record that kept it
        for index in range(max((len(r) for r in results), default=0)):
            for records in results:  # round-robin, so every source contributes
                if index >= len(records):
                    continue
                record = records[index]
                keys = _keys(record)
                match = next((owner[k] for k in keys if k in owner), None)
                if match:
                    # The same business from another source: evidence it is real, not a new lead.
                    if record.source_key != match.source_key and record.source_key not in match.corroborated_by:
                        match.corroborated_by.append(record.source_key)
                    for key in keys:
                        owner.setdefault(key, match)
                    continue
                for key in keys:
                    owner[key] = record
                kept.append(record)
        yield from kept[:query.max_results]

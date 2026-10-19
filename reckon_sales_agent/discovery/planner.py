"""Bounded search planning (pure: no Frappe imports)."""

from __future__ import annotations

from dataclasses import dataclass

MAX_QUERIES = 50
MAX_PER_QUERY = 60


@dataclass(frozen=True)
class PlannedQuery:
    keyword: str
    location: str
    query_text: str
    max_results: int


def split_lines(value: str | None) -> list[str]:
    seen: list[str] = []
    for line in (value or "").replace(",\n", "\n").splitlines():
        item = " ".join(line.split()).strip()
        if item and item.lower() not in {s.lower() for s in seen}:
            seen.append(item)
    return seen


def plan_queries(
    industries: str | None,
    keywords: str | None,
    locations: str | None,
    target_count: int,
    per_query_limit: int,
    max_results_per_job: int,
) -> list[PlannedQuery]:
    """Cross keywords (or industries) with locations, capped in count and volume.

    Never expands without bound: at most ``MAX_QUERIES`` searches, each limited
    to ``per_query_limit`` results, and the total stays within both the target
    and the Company's per-job maximum.
    """
    terms = split_lines(keywords) or split_lines(industries)
    places = split_lines(locations) or [""]
    if not terms:
        return []
    budget = max(0, min(int(target_count or 0), int(max_results_per_job or 0)))
    per_query = max(1, min(int(per_query_limit or 1), MAX_PER_QUERY))
    plan: list[PlannedQuery] = []
    for location in places:
        for term in terms:
            if len(plan) >= MAX_QUERIES or budget <= 0:
                return plan
            size = min(per_query, budget)
            text = f"{term} in {location}" if location else term
            plan.append(PlannedQuery(term, location, text, size))
            budget -= size
    return plan

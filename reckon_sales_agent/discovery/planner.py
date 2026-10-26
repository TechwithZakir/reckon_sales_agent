"""Bounded search planning (pure: no Frappe imports)."""

from __future__ import annotations

from dataclasses import dataclass

MAX_QUERIES = 50
MAX_PER_QUERY = 60
MIN_PER_QUERY = 5  # smaller searches across more keyword x location pairs find more distinct businesses


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


def pairs(terms: list[str], places: list[str]) -> list[tuple[str, str]]:
    """Every keyword x location pair, ordered so consecutive searches differ in both."""
    places = places or [""]
    return [(term, places[(i + shift) % len(places)]) for shift in range(len(places)) for i, term in enumerate(terms)]


def spread_plan(terms: list[str], places: list[str], target_count: int, per_query_limit: int,
                max_results_per_job: int, start: int = 0) -> tuple[list[PlannedQuery], int]:
    """Spread one run's leads over many keyword x location pairs; returns the plan and the next start.

    The run asks for at least ``MIN_PER_QUERY`` results per search, so a 20-lead
    run covers four pairs rather than one. Scheduled runs continue from
    ``start``, so over time every pair gets searched. Bounded: at most
    ``MAX_QUERIES`` searches, each within ``per_query_limit``, and the total
    within both the target and the Company's per-job maximum.
    """
    combos = pairs(terms, places)
    if not combos:
        return [], 0
    budget = max(0, min(int(target_count or 0), int(max_results_per_job or 0)))
    cap = max(1, min(int(per_query_limit or 1), MAX_PER_QUERY))
    if budget <= 0:
        return [], start % len(combos)
    size = min(cap, max(MIN_PER_QUERY, -(-budget // len(combos))))
    count = min(len(combos), MAX_QUERIES, -(-budget // size))
    plan: list[PlannedQuery] = []
    for k in range(count):
        if budget <= 0:
            break
        term, place = combos[(start + k) % len(combos)]
        n = min(size, budget)
        plan.append(PlannedQuery(term, place, f"{term} in {place}" if place else term, n))
        budget -= n
    return plan, (start + len(plan)) % len(combos)


def plan_queries(
    industries: str | None,
    keywords: str | None,
    locations: str | None,
    target_count: int,
    per_query_limit: int,
    max_results_per_job: int,
    start: int = 0,
) -> list[PlannedQuery]:
    """Cross keywords (or industries) with locations, capped in count and volume (see ``spread_plan``)."""
    terms = split_lines(keywords) or split_lines(industries)
    if not terms:
        return []
    return spread_plan(terms, split_lines(locations), target_count, per_query_limit, max_results_per_job, start)[0]

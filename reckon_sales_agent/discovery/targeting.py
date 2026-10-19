"""Master targeting setup -> search plan, with optional AI expansion.

A Sales Targeting Profile holds who to find (industries, B2B segments,
keywords, interests, exclusions, company size) and where (locations). The
planner turns it into the same bounded plan as a hand-written campaign.
Claude may propose extra keywords and segments, but only as suggestions the
user applies; nothing it proposes is searched without being saved first.
"""

from __future__ import annotations

from reckon_sales_agent.discovery.planner import MAX_QUERIES, PlannedQuery, split_lines

AI_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "keywords": {"type": "array", "items": {"type": "string"}},
        "bangla_keywords": {"type": "array", "items": {"type": "string"}},
        "b2b_segments": {"type": "array", "items": {"type": "string"}},
        "industries": {"type": "array", "items": {"type": "string"}},
        "exclude_keywords": {"type": "array", "items": {"type": "string"}},
        "reasoning": {"type": "string"},
    },
    "required": ["keywords", "bangla_keywords", "b2b_segments", "industries", "exclude_keywords", "reasoning"],
    "additionalProperties": False,
}
MAX_SUGGESTIONS = 15


def location_labels(rows) -> list[str]:
    labels = []
    for row in rows or []:
        parts = [row.get("area"), row.get("city")]
        label = ", ".join(p.strip() for p in parts if p and p.strip())
        if label and label.lower() not in {x.lower() for x in labels}:
            labels.append(label)
    return labels


def search_terms(profile: dict) -> list[str]:
    """Keywords first, then B2B segments qualified by industry, de-duplicated."""
    terms = split_lines(profile.get("keywords"))
    industries = split_lines(profile.get("industries"))
    for segment in split_lines(profile.get("b2b_segments")):
        if industries:
            terms.extend(f"{industry} {segment}" for industry in industries)
        else:
            terms.append(segment)
    if not terms:
        terms = industries
    seen, unique = set(), []
    for term in terms:
        if term.lower() not in seen:
            seen.add(term.lower())
            unique.append(term)
    return unique


def plan_from_profile(profile: dict, target_count: int, per_query_limit: int, max_results_per_job: int) -> list[PlannedQuery]:
    terms = search_terms(profile)
    places = location_labels(profile.get("locations")) or [""]
    budget = max(0, min(int(target_count or 0), int(max_results_per_job or 0)))
    per_query = max(1, min(int(per_query_limit or 1), 60))
    plan: list[PlannedQuery] = []
    for place in places:
        for term in terms:
            if len(plan) >= MAX_QUERIES or budget <= 0:
                return plan
            size = min(per_query, budget)
            plan.append(PlannedQuery(term, place, f"{term} in {place}" if place else term, size))
            budget -= size
    return plan


def excluded(text: str, profile: dict) -> bool:
    lowered = (text or "").lower()
    return any(word.lower() in lowered for word in split_lines(profile.get("exclude_keywords")))


def clean_suggestions(data: dict) -> dict:
    """Bound and tidy what the model proposed before it is shown or saved."""
    def tidy(values):
        out = []
        for value in values or []:
            item = " ".join(str(value).split())[:80]
            if item and item.lower() not in {o.lower() for o in out}:
                out.append(item)
        return out[:MAX_SUGGESTIONS]

    return {
        "keywords": tidy(data.get("keywords")),
        "bangla_keywords": tidy(data.get("bangla_keywords")),
        "b2b_segments": tidy(data.get("b2b_segments")),
        "industries": tidy(data.get("industries")),
        "exclude_keywords": tidy(data.get("exclude_keywords")),
        "reasoning": " ".join(str(data.get("reasoning") or "").split())[:1000],
    }


def merge_lines(existing: str | None, additions: list[str]) -> str:
    lines = split_lines(existing)
    for item in additions:
        if item.lower() not in {line.lower() for line in lines}:
            lines.append(item)
    return "\n".join(lines)

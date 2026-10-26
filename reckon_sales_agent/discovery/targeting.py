"""Master targeting setup -> search plan, with optional AI expansion.

A Sales Targeting Profile holds who to find (industries, B2B segments,
keywords, interests, exclusions, company size) and where (locations). The
planner turns it into the same bounded plan as a hand-written campaign.
Claude may propose extra keywords and segments, but only as suggestions the
user applies; nothing it proposes is searched without being saved first.
"""

from __future__ import annotations

import re

from reckon_sales_agent.discovery.planner import PlannedQuery, split_lines, spread_plan

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


def plan_from_profile(profile: dict, target_count: int, per_query_limit: int, max_results_per_job: int,
                      start: int = 0) -> list[PlannedQuery]:
    return plan_with_cursor(profile, target_count, per_query_limit, max_results_per_job, start)[0]


def plan_with_cursor(profile: dict, target_count: int, per_query_limit: int, max_results_per_job: int,
                     start: int = 0) -> tuple[list[PlannedQuery], int]:
    """This run's searches over the profile's keyword x location pairs, and where the next run starts."""
    return spread_plan(search_terms(profile), location_labels(profile.get("locations")), target_count,
                       per_query_limit, max_results_per_job, start)


def excluded(text: str, profile: dict) -> bool:
    lowered = (text or "").lower()
    return any(word.lower() in lowered for word in split_lines(profile.get("exclude_keywords")))


# Two-letter endings used worldwide as generic domains, not as a country signal.
GENERIC_CCTLDS = {"io", "co", "ai", "me", "tv", "cc", "ly", "fm", "gg", "to", "sh", "ws", "la", "so", "vc"}
OTHER_COUNTRIES = ("india", "pakistan", "nepal", "sri lanka", "bhutan", "myanmar", "china", "usa", "united states",
                   "united kingdom", "england", "uae", "dubai", "saudi arabia", "qatar", "malaysia", "singapore",
                   "indonesia", "thailand", "vietnam", "australia", "canada", "germany", "kolkata", "mumbai",
                   "delhi", "bengaluru", "bangalore", "chennai", "hyderabad", "karachi", "lahore")


def market_country(profile: dict | None) -> str:
    """The country a targeting profile searches in (Bangladesh unless its locations say otherwise)."""
    countries = {str(row.get("country") or "").strip().lower() for row in (profile or {}).get("locations") or []}
    countries.discard("")
    return countries.pop() if len(countries) == 1 else "bangladesh"


def foreign_business(fields: dict, country: str = "bangladesh") -> str | None:
    """Why a found business is outside the target country, or None. Only judged for Bangladesh campaigns."""
    if country not in ("bangladesh", "bd"):
        return None
    stated = str(fields.get("country") or "").strip().lower()
    if stated and stated not in ("bangladesh", "bd", "বাংলাদেশ"):
        return f"listed in {fields.get('country')}"
    host = re.sub(r"^https?://", "", str(fields.get("website") or "").lower()).split("/")[0].split(":")[0]
    tld = host.rsplit(".", 1)[-1] if "." in host else ""
    if len(tld) == 2 and tld != "bd" and tld not in GENERIC_CCTLDS:
        return f"website on .{tld}"
    address = str(fields.get("address") or "").lower()
    if address and "bangladesh" not in address and "dhaka" not in address:
        for name in OTHER_COUNTRIES:
            if re.search(rf"\b{re.escape(name)}\b", address):
                return f"address in {name.title()}"
    return None


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

"""Market research planning (pure: no Frappe imports).

From the seller's Business Profile the agent decides what to read on the
web, Claude turns that evidence into customer segments with search keywords,
and each approved segment becomes a Targeting Profile. AI output is checked
here: a segment may only cite pages the agent actually read, and lists are
trimmed to sizes a search plan can use.
"""

from __future__ import annotations

from reckon_sales_agent.discovery.planner import split_lines
from reckon_sales_agent.providers.llm import UNTRUSTED_RULES

COUNTRY = "Bangladesh"
MAX_SEGMENTS = 8
LIST_LIMITS = {"industries": 6, "business_types": 8, "keywords": 12, "bangla_keywords": 8, "locations": 10,
               "buying_signals": 8, "negative_keywords": 10, "evidence_urls": 6}
SEGMENT_FIELDS = tuple(LIST_LIMITS)

MARKET_SYSTEM = (
    "You are a B2B market researcher helping a company that sells in Bangladesh find new customers. "
    "From the seller's profile and the web pages provided, identify the customer segments most likely to buy. "
    "For each segment give: a short name; priority 1 (best) to 5; why it fits, grounded in the pages; "
    "industries; business types; search keywords that a maps or places search would match for the CUSTOMER "
    "businesses themselves (2-4 words, e.g. 'pharmacy', 'medicine wholesaler', not the seller's product names); "
    "Bangla equivalents that Bangladeshi businesses use on signboards and listings; locations (area and city); "
    "buying signals a salesperson could spot (new branch, hiring, tender); and keywords that rule a business out. "
    "Cite evidence_urls only from the URLs of the pages provided. Do not invent companies, numbers or facts; "
    "when the evidence is thin, say so in unknowns. " + UNTRUSTED_RULES
)

_string_list = {"type": "array", "items": {"type": "string"}}
MARKET_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "segments": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "segment_name": {"type": "string"},
                "priority": {"type": "integer"},
                "fit_reason": {"type": "string"},
                **{field: _string_list for field in SEGMENT_FIELDS},
            },
            "required": ["segment_name", "priority", "fit_reason", *SEGMENT_FIELDS],
            "additionalProperties": False,
        }},
        "unknowns": _string_list,
    },
    "required": ["summary", "segments", "unknowns"],
    "additionalProperties": False,
}


def lines(profile: dict, field: str) -> list[str]:
    return split_lines(profile.get(field))


def research_queries(profile: dict, max_queries: int = 8) -> list[str]:
    """What to read about the market, most useful first; duplicates removed."""
    industries = lines(profile, "target_industries")
    types = lines(profile, "business_types")
    products = lines(profile, "products")
    regions = lines(profile, "regions") or [COUNTRY]
    region = regions[0]
    customers = [row.split("|")[0].strip() for row in lines(profile, "best_customers")]
    queries: list[str] = []
    for industry in industries[:3]:
        queries.append(f"{industry} companies in {region}")
    for kind in types[:2]:
        queries.append(f"{kind} {industries[0] if industries else ''} {region}".replace("  ", " "))
    for product in products[:2]:
        queries.append(f"businesses that buy {product} in {COUNTRY}")
    for name in customers[:2]:
        queries.append(f"companies like {name} {COUNTRY}")
    if industries:
        queries.append(f"{industries[0]} association members {COUNTRY}")
        queries.append(f"{industries[0]} market {COUNTRY} growth trends")
    for competitor in lines(profile, "competitors")[:1]:
        queries.append(f"{competitor} customers {COUNTRY}")
    if not queries and profile.get("what_we_sell"):
        queries.append(f"who buys {profile['what_we_sell'][:80]} in {COUNTRY}")
    unique: list[str] = []
    for query in (" ".join(q.split()) for q in queries):
        if query and query.lower() not in {u.lower() for u in unique}:
            unique.append(query)
    return unique[:max_queries]


def profile_prompt(profile: dict) -> str:
    labels = (("Business", "business_name"), ("What we sell", "what_we_sell"), ("Products", "products"),
              ("Problems we solve", "problems_solved"), ("Target industries", "target_industries"),
              ("Business types", "business_types"), ("Buyer roles", "buyer_roles"), ("Regions", "regions"),
              ("Size signals", "size_signals"), ("Competitors", "competitors"), ("Exclusions", "exclusions"),
              ("Best customers", "best_customers"), ("Languages", "languages"))
    return "\n".join(f"{label}: {', '.join(split_lines(profile.get(field))) or '-'}" for label, field in labels)


def _items(value, limit: int) -> list[str]:
    out: list[str] = []
    for item in value if isinstance(value, list) else []:
        text = " ".join(str(item).split())[:80]
        if text and text.lower() not in {o.lower() for o in out}:
            out.append(text)
    return out[:limit]


def clean_brief(data: dict, read_urls: set[str], max_segments: int = MAX_SEGMENTS) -> dict:
    """Validated brief: trimmed lists, priorities 1-5, evidence limited to pages actually read."""
    segments = []
    for raw in (data.get("segments") or [])[: max_segments * 2]:
        if not isinstance(raw, dict):
            continue
        name = " ".join(str(raw.get("segment_name") or "").split())[:120]
        segment = {field: _items(raw.get(field), limit) for field, limit in LIST_LIMITS.items()}
        segment["evidence_urls"] = [url for url in segment["evidence_urls"] if url in read_urls]
        if not name or not (segment["keywords"] or segment["bangla_keywords"]):
            continue
        try:
            priority = int(raw.get("priority") or 3)
        except (TypeError, ValueError):
            priority = 3
        segment.update(segment_name=name, priority=max(1, min(priority, 5)),
                       fit_reason=" ".join(str(raw.get("fit_reason") or "").split())[:600])
        segments.append(segment)
    segments.sort(key=lambda s: s["priority"])
    return {
        "summary": " ".join(str(data.get("summary") or "").split())[:3000],
        "segments": segments[:max_segments],
        "unknowns": _items(data.get("unknowns"), 10),
    }


def rule_brief(profile: dict) -> dict:
    """A plan without AI: one segment per target industry (or one core segment) from the profile itself."""
    types = lines(profile, "business_types")
    industries = lines(profile, "target_industries") or ["Core market"]
    negatives = lines(profile, "competitors") + lines(profile, "exclusions")
    segments = []
    for priority, industry in enumerate(industries[:MAX_SEGMENTS], start=1):
        keywords = types[:8] or [industry]
        segments.append({
            "segment_name": f"{industry}" if industry != "Core market" else "Core market",
            "priority": min(priority, 5),
            "fit_reason": "From your business profile (AI research was not available).",
            "industries": [industry] if industry != "Core market" else [],
            "business_types": types[:8], "keywords": keywords, "bangla_keywords": [],
            "locations": lines(profile, "regions")[:10], "buying_signals": lines(profile, "size_signals")[:8],
            "negative_keywords": negatives[:10], "evidence_urls": [],
        })
    return {"summary": "Search plan built from your business profile without AI research.",
            "segments": segments, "unknowns": ["No web research was done; enable AI for an evidence-based brief."]}


def segment_to_targeting(segment: dict, profile: dict) -> dict:
    """Sales Targeting Profile fields for one approved segment."""
    regions = segment.get("locations") or lines(profile, "regions")
    locations = []
    for label in regions[:20]:
        parts = [p.strip() for p in label.split(",") if p.strip()]
        if parts:
            locations.append({"city": parts[-1][:80], "area": ", ".join(parts[:-1])[:80], "country": COUNTRY})
    negatives = segment.get("negative_keywords", []) + lines(profile, "competitors") + lines(profile, "exclusions")
    return {
        "profile_name": segment["segment_name"][:140],
        "market": "B2B",
        "keywords": "\n".join(segment.get("keywords", []) + segment.get("bangla_keywords", [])),
        "b2b_segments": "\n".join(segment.get("business_types", [])),
        "industries": "\n".join(segment.get("industries", [])),
        "interests": "\n".join(segment.get("buying_signals", [])),
        "exclude_keywords": "\n".join(dict.fromkeys(negatives)),
        "locations": locations,
    }


def best_customer_line(name: str, website: str | None = None, industry: str | None = None) -> str:
    return " | ".join(part for part in (name, website or "", industry or "") if part is not None).rstrip(" |")

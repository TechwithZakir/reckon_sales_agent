"""Guided setup: one page that gets a Company (or a new salesperson) working, with AI filling in the blanks.

Managers walk six steps; each is done when the system says so, never by ticking a box:

    business   the website is read and the business profile filled           (AI: reads the site)
    market     the market is researched and segments chosen                   (AI: web research)
    facts      approved sales facts the Content agent may use                 (AI: drafts them for approval)
    team       sender details for emails, who makes the calls, digest list    (suggested from the account)
    sources    a lead source the Company may use                              (Smart Sources)
    autopilot  the agents run on their own within the rules                   (suggested thresholds)

A salesperson sees a short track instead: their name and number for call scripts, and how their day works.
``steps`` and ``clean_facts`` are pure; the rest uses Frappe.
"""

from __future__ import annotations

MANAGER_STEPS = (
    ("business", "Your business"),
    ("market", "Your market"),
    ("facts", "Sales facts"),
    ("team", "Your team"),
    ("sources", "Lead sources"),
    ("autopilot", "Autopilot"),
)
SELLER_STEPS = (("me", "You"), ("day", "Your day"))
FACT_CATEGORIES = ("Product", "Service", "Pricing", "Offer", "FAQ", "Proof", "Policy", "Brand")

FACTS_SCHEMA = {
    "type": "object",
    "properties": {"facts": {"type": "array", "items": {
        "type": "object",
        "properties": {"category": {"type": "string", "enum": list(FACT_CATEGORIES)}, "title": {"type": "string"},
                       "content": {"type": "string"}, "source_url": {"type": "string"}},
        "required": ["category", "title", "content", "source_url"],
        "additionalProperties": False,
    }}},
    "required": ["facts"],
    "additionalProperties": False,
}
FACTS_SYSTEM = (
    "You draft the approved-knowledge library a sales agent may quote from, for a company selling in Bangladesh. "
    "From the company's own web pages and profile, write 3 to 8 short, factual items: what each product or service "
    "does and for whom, proof points (clients, years, numbers) only when the pages state them, and any offer or "
    "price only when the pages state it. Each item is 1-4 plain sentences. source_url is the page it came from, or "
    "empty when it comes from the profile. Never invent numbers, clients, prices, guarantees or awards. A person "
    "approves every item before any message uses it."
)


def steps(state: dict, seller: bool = False) -> list[dict]:
    """The checklist with each step's done flag, from the system's real state."""
    if seller:
        done = {"me": bool(state.get("my_name")) and bool(state.get("my_phone")), "day": bool(state.get("seen_day"))}
        return [{"key": k, "title": t, "done": done[k]} for k, t in SELLER_STEPS]
    done = {
        "business": bool(state.get("has_profile")),
        "market": state.get("brief_status") == "Approved",
        "facts": int(state.get("facts_approved") or 0) > 0,
        "team": bool(state.get("sender_name")) and bool(state.get("physical_address")),
        "sources": bool(state.get("sources_ready")) and bool(state.get("connector_ready")),
        "autopilot": bool(state.get("autopilot")),
    }
    return [{"key": k, "title": t, "done": done[k]} for k, t in MANAGER_STEPS]


def progress(rows: list[dict]) -> int:
    return round(100 * sum(1 for r in rows if r["done"]) / len(rows)) if rows else 0


def clean_facts(data: dict, page_urls: set[str]) -> list[dict]:
    """Bound the model's drafts; a source_url must be one of the pages actually read."""
    out, seen = [], set()
    for item in (data.get("facts") or [])[:8]:
        title = " ".join(str(item.get("title") or "").split())[:140]
        content = " ".join(str(item.get("content") or "").split())[:1200]
        if not title or not content or title.lower() in seen:
            continue
        seen.add(title.lower())
        category = item.get("category") if item.get("category") in FACT_CATEGORIES else "Product"
        url = str(item.get("source_url") or "").strip()
        out.append({"category": category, "title": title, "content": content,
                    "source_url": url if url in page_urls else ""})
    return out


def rule_facts(profile: dict) -> list[dict]:
    """Without AI: one Product item from what the profile says."""
    what = (profile.get("what_we_sell") or "").strip()
    products = [p.strip() for p in (profile.get("products") or "").splitlines() if p.strip()]
    if not what and not products:
        return []
    content = " ".join(filter(None, [what, ("Products: " + ", ".join(products) + ".") if products else ""]))
    return [{"category": "Product", "title": f"{profile.get('business_name') or 'Our'} offering"[:140],
             "content": content[:1200], "source_url": ""}]


# --------------------------------------------------------------------------- Frappe side


def draft_facts(company: str) -> int:
    """Create Draft knowledge items from the website and profile; returns how many."""
    import frappe

    from reckon_sales_agent.agents.onboarding import _fetch
    from reckon_sales_agent.constants import USAGE_AI
    from reckon_sales_agent.providers.factory import get_llm
    from reckon_sales_agent.providers.llm import LLMError, untrusted
    from reckon_sales_agent.research.market import business_profile
    from reckon_sales_agent.usage import log_activity, remaining, reserve

    profile = business_profile(company, create=False)
    if not profile:
        frappe.throw("Describe your business first.")
    pages = []
    if profile.get("website"):
        try:
            pages = _fetch(profile.website)
        except Exception:
            pages = []
    llm = get_llm(company)
    facts = []
    if llm and remaining(company, USAGE_AI) > 0:
        reserve(company, USAGE_AI, 1, profile)
        frappe.db.commit()
        seller = "\n".join(f"{f}: {profile.get(f)}" for f in ("business_name", "what_we_sell", "products",
                                                              "problems_solved", "target_industries") if profile.get(f))
        text = untrusted("profile", seller) + "\n" + "\n\n".join(
            untrusted(p.url, f"TITLE: {p.title}\nTEXT: {p.text[:5000]}") for p in pages)
        try:
            facts = clean_facts(llm.complete_json(FACTS_SYSTEM, text, FACTS_SCHEMA, max_tokens=3000),
                                {p.url for p in pages})
        except LLMError:
            facts = []
    facts = facts or rule_facts(profile.as_dict())
    existing = {t.lower() for t in frappe.get_all("Sales Knowledge Item", filters={"company": company}, pluck="title")}
    created = 0
    for fact in facts:
        if fact["title"].lower() in existing:
            continue
        frappe.get_doc({"doctype": "Sales Knowledge Item", "company": company, "status": "Draft", "language": "Any",
                        **fact}).insert(ignore_permissions=True)
        created += 1
    log_activity(company, "content_facts_drafted", profile, f"{created} draft fact(s) for approval",
                 actor_type="agent", agent="Content", policy_outcome="draft only: a person approves")
    return created

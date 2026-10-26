"""One-line onboarding: the agent reads the seller's own website and fills in the business profile.

The manager types a website (and optionally a sentence); the Research agent
fetches a few pages of that site through the same SSRF-safe fetcher used for
prospects, asks Claude to describe the business in the profile's fields (rules
fall back to the page title and description), then starts market research.
Fields the manager already filled are never overwritten.
"""

from __future__ import annotations

PROFILE_FIELDS = ("what_we_sell", "products", "problems_solved", "target_industries", "business_types",
                  "buyer_roles", "regions", "size_signals", "competitors")
LIST_FIELDS = PROFILE_FIELDS[1:]
MAX_PAGES = 4

PROFILE_SCHEMA = {
    "type": "object",
    "properties": {
        "business_name": {"type": "string"},
        "what_we_sell": {"type": "string"},
        **{name: {"type": "array", "items": {"type": "string"}} for name in LIST_FIELDS},
    },
    "required": ["business_name", "what_we_sell", *LIST_FIELDS],
    "additionalProperties": False,
}
PROFILE_SYSTEM = (
    "You describe a company that sells to other businesses, from its own website, so a sales agent can find it "
    "new customers. Fill every field from what the pages say; where they are silent, infer conservatively from "
    "the products (for example who would buy them) and keep lists short (at most 8 items, 1-5 words each). "
    "what_we_sell is one plain sentence. regions are cities or areas the company serves (Bangladesh unless the "
    "pages say otherwise). competitors only when the pages or your general knowledge name well-known ones. "
    "Never invent figures, prices or customer names."
)


def clean_profile(data: dict) -> dict:
    """Bound and tidy what the model returned."""
    out = {"business_name": " ".join(str(data.get("business_name") or "").split())[:140],
           "what_we_sell": " ".join(str(data.get("what_we_sell") or "").split())[:500]}
    for name in LIST_FIELDS:
        items: list[str] = []
        for value in data.get(name) or []:
            item = " ".join(str(value).split())[:80]
            if item and item.lower() not in {i.lower() for i in items}:
                items.append(item)
        out[name] = items[:8]
    return out


def rule_profile(pages: list) -> dict:
    """Without AI: the business name and a description from the home page's title and meta description."""
    first = pages[0] if pages else None
    title = (getattr(first, "title", "") or "").split("|")[0].split(" - ")[0].strip()
    description = getattr(first, "description", "") or ""
    return clean_profile({"business_name": title, "what_we_sell": description or title})


def merge_into(profile, found: dict, note: str = "") -> list[str]:
    """Fill only the empty profile fields; returns the fields filled."""
    filled = []
    if found.get("business_name") and (not profile.business_name or profile.business_name == profile.company):
        profile.business_name = found["business_name"]
        filled.append("business_name")
    what = " ".join(filter(None, [found.get("what_we_sell"), note])).strip()
    if what and not profile.what_we_sell:
        profile.what_we_sell = what[:1000]
        filled.append("what_we_sell")
    for name in LIST_FIELDS:
        if found.get(name) and not (profile.get(name) or "").strip():
            profile.set(name, "\n".join(found[name]))
            filled.append(name)
    return filled


# --------------------------------------------------------------------------- Frappe side


def start(company: str, website: str, note: str = "") -> str:
    """Save the website on the profile and read it in the background."""
    import frappe
    from frappe import _

    from reckon_sales_agent.research.market import business_profile
    from reckon_sales_agent.research.runner import _normalise_url
    from reckon_sales_agent.research.url_safety import UnsafeURL, validate_url
    from reckon_sales_agent.usage import log_activity

    website = (website or "").strip()
    if not website and not note:
        frappe.throw(_("Type your website, or a sentence about what you sell."))
    url = _normalise_url(website) if website else ""
    if url:
        try:
            validate_url(url)
        except UnsafeURL as exc:
            frappe.throw(_("That website cannot be read: {0}").format(exc))
    profile = business_profile(company)
    profile.website = url or profile.get("website")
    profile.onboarding_status = "Reading website" if url else "Done"
    if not url and note and not profile.what_we_sell:
        profile.what_we_sell = " ".join(note.split())[:1000]
    profile.save(ignore_permissions=True) if not profile.is_new() else profile.insert(ignore_permissions=True)
    log_activity(company, "market_onboarding_started", profile, url or "from a description", actor_type="user",
                 agent="Research")
    if url:
        frappe.enqueue("reckon_sales_agent.agents.onboarding.read_website", queue="long", timeout=900,
                       enqueue_after_commit=True, profile=profile.name, note=note or "")
    else:
        from reckon_sales_agent.agents.orchestrator import enqueue_run

        enqueue_run(company, "onboarding")
    return profile.name


def read_website(profile: str, note: str = "") -> None:
    import frappe

    from reckon_sales_agent.agents.orchestrator import enqueue_run
    from reckon_sales_agent.usage import log_activity

    doc = frappe.get_doc("Sales Business Profile", profile)
    try:
        pages = _fetch(doc.website)
        found, method = _describe(doc.company, pages)
        doc.reload()
        filled = merge_into(doc, found, note)
        doc.onboarding_status = "Done"
        doc.save(ignore_permissions=True)
        log_activity(doc.company, "market_profile_filled", doc,
                     f"Read {len(pages)} page(s) ({method}); filled {', '.join(filled) or 'nothing new'}",
                     actor_type="agent", agent="Research", policy_outcome="automatic (research_company)")
    except Exception as exc:
        frappe.db.rollback()
        frappe.log_error(title="Sales Agent onboarding failed", reference_doctype="Sales Business Profile",
                         reference_name=profile)
        frappe.db.set_value("Sales Business Profile", profile, "onboarding_status", "Failed")
        log_activity(doc.company, "market_profile_failed", doc, str(exc)[:300], actor_type="agent", agent="Research")
    frappe.db.commit()
    enqueue_run(doc.company, "onboarding")


def _fetch(website: str) -> list:
    from reckon_sales_agent.research.parser import parse_html
    from reckon_sales_agent.research.runner import _robots_allow
    from reckon_sales_agent.research.url_safety import FetchError, UnsafeURL, fetch
    from reckon_sales_agent.usage import platform_settings

    platform = platform_settings()
    limits = dict(user_agent=platform.user_agent or "ReckonSalesAgent/1.0", timeout=platform.fetch_timeout or 10,
                  max_bytes=(platform.max_page_kb or 1024) * 1024)
    if not _robots_allow(website, limits["user_agent"], limits):
        raise ValueError("The website's robots.txt does not allow our agent to read it.")
    pages, queue, seen = [], [website], set()
    while queue and len(pages) < MAX_PAGES:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            result = fetch(url, **limits)
        except (UnsafeURL, FetchError):
            continue
        page = parse_html(result.text, result.url)
        pages.append(page)
        if len(pages) == 1:
            queue.extend(page.internal_links)
    if not pages:
        raise ValueError("No page of the website could be read.")
    return pages


def _describe(company: str, pages: list) -> tuple[dict, str]:
    import frappe

    from reckon_sales_agent.constants import USAGE_AI
    from reckon_sales_agent.providers.factory import get_llm
    from reckon_sales_agent.providers.llm import LLMError, untrusted
    from reckon_sales_agent.usage import remaining, reserve

    llm = get_llm(company)
    if not llm or remaining(company, USAGE_AI) <= 0:
        return rule_profile(pages), "rules"
    reserve(company, USAGE_AI, 1, None)
    frappe.db.commit()  # no open transaction while waiting on the model
    text = "\n\n".join(untrusted(p.url, f"TITLE: {p.title}\nDESCRIPTION: {p.description}\nTEXT: {p.text[:6000]}")
                       for p in pages)
    try:
        return clean_profile(llm.complete_json(PROFILE_SYSTEM, text, PROFILE_SCHEMA, max_tokens=3000)), "ai"
    except LLMError:
        return rule_profile(pages), "rules"

"""AI triage: the Research agent judges borderline leads so a person sees only the unclear ones.

A lead the deterministic score left in "Needs Review" (or a qualified lead
under the auto-approve bar) is shown to Claude with the seller's profile, the
segment it was found for and the evidence from its own website. Claude says
what the business really is, whether it fits, how sure it is, and which word
in its listing marks businesses like it as a misfit. Under autopilot a
confident verdict is applied (approving creates the CRM lead, as the matrix
allows); an unsure one goes to a person with the agent's reasoning.

``triage_outcome`` and the prompt pieces are pure; the rest uses Frappe.
"""

from __future__ import annotations

VERDICTS = ("approve", "reject", "unsure")
DEFAULT_MIN_CONFIDENCE = 0.8
BATCH = 20

TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "business_type": {"type": "string"},
        "verdict": {"type": "string", "enum": list(VERDICTS)},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
        "exclude_term": {"type": "string"},
    },
    "required": ["business_type", "verdict", "confidence", "reason", "exclude_term"],
    "additionalProperties": False,
}
TRIAGE_SYSTEM = (
    "You screen B2B sales leads for a seller in Bangladesh. Decide whether the business could buy the seller's "
    "offering as one of the segment's buyer types. business_type: what the business actually is, in 1-4 words "
    "(e.g. 'computer shop', 'bank branch', 'FMCG distributor', 'wholesale market'). verdict: approve when it is "
    "plausibly that kind of buyer, reject when it clearly is not (a different trade, a marketplace or association "
    "rather than a business, a bank, a manufacturer's head office when the segment is distributors), unsure when "
    "the evidence is too thin. confidence: 0 to 1. reason: one sentence citing the evidence. exclude_term: only "
    "when rejecting, one or two words copied from the business name or listing that would mark similar misfits "
    "(e.g. 'computer', 'bank', 'hypermarket'); never a word describing the wanted buyers, a generic company word "
    "(group, limited, products, company, enterprise) or a brand name; otherwise empty."
)


def triage_outcome(verdict: str, confidence: float, *, min_confidence: float = DEFAULT_MIN_CONFIDENCE,
                   duplicate: bool = False, do_not_contact: bool = False) -> str:
    """What the autopilot does with a verdict: "approve", "reject" or "person"."""
    sure = float(confidence or 0) >= float(min_confidence)
    if verdict == "reject" and sure:
        return "reject"  # a misfit is safe to set aside: it is reversible and reaches nobody
    if verdict == "approve" and sure and not duplicate and not do_not_contact:
        return "approve"
    return "person"


# Words in many company names that say nothing about the trade. Live test: the model offered "group" and
# "products limited" as misfit markers, which would have excluded every "X Group" distributor.
GENERIC_TERMS = frozenset({
    "group", "limited", "ltd", "pvt", "private", "plc", "company", "co", "corporation", "corp", "inc", "enterprise",
    "enterprises", "international", "industries", "industry", "products", "product", "trading", "traders", "house",
    "bangladesh", "bd", "dhaka", "chattogram", "the", "and", "&", "office", "branch", "center", "centre", "brothers",
    "sons", "associates", "agency", "agencies", "global", "world", "new", "best", "store", "shop",
})


def is_generic(term: str) -> bool:
    return all(word in GENERIC_TERMS for word in term.lower().replace("&", " & ").split())


def clean_verdict(data: dict) -> dict:
    verdict = data.get("verdict") if data.get("verdict") in VERDICTS else "unsure"
    term = " ".join(str(data.get("exclude_term") or "").split())[:40].lower()
    term = "" if is_generic(term) else term
    return {
        "verdict": verdict,
        "confidence": round(min(max(float(data.get("confidence") or 0), 0.0), 1.0), 2),
        "business_type": " ".join(str(data.get("business_type") or "").split())[:80],
        "reason": " ".join(str(data.get("reason") or "").split())[:400],
        "exclude_term": term if verdict == "reject" and len(term) >= 3 and len(term.split()) <= 2 else "",
    }


def lead_prompt(lead: dict, facts: list[str]) -> str:
    rows = [f"{key}: {lead.get(key)}" for key in ("business_name", "industry", "city", "address", "website",
                                                  "fit_score", "identity_confidence") if lead.get(key)]
    rows.append("research summary: " + (lead.get("summary") or "none"))
    rows.extend(f"fact: {fact}" for fact in facts[:15])
    return "\n".join(rows)


# --------------------------------------------------------------------------- Frappe side


def untriaged(company: str, limit: int = 2000) -> list[str]:
    """Pending borderline leads whose research has finished and that no agent has judged yet."""
    import frappe

    return frappe.get_all("Sales Prospect", filters={
        "company": company, "review_status": "Pending", "qualification_status": ["in", ["Needs Review", "Qualified"]],
        "research_status": ["in", ["Done", "Skipped", "Failed"]], "ai_triaged_on": ["is", "not set"],
        "source_type": ["!=", "fixture"],  # demo data: never worth an AI call (set aside by auto_triage)
    }, pluck="name", order_by="fit_score desc", limit=limit)


def triage_batch(company: str, apply: bool) -> dict:
    """Judge up to ``BATCH`` leads; with ``apply`` (autopilot), act on the confident verdicts."""
    from reckon_sales_agent.constants import USAGE_AI
    from reckon_sales_agent.usage import remaining

    counts = {"approve": 0, "reject": 0, "person": 0, "judged": 0}
    for name in untriaged(company, BATCH):
        if remaining(company, USAGE_AI) <= 0:
            break
        outcome = triage_prospect(name, apply)
        if outcome:
            counts["judged"] += 1
            counts[outcome] += 1
    return counts


def triage_prospect(name: str, apply: bool = False) -> str | None:
    import frappe
    from frappe.utils import now_datetime

    from reckon_sales_agent.constants import USAGE_AI
    from reckon_sales_agent.providers.factory import get_llm
    from reckon_sales_agent.providers.llm import LLMError, untrusted
    from reckon_sales_agent.usage import get_settings, log_activity, reserve

    prospect = frappe.get_doc("Sales Prospect", name)
    llm = get_llm(prospect.company)
    if not llm:
        return None
    settings = get_settings(prospect.company)
    reserve(prospect.company, USAGE_AI, 1, prospect)
    frappe.db.commit()  # no open transaction while waiting on the model
    summary, facts = "", []
    if prospect.latest_research:
        report = frappe.get_doc("Sales Research Report", prospect.latest_research)
        summary = report.summary or ""
        facts = [row.statement for row in report.facts]
    lead = {**prospect.as_dict(), "summary": summary}
    try:
        data = clean_verdict(llm.complete_json(
            TRIAGE_SYSTEM,
            untrusted("seller", _seller(prospect.company)) + "\n" + untrusted("segment", _segment(prospect)) + "\n"
            + untrusted("lead", lead_prompt(lead, facts)),
            TRIAGE_SCHEMA, max_tokens=1500))
    except LLMError as exc:
        prospect.db_set({"ai_triaged_on": now_datetime(), "ai_triage_verdict": "unsure",
                         "ai_triage_reason": f"AI triage failed: {exc}"[:400]})
        return "person"
    prospect.db_set({"ai_triage_verdict": data["verdict"], "ai_triage_confidence": data["confidence"],
                     "ai_triage_reason": data["reason"], "ai_business_type": data["business_type"],
                     "ai_exclude_term": data["exclude_term"], "ai_triaged_on": now_datetime()})
    min_confidence = float(settings.get("ai_triage_min_confidence") or DEFAULT_MIN_CONFIDENCE * 100) / 100
    outcome = triage_outcome(data["verdict"], data["confidence"], min_confidence=min_confidence,
                             duplicate=bool(prospect.possible_duplicate_of),
                             do_not_contact=bool(prospect.do_not_contact))
    summary_line = f"{data['business_type'] or 'Business'}: {data['verdict']} ({data['confidence']:.0%}). {data['reason']}"
    log_activity(prospect.company, "prospect_triaged", prospect, summary_line, actor_type="agent", agent="Research",
                 policy_outcome="automatic (score_lead)")
    if apply and outcome in ("approve", "reject"):
        from reckon_sales_agent.crm_sync import review

        prospect.reload()
        review(prospect, outcome, f"AI triage ({data['confidence']:.0%}): {data['reason']}"[:500])
        frappe.db.commit()
    return outcome


def _seller(company: str) -> str:
    from reckon_sales_agent.research.market import business_profile

    profile = business_profile(company, create=False)
    if not profile:
        return company
    return "\n".join(f"{field}: {profile.get(field)}" for field in
                     ("business_name", "what_we_sell", "products", "target_industries", "business_types", "exclusions")
                     if profile.get(field))


def _segment(prospect) -> str:
    import frappe

    target = frappe.db.get_value("Sales Discovery Campaign", prospect.discovery_campaign, "targeting_profile") \
        if prospect.discovery_campaign else None
    if not target:
        return "No segment recorded; judge against the seller's target business types."
    doc = frappe.get_doc("Sales Targeting Profile", target)
    return (f"segment: {doc.profile_name}\nbuyer types: {doc.b2b_segments or '-'}\nindustries: {doc.industries or '-'}\n"
            f"needs: {doc.interests or '-'}\nnot wanted: {doc.exclude_keywords or '-'}")

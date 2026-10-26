"""Learning from decisions: every approval and rejection tunes the segment's next searches.

Two lessons per targeting profile, from its leads that a person or an agent
approved or rejected:

- exclude: a term the AI triage named as a misfit marker ("computer", "bank")
  that keeps coming back in rejected leads and never in approved ones becomes
  an exclusion keyword, so discovery skips such businesses.
- retire: a search keyword whose leads were all rejected (enough of them) is
  dropped from the profile, so the budget goes to keywords that work.

Guards: a term that describes the wanted buyers (in the profile's keywords,
segments or industries) is never excluded, and a profile always keeps at
least two keywords. ``learn`` is pure; ``apply_lessons`` writes them.
"""

from __future__ import annotations

MIN_REJECTIONS_TO_EXCLUDE = 3
MIN_DECISIONS_TO_RETIRE = 5
KEEP_KEYWORDS = 2


def _lines(value) -> list[str]:
    return [line.strip() for line in (value or "").splitlines() if line.strip()]


def learn(decisions: list[dict], profile: dict) -> dict:
    """``decisions``: {"keyword", "term", "name", "approved"} per lead; approved is None while it is undecided.

    Returns {"exclude", "retire"}.
    """
    keywords = _lines(profile.get("keywords"))
    wanted = " ".join(_lines(profile.get("keywords")) + _lines(profile.get("b2b_segments"))
                      + _lines(profile.get("industries"))).lower()
    excluded = {x.lower() for x in _lines(profile.get("exclude_keywords"))}
    approved_names = " ".join((d.get("name") or "").lower() for d in decisions if d.get("approved"))

    from reckon_sales_agent.agents.triage import is_generic

    rejected_terms: dict[str, int] = {}
    for d in decisions:
        term = (d.get("term") or "").strip().lower()
        if term and d.get("approved") is False and not is_generic(term):  # markers stored before the filter
            rejected_terms[term] = rejected_terms.get(term, 0) + 1
    exclude = sorted(term for term, count in rejected_terms.items()
                     if count >= MIN_REJECTIONS_TO_EXCLUDE and term not in excluded and term not in wanted
                     and term not in approved_names)

    # Live test: "medicine wholesaler" was about to retire on five low-score rejections while five of its leads,
    # one scoring 60, were still undecided. A keyword is judged only once all its leads are decided.
    per_keyword: dict[str, list] = {}
    for d in decisions:
        if d.get("keyword"):
            per_keyword.setdefault(d["keyword"].strip().lower(), []).append(d.get("approved"))
    retire = []
    for keyword in keywords:
        outcomes = per_keyword.get(keyword.lower(), [])
        if None in outcomes:
            continue
        if len(outcomes) >= MIN_DECISIONS_TO_RETIRE and not any(outcomes):
            retire.append(keyword)
    retire = retire[:max(0, len(keywords) - KEEP_KEYWORDS)]
    return {"exclude": exclude, "retire": retire}


# --------------------------------------------------------------------------- Frappe side


def lessons(company: str) -> list[dict]:
    """Pending lessons per targeting profile used by this Company's lead searches."""
    import frappe

    out = []
    for target in sorted(set(frappe.get_all("Sales Discovery Campaign", filters={
            "company": company, "targeting_profile": ["is", "set"]}, pluck="targeting_profile"))):
        campaigns = frappe.get_all("Sales Discovery Campaign", filters={"targeting_profile": target}, pluck="name")
        rows = frappe.get_all("Sales Prospect", filters={
            "company": company, "discovery_campaign": ["in", campaigns],
            "review_status": ["in", ["Approved", "Rejected", "Pending"]]},
            fields=["industry", "ai_exclude_term", "business_name", "review_status"], limit=5000)
        if not rows:
            continue
        profile = frappe.get_doc("Sales Targeting Profile", target)
        found = learn([{"keyword": r.industry, "term": r.ai_exclude_term, "name": r.business_name,
                        "approved": None if r.review_status == "Pending" else r.review_status == "Approved"}
                       for r in rows], profile.as_dict())
        if found["exclude"] or found["retire"]:
            out.append({"profile": target, "label": profile.profile_name, **found})
    return out


def apply_lessons(company: str) -> str:
    import frappe

    from reckon_sales_agent.discovery.targeting import merge_lines
    from reckon_sales_agent.usage import log_activity

    applied = []
    for lesson in lessons(company):
        profile = frappe.get_doc("Sales Targeting Profile", lesson["profile"])
        if lesson["exclude"]:
            profile.exclude_keywords = merge_lines(profile.exclude_keywords, lesson["exclude"])
        if lesson["retire"]:
            gone = {k.lower() for k in lesson["retire"]}
            profile.keywords = "\n".join(k for k in _lines(profile.keywords) if k.lower() not in gone)
        profile.flags.ignore_permissions = True
        profile.save()
        detail = "; ".join(filter(None, [
            "skip businesses mentioning " + ", ".join(lesson["exclude"]) if lesson["exclude"] else "",
            "stop searching " + ", ".join(lesson["retire"]) if lesson["retire"] else ""]))
        log_activity(company, "targeting_learned", profile, detail, actor_type="agent", agent="Research",
                     policy_outcome="automatic (learned from approvals and rejections)")
        applied.append(f"{lesson['label']}: {detail}")
    return " | ".join(applied) or "nothing new"

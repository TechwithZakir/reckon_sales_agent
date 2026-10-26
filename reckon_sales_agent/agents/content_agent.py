"""Content agent: writes campaign sequences from approved knowledge and checks every message's claims.

Writing a draft is automatic; sending it is not. A written sequence replaces
the campaign's steps, so any earlier approval no longer matches and a person
approves again (see ``agents.approvals``). Every save runs the rule checks;
"Check content" adds Claude's claim check against the approved knowledge.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import getdate, now_datetime, nowdate

from reckon_sales_agent.agents.content import (
    CLAIM_SCHEMA,
    CLAIM_SYSTEM,
    SEQUENCE_SCHEMA,
    SEQUENCE_SYSTEM,
    check_steps,
    clean_steps,
    default_plan,
    knowledge_prompt,
)
from reckon_sales_agent.constants import USAGE_AI
from reckon_sales_agent.providers.factory import get_llm
from reckon_sales_agent.providers.llm import LLMError, untrusted
from reckon_sales_agent.usage import log_activity, remaining, reserve

KNOWLEDGE = "Sales Knowledge Item"
EDITABLE = ("Draft", "Paused", "Pending Approval")


def approved_knowledge(company: str, language: str | None = None) -> list[dict]:
    """Approved, unexpired knowledge items in the language (or Any)."""
    rows = frappe.get_all(KNOWLEDGE, filters={"company": company, "status": "Approved"},
                          fields=["title", "category", "content", "language", "valid_until"], limit=200)
    today = getdate(nowdate())
    return [r for r in rows if (not r.valid_until or getdate(r.valid_until) >= today)
            and (not language or r.language in (None, "", "Any", language))]


def _brand(company: str) -> tuple[str, list[str], dict]:
    profile = frappe.db.get_value("Sales Business Profile", {"company": company},
                                  ["business_name", "what_we_sell", "products", "problems_solved", "brand_voice",
                                   "banned_phrases"], as_dict=True) or {}
    banned = [line.strip() for line in (profile.get("banned_phrases") or "").splitlines() if line.strip()]
    return profile.get("brand_voice") or "friendly, professional and concise", banned, profile


def _segment(campaign) -> str:
    target = campaign.get("targeting_profile")
    if not target and campaign.discovery_campaign:
        target = frappe.db.get_value("Sales Discovery Campaign", campaign.discovery_campaign, "targeting_profile")
    if not target:
        return "No segment chosen: write for B2B businesses in Bangladesh that fit the seller's offer."
    profile = frappe.db.get_value("Sales Targeting Profile", target,
                                  ["profile_name", "industries", "b2b_segments", "interests"], as_dict=True) or {}
    why = frappe.db.get_value("Sales Market Segment", {"targeting_profile": target}, "fit_reason") or ""
    return (f"Segment: {profile.get('profile_name')}\nIndustries: {profile.get('industries') or '-'}\n"
            f"Business types: {profile.get('b2b_segments') or '-'}\nBuying signals: {profile.get('interests') or '-'}\n"
            f"Why they fit: {why or '-'}")


def write_sequence(campaign, steps: int = 3, channels: list[str] | None = None) -> int:
    """Claude writes the campaign's steps; returns how many were written."""
    if campaign.status not in EDITABLE:
        frappe.throw(_("Pause the campaign before rewriting its messages."))
    llm = get_llm(campaign.company)
    if not llm:
        frappe.throw(_("Turn on AI in Sales Agent Settings to write with AI."))
    if remaining(campaign.company, USAGE_AI) <= 0:
        frappe.throw(_("Monthly AI limit reached."))
    language = campaign.get("language") or "English"
    plan = default_plan(steps, channels or ["Email", "WhatsApp"])
    voice, banned, profile = _brand(campaign.company)
    knowledge = approved_knowledge(campaign.company, language)
    reserve(campaign.company, USAGE_AI, 1, campaign)
    frappe.db.commit()  # no open transaction while waiting on the model
    seller = "\n".join(f"{k}: {v}" for k, v in profile.items() if v and k != "banned_phrases")
    slots = "\n".join(f"Step {p['step_no']}: {p['channel']}, {p['delay_days']} days after the previous step"
                      for p in plan)
    try:
        data = llm.complete_json(
            SEQUENCE_SYSTEM + f" Brand voice: {voice}. Never use: {', '.join(banned) or 'n/a'}.",
            untrusted("seller", seller or campaign.company) + "\n"
            + untrusted("segment", _segment(campaign)) + "\n"
            + untrusted("approved knowledge", knowledge_prompt(knowledge)) + "\n"
            + untrusted("campaign offer", campaign.offer or "-") + "\n"
            + f"Language: {language}\nWrite exactly these steps:\n{slots}",
            SEQUENCE_SCHEMA,
            max_tokens=6000,
        )
    except LLMError as exc:
        frappe.throw(str(exc))
    rows = clean_steps(data, plan)
    if not rows:
        frappe.throw(_("The AI returned no usable messages; try again."))
    campaign.set("steps", [])
    for row in rows:
        campaign.append("steps", row)
    campaign.save()  # the content check runs on save; a changed campaign needs approval again
    log_activity(campaign.company, "content_sequence_written", campaign,
                 f"{len(rows)} steps in {language} from {len(knowledge)} approved knowledge items",
                 actor_type="agent", agent="Content", policy_outcome="automatic (draft only)")
    return len(rows)


def rule_check(campaign) -> dict:
    _voice, banned, _profile = _brand(campaign.company)
    steps = [{"step_no": s.step_no, "channel": s.channel, "subject_template": s.subject_template,
              "body_template": s.body_template} for s in campaign.steps]
    return check_steps(steps, approved_knowledge(campaign.company, campaign.get("language")), banned)


def apply_rule_check(campaign) -> None:
    """Called on every campaign save: record the deterministic check's result on the document."""
    result = rule_check(campaign)
    campaign.content_status = result["status"]
    campaign.content_issues = "\n".join(result["issues"])[:5000]
    campaign.content_checked_on = now_datetime()


def check_campaign(campaign) -> dict:
    """Rule checks plus, when AI is on, Claude's check for claims the approved knowledge does not support."""
    result = rule_check(campaign)
    llm = get_llm(campaign.company)
    if llm and remaining(campaign.company, USAGE_AI) > 0 and campaign.steps:
        knowledge = approved_knowledge(campaign.company, campaign.get("language"))
        messages = "\n\n".join(f"Step {s.step_no} ({s.channel}): {s.subject_template or ''}\n{s.body_template or ''}"
                               for s in campaign.steps)
        reserve(campaign.company, USAGE_AI, 1, campaign)
        frappe.db.commit()
        try:
            data = llm.complete_json(CLAIM_SYSTEM, untrusted("approved knowledge", knowledge_prompt(knowledge))
                                     + "\n" + untrusted("messages", messages), CLAIM_SCHEMA, max_tokens=3000)
            claims = [" ".join(str(c).split())[:300] for c in data.get("unsupported_claims") or [] if str(c).strip()]
            result["issues"] += [f"Unsupported claim: {claim}" for claim in claims[:15]]
        except LLMError as exc:
            result["issues"].append(f"AI claim check could not run: {exc}")
    result["status"] = "Needs review" if result["issues"] else "Passed"
    campaign.db_set({"content_status": result["status"], "content_issues": "\n".join(result["issues"])[:5000],
                     "content_checked_on": now_datetime()})
    log_activity(campaign.company, "content_checked", campaign, f"{result['status']}: {len(result['issues'])} issue(s)",
                 actor_type="agent", agent="Content")
    return result


def approve_knowledge(names: list[str]) -> int:
    approved = 0
    for name in names:
        doc = frappe.get_doc(KNOWLEDGE, name)
        doc.check_permission("write")
        if doc.status != "Approved":
            doc.db_set({"status": "Approved", "approved_by": frappe.session.user, "approved_on": now_datetime()})
            log_activity(doc.company, "content_knowledge_approved", doc, doc.title, agent="Governance")
            approved += 1
    return approved

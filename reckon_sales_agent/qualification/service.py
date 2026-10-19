"""Qualify a prospect: deterministic score, optional AI assessment, deal probability, autopilot."""

from __future__ import annotations

import frappe
from frappe.utils import add_days, nowdate

from reckon_sales_agent.constants import USAGE_AI
from reckon_sales_agent.providers.factory import get_llm
from reckon_sales_agent.providers.llm import LLMError
from reckon_sales_agent.qualification import ai_assessment
from reckon_sales_agent.qualification.probability import (
    MODEL_VERSION,
    calibrate,
    combine,
    deal_probability,
)
from reckon_sales_agent.qualification.scoring import score
from reckon_sales_agent.usage import get_settings, log_activity, remaining, reserve

CALIBRATION_MIN_AGE_DAYS = 14


def qualify_prospect(prospect_name: str) -> str:
    """Score a prospect from its latest research; human overrides stay in force."""
    prospect = frappe.get_doc("Sales Prospect", prospect_name)
    settings = get_settings(prospect.company)
    facts = []
    if prospect.latest_research:
        facts = [row.as_dict() for row in frappe.get_doc("Sales Research Report", prospect.latest_research).facts]
    profile_name = None
    if prospect.discovery_campaign:
        profile_name = frappe.db.get_value("Sales Discovery Campaign", prospect.discovery_campaign,
                                           "qualification_profile")
    profile_name = profile_name or frappe.db.get_value(
        "Sales Qualification Profile", {"company": prospect.company}, "name", order_by="creation asc")
    profile = frappe.get_doc("Sales Qualification Profile", profile_name).as_dict() if profile_name else None

    result = score(prospect.as_dict(), facts, profile)
    verified = [f for f in facts if not f.get("is_inference")]
    ai = _ai_assessment(prospect, settings, verified)
    result.update(ai)
    combined = combine(result["fit_score"], ai.get("ai_fit_score"), settings.ai_score_weight or 0)
    result["combined_score"] = combined
    if ai:
        # The AI only shifts the blend; thresholds still need real evidence.
        qualify_at = float((profile or {}).get("qualify_threshold") or 60)
        review_at = float((profile or {}).get("review_threshold") or 40)
        if combined >= qualify_at and result["evidence_quality"] >= 30:
            result["result"] = "Qualified"
        elif combined >= review_at:
            result["result"] = "Needs Review"
        else:
            result["result"] = "Not Qualified"

    features = {
        "fit": combined,
        "buying": max(result["buying_signal_score"], 0),
        "evidence": result["evidence_confidence"],
        "contactable": result["contactability"] == "Contactable",
        "do_not_contact": prospect.do_not_contact,
        **engagement(prospect.name),
    }
    probability, why = deal_probability(features, company_calibration(prospect.company))
    result["deal_probability"] = probability
    result["probability_model"] = MODEL_VERSION
    result["explanation"] = f"{result['explanation']} Deal probability {probability}% ({why}).".strip()

    previous_override = None
    if prospect.latest_qualification:
        previous_override = frappe.db.get_value(
            "Sales Qualification", prospect.latest_qualification,
            ["override_result", "override_reason", "overridden_by"], as_dict=True)
    qualification = frappe.get_doc({
        "doctype": "Sales Qualification",
        "company": prospect.company,
        "prospect": prospect.name,
        "profile": profile_name,
        **result,
    })
    if previous_override and previous_override.override_result:
        qualification.update(previous_override)
    qualification.insert(ignore_permissions=True)
    prospect.db_set({
        "latest_qualification": qualification.name,
        "qualification_status": qualification.override_result or result["result"],
        "fit_score": combined,
        "ai_fit_score": ai.get("ai_fit_score"),
        "buying_signal_score": result["buying_signal_score"],
        "evidence_confidence": result["evidence_confidence"],
        "contactability": result["contactability"],
        "deal_probability": probability,
    })
    log_activity(prospect.company, "qualified", prospect,
                 f"{qualification.override_result or result['result']} (score {combined}, "
                 f"probability {probability}%, {result['scoring_version']})", "system")
    _sync_deal_probability(prospect.crm_lead, probability)

    from reckon_sales_agent.autopilot import maybe_auto_approve

    maybe_auto_approve(prospect.name)
    return qualification.name


def _ai_assessment(prospect, settings, facts: list[dict]) -> dict:
    if not facts:
        return {}
    llm = get_llm(prospect.company)
    if not llm or remaining(prospect.company, USAGE_AI) <= 0:
        return {}
    try:
        reserve(prospect.company, USAGE_AI, 1, prospect)
        frappe.db.commit()  # no open transaction while waiting on the model
        data = llm.complete_json(
            ai_assessment.SYSTEM,
            ai_assessment.build_prompt(settings.company_profile, prospect.as_dict(), facts[:40]),
            ai_assessment.SCHEMA,
        )
    except LLMError:
        return {}
    return ai_assessment.sanitize(data, facts)


def engagement(prospect_name: str) -> dict:
    """Outreach signals for the probability model."""
    members = frappe.get_all("Sales Campaign Member", filters={"prospect": prospect_name},
                             fields=["name", "stop_reason", "reply_classification"])
    flags = {"replied": False, "positive_reply": False, "meeting": False, "unsubscribed": False}
    for member in members:
        if member.stop_reason == "unsubscribed":
            flags["unsubscribed"] = True
        if member.reply_classification:
            flags["replied"] = True
        if member.reply_classification in ("interested", "meeting_request"):
            flags["positive_reply"] = True
        if member.reply_classification == "meeting_request":
            flags["meeting"] = True
    return flags


def company_calibration(company: str) -> dict:
    """{fit band: (deals, leads)} from this Company's synced prospects old enough to have an outcome."""
    cache = getattr(frappe.local, "sales_agent_calibration", None)
    if cache is None:
        cache = frappe.local.sales_agent_calibration = {}  # per request/job
    if company in cache:
        return cache[company]
    rows = frappe.get_all(
        "Sales Prospect",
        filters={"company": company, "crm_lead": ["is", "set"],
                 "creation": ["<", add_days(nowdate(), -CALIBRATION_MIN_AGE_DAYS)]},
        fields=["fit_score", "crm_lead"],
        limit=5000,
    )
    converted = set(frappe.get_all("CRM Deal", filters={"lead": ["in", [r.crm_lead for r in rows] or [""]]},
                                   pluck="lead")) if rows else set()
    cache[company] = calibrate([(r.fit_score or 0, r.crm_lead in converted) for r in rows])
    return cache[company]


def _sync_deal_probability(lead: str | None, probability: float) -> None:
    """Fill an open CRM Deal's probability only when nobody has set one."""
    if not lead:
        return
    for deal in frappe.get_all("CRM Deal", filters={"lead": lead}, fields=["name", "probability"]):
        if not deal.probability:
            frappe.db.set_value("CRM Deal", deal.name, "probability", probability, update_modified=False)


def recalibrate_all() -> None:
    """Weekly: re-score recent prospects so probabilities learn from new outcomes."""
    for name in frappe.get_all("Sales Prospect",
                               filters={"review_status": ["in", ["Pending", "Approved"]],
                                        "latest_qualification": ["is", "set"],
                                        "modified": [">=", add_days(nowdate(), -90)]},
                               pluck="name", limit=2000):
        prospect = frappe.get_doc("Sales Prospect", name)
        features = {
            "fit": prospect.fit_score, "buying": prospect.buying_signal_score,
            "evidence": prospect.evidence_confidence, "contactable": prospect.contactability == "Contactable",
            "do_not_contact": prospect.do_not_contact, **engagement(name),
        }
        probability, _why = deal_probability(features, company_calibration(prospect.company))
        if probability != prospect.deal_probability:
            prospect.db_set("deal_probability", probability, update_modified=False)
            _sync_deal_probability(prospect.crm_lead, probability)
    frappe.db.commit()

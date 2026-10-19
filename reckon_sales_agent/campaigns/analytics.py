"""Campaign analytics: funnel by channel and step, outcomes, and an AI-written insight.

Metrics are computed from Sales Communication Events and CRM outcomes. The
AI only sees aggregated numbers (no names, emails or phone numbers) and is
asked for an analysis and concrete recommendations, never for raw data.
"""

from __future__ import annotations

import json

import frappe
from frappe.utils import now_datetime

from reckon_sales_agent.campaigns.metrics import summarize
from reckon_sales_agent.constants import USAGE_AI
from reckon_sales_agent.providers.factory import get_llm
from reckon_sales_agent.providers.llm import LLMError
from reckon_sales_agent.usage import log_activity, remaining, reserve

INSIGHT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "recommendations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "recommendations"],
    "additionalProperties": False,
}
def campaign_metrics(campaign_name: str) -> dict:
    events = frappe.db.sql(
        """select e.event_type, coalesce(m.channel, e.channel) as channel, m.step_no
        from `tabSales Communication Event` e
        left join `tabSales Outreach Message` m on m.name = e.message
        where e.campaign = %s""",
        campaign_name,
        as_dict=True,
    )
    members = frappe.get_all("Sales Campaign Member", filters={"campaign": campaign_name},
                             fields=["status", "crm_lead"], limit=20000)
    leads = [m.crm_lead for m in members if m.crm_lead]
    deals = []
    if leads:
        fields = ["name", "status"]
        if frappe.db.has_column("CRM Deal", "deal_value"):
            fields.append("deal_value")
        elif frappe.db.has_column("CRM Deal", "annual_revenue"):
            fields.append("annual_revenue as deal_value")
        deals = frappe.get_all("CRM Deal", filters={"lead": ["in", leads]}, fields=fields)
    return summarize(events, members, deals)


def analyze_campaign(campaign) -> str:
    """Store metrics and (when AI is enabled) Claude's analysis as a Sales Campaign Insight."""
    metrics = campaign_metrics(campaign.name)
    summary, recommendations, model = _rule_insight(metrics), [], None
    llm = get_llm(campaign.company)
    if llm and remaining(campaign.company, USAGE_AI) > 0:
        try:
            reserve(campaign.company, USAGE_AI, 1, campaign)
            frappe.db.commit()
            steps = [{"step": s.step_no, "channel": s.channel, "delay_days": s.delay_days,
                      "subject": s.subject_template[:120]} for s in campaign.steps]
            data = llm.complete_json(
                "You are a B2B sales operations analyst. Analyse this outreach campaign's aggregated "
                "results for a Bangladeshi company. Explain what is working and what is not, compare "
                "channels and steps, and give 3-6 specific, actionable recommendations (timing, channel "
                "mix, targeting, message). Use only the numbers given; say when the sample is too small "
                "to conclude anything.",
                json.dumps({"offer": campaign.offer or "", "steps": steps, "metrics": metrics}, ensure_ascii=False),
                INSIGHT_SCHEMA,
                max_tokens=4000,
            )
            summary = " ".join(str(data.get("summary") or "").split())[:3000] or summary
            recommendations = [" ".join(str(r).split())[:300] for r in (data.get("recommendations") or [])][:6]
            model = llm.model
        except LLMError:
            pass
    insight = frappe.get_doc({
        "doctype": "Sales Campaign Insight",
        "company": campaign.company,
        "campaign": campaign.name,
        "generated_on": now_datetime(),
        "model": model,
        "summary": summary,
        "recommendations": "\n".join(f"• {r}" for r in recommendations),
        "metrics_json": json.dumps(metrics, indent=1),
    }).insert(ignore_permissions=True)
    frappe.db.set_value("Sales Campaign", campaign.name, "latest_insight", insight.name, update_modified=False)
    log_activity(campaign.company, "campaign_analyzed", campaign, insight.name, "agent" if model else "system")
    return insight.name


def _rule_insight(metrics: dict) -> str:
    t = metrics["totals"]
    if not t["outreach"]:
        return "Nothing has been sent yet."
    best = max(metrics["by_channel"].items(), key=lambda kv: kv[1]["positive_rate"], default=(None, None))[0]
    return (f"{t['outreach']} messages, reply rate {metrics['reply_rate']}%, positive {metrics['positive_reply_rate']}%, "
            f"{t['meetings']} meetings, {metrics['deals']} deals, unsubscribe rate {metrics['unsubscribe_rate']}%."
            + (f" Best channel so far: {best}." if best else ""))


def analyze_active_campaigns() -> None:
    """Weekly: refresh insights for active campaigns."""
    for name in frappe.get_all("Sales Campaign", filters={"status": ["in", ["Active", "Completed"]]}, pluck="name"):
        try:
            analyze_campaign(frappe.get_doc("Sales Campaign", name))
            frappe.db.commit()
        except Exception:
            frappe.db.rollback()
            frappe.log_error(title="Sales Agent campaign analysis failed", reference_doctype="Sales Campaign",
                             reference_name=name)

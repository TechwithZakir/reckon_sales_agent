"""Backend for the Agent Studio: one page where the agents work and a person only decides.

``state`` returns everything the page shows (agent lanes, the Needs-you inbox,
the funnel and the live activity feed) in one call, so the page can poll it.
Every approval goes through the same checked paths as the forms.
"""

from __future__ import annotations

import json

import frappe
from frappe import _

from reckon_sales_agent.agents.orchestrator import ASK, DO, WAIT, collect_state, lane_status, plan
from reckon_sales_agent.api_studio import _can_manage
from reckon_sales_agent.tenant import current_company, get_tenant_doc
from reckon_sales_agent.usage import assert_entitled, get_settings, log_activity

AGENTS = ("Research", "Content", "Governance", "Engagement", "Analytics")
LANE_TITLES = {
    "Research": "Finds and qualifies leads",
    "Content": "Writes campaigns from approved facts",
    "Governance": "Keeps launches and sending with a person",
    "Engagement": "Handles replies and follow-ups",
    "Analytics": "Measures pilots and recommends",
}


def _require_manager() -> None:
    if not _can_manage():
        frappe.throw(_("Ask a Sales Agent admin or manager to do this."), frappe.PermissionError)


def _args(value) -> dict:
    if isinstance(value, str):
        value = json.loads(value or "{}")
    return value if isinstance(value, dict) else {}


@frappe.whitelist()
def state() -> dict:
    company = current_company()
    settings = get_settings(company)
    snapshot = collect_state(company)
    steps = plan(snapshot)
    count = lambda doctype, **f: frappe.db.count(doctype, {"company": company, **f})  # noqa: E731
    events = lambda *types: count("Sales Communication Event", event_type=["in", list(types)])  # noqa: E731
    funnel = [
        (_("Found"), count("Sales Prospect")),
        (_("Researched"), count("Sales Prospect", research_status="Done")),
        (_("Qualified"), count("Sales Prospect", qualification_status="Qualified")),
        (_("Approved"), count("Sales Prospect", review_status="Approved")),
        (_("In CRM"), count("Sales Prospect", crm_lead=["is", "set"])),
        # A call someone answered counts as contact and as a reply; "interested" as positive.
        (_("Contacted"), events("sent", "dry_run", "call_interested", "call_callback", "call_not_interested")),
        (_("Replied"), events("received", "call_interested", "call_callback", "call_not_interested")),
        (_("Positive"), events("positive_reply", "meeting_requested", "call_interested")),
    ]
    metrics = {
        "Research": [(_("leads"), funnel[0][1]), (_("qualified"), funnel[2][1]),
                     (_("searching"), snapshot.get("running_jobs", 0))],
        "Content": [(_("campaigns"), count("Sales Campaign")),
                    (_("facts approved"), count("Sales Knowledge Item", status="Approved"))],
        "Governance": [(_("awaiting you"), len(snapshot.get("campaigns_pending") or [])),
                       (_("live"), count("Sales Campaign", status="Active"))],
        "Engagement": [(_("drafts"), snapshot.get("drafts_waiting", 0)), (_("replies"), funnel[6][1]),
                       (_("follow-ups"), snapshot.get("open_followups", 0))],
        "Analytics": [(_("pilots"), count("Sales Campaign", pilot_mode=1, status="Active")),
                      (_("measured"), count("Sales Campaign", pilot_verdict=["is", "set"]))],
    }
    feed = frappe.get_list("Sales Agent Activity", filters={"company": company},
                           fields=["name", "agent", "action", "summary", "actor_type", "creation",
                                   "reference_doctype", "reference_name", "policy_outcome"],
                           order_by="creation desc", page_length=40)
    latest = {}
    for row in feed:
        latest.setdefault(row.agent or "Governance", row)
    return {
        "company": company,
        "can_manage": _can_manage(),
        "ai": snapshot.get("ai"),
        "ai_label": _ai_label(company),
        "outbound_enabled": bool(settings.outbound_enabled),
        "kill_switch": bool(settings.kill_switch),
        "human_approval": bool(settings.human_approval_required),
        "office_phone": settings.get("telephony_provider") == "Asterisk (SIP)" and bool(settings.get("ari_url")),
        "autopilot": {
            "enabled": bool(settings.get("autopilot_enabled")),
            "auto_segments": bool(settings.get("autopilot_auto_segments")),
            "weekly_leads": settings.get("autopilot_weekly_leads") or 50,
            "min_prospects": settings.get("autopilot_campaign_min_prospects") or 5,
            "auto_approve_min_fit": settings.auto_approve_min_fit,
            "ai_triage": bool(settings.get("autopilot_ai_triage")),
            "task_assignee": settings.get("task_assignee") or "",
            "daily_digest": bool(settings.get("daily_digest")),
            "digest_recipients": settings.get("digest_recipients") or "",
            "last_run": settings.get("autopilot_last_run"),
            "summary": settings.get("autopilot_summary"),
        },
        "lanes": [{
            "agent": agent, "title": _(LANE_TITLES[agent]), "status": lane_status(steps, agent),
            "now": [s.title for s in steps if s.agent == agent and s.kind in (DO, WAIT)],
            "metrics": metrics[agent],
            "last": latest.get(agent),
        } for agent in AGENTS],
        "asks": [_detail(company, s) for s in steps if s.kind == ASK],
        "upcoming": [s.as_dict() for s in steps if s.kind == DO],
        "funnel": funnel,
        "feed": feed,
    }


def _detail(company: str, step) -> dict:
    """An inbox card with what a person needs to decide without leaving the page."""
    item = step.as_dict()
    if step.key == "approve_segments":
        brief = frappe.get_doc("Sales Market Brief", step.ref["brief"])
        item["summary"] = brief.summary
        item["segments"] = [{"name": r.name, "segment_name": r.segment_name, "priority": r.priority,
                             "fit_reason": r.fit_reason, "include": r.include,
                             "keywords": (r.keywords or "").splitlines()[:6]} for r in brief.segments]
    elif step.key == "approve_campaign":
        campaign = frappe.get_doc("Sales Campaign", step.ref["campaign"])
        item["campaign"] = {
            "name": campaign.name, "offer": campaign.offer, "content_status": campaign.content_status,
            "issues": (campaign.content_issues or "").splitlines()[:10], "pilot": bool(campaign.pilot_mode),
            "holdout": campaign.holdout_percent, "pilot_max": campaign.pilot_max_members,
            "daily_limit": campaign.daily_limit,
            "steps": [{"step_no": s.step_no, "channel": s.channel, "delay_days": s.delay_days,
                       "subject": s.subject_template, "body": s.body_template} for s in campaign.steps],
        }
    elif step.key == "approve_drafts":
        item["messages"] = frappe.get_list("Sales Outreach Message", filters={"company": company, "status": "Draft"},
                                           fields=["name", "channel", "recipient", "subject", "body", "is_reply",
                                                   "campaign"], order_by="creation asc", page_length=20)
    elif step.key == "review":
        item["prospects"] = frappe.get_list(
            "Sales Prospect", filters={"company": company, "review_status": "Pending",
                                       "qualification_status": ["in", ["Qualified", "Needs Review"]]},
            fields=["name", "business_name", "city", "website", "fit_score", "deal_probability",
                    "identity_confidence", "qualification_status", "ai_triage_verdict", "ai_triage_confidence",
                    "ai_triage_reason", "ai_business_type"],
            order_by="deal_probability desc, fit_score desc", page_length=12)
        found = ai_suggestions(company)
        item["ai_counts"] = {"approve": len(found["approve"]), "reject": len(found["reject"])}
    elif step.key == "followups":
        leads = frappe.get_all("Sales Prospect", filters={"company": company, "crm_lead": ["is", "set"]},
                               fields=["crm_lead", "business_name"])
        names = {row.crm_lead: row.business_name for row in leads}
        item["tasks"] = [{**task, "business": names.get(task.reference_docname)} for task in frappe.get_all(
            "CRM Task", filters={"reference_doctype": "CRM Lead", "reference_docname": ["in", list(names) or [""]],
                                 "status": ["in", ["Backlog", "Todo", "In Progress"]]},
            fields=["name", "title", "priority", "due_date", "reference_docname"], limit=10)]
        # Calls for leads not yet in the CRM are ToDos on the prospect (live test: they were not listed).
        todos = frappe.get_all("ToDo", filters={"reference_type": "Sales Prospect", "status": "Open",
                                                "rsa_company": company},
                               fields=["name", "description", "date", "reference_name", "allocated_to"],
                               order_by="date asc", limit=15)
        prospects = {row.name: row for row in frappe.get_all(
            "Sales Prospect", filters={"name": ["in", [t.reference_name for t in todos] or [""]]},
            fields=["name", "business_name", "phone"])}
        # Only a Call Task step's tasks are calls (reply follow-ups are tasks too); CRM task names are numbers.
        events = frappe.get_all("Sales Communication Event", filters={
            "event_type": "task_created", "company": company,
            "provider_message_id": ["in", [str(t.name) for t in todos] + [str(t["name"]) for t in item["tasks"]]
                                    or [""]]}, fields=["provider_message_id", "message"])
        call_messages = set(frappe.get_all("Sales Outreach Message", filters={
            "name": ["in", [e.message for e in events] or [""]], "channel": "Call Task"}, pluck="name"))
        calls = {str(e.provider_message_id) for e in events if e.message in call_messages}
        for task in item["tasks"]:
            task["is_call"] = str(task["name"]) in calls
        item["todos"] = [{
            "name": t.name, "due_date": t.date, "assignee": t.allocated_to, "prospect": t.reference_name,
            "is_call": str(t.name) in calls,
            "business": (prospects.get(t.reference_name) or {}).get("business_name"),
            "phone": (prospects.get(t.reference_name) or {}).get("phone"),
            "title": frappe.utils.strip_html(t.description or "").split("\n")[0][:140],
            "script": frappe.utils.strip_html((t.description or "").replace("<br>", "\n"))[:3000],
        } for t in todos]
    return item


@frappe.whitelist()
def onboard(website: str | None = None, note: str | None = None) -> str:
    from reckon_sales_agent.agents.onboarding import start

    _require_manager()
    company = current_company()
    assert_entitled(company)
    return start(company, website or "", note or "")


@frappe.whitelist()
def set_autopilot(data) -> dict:
    """Turn autopilot on or off; turning it on records who agreed to what the agents may do alone."""
    from reckon_sales_agent.agents.orchestrator import enqueue_run

    _require_manager()
    data = _args(data)
    company = current_company()
    settings = get_settings(company)
    enable = bool(data.get("enabled"))
    if enable and not settings.get("autopilot_enabled") and not data.get("consent"):
        frappe.throw(_("Confirm what the agents may do on their own first."))
    if "weekly_leads" in data:
        settings.autopilot_weekly_leads = max(5, min(int(data["weekly_leads"] or 50), 1000))
    if "min_prospects" in data:
        settings.autopilot_campaign_min_prospects = max(1, min(int(data["min_prospects"] or 5), 200))
    if "min_fit" in data:
        settings.auto_approve_min_fit = max(0, min(float(data["min_fit"] or 0), 100))
    elif enable and not settings.get("autopilot_enabled") and float(settings.auto_approve_min_fit or 0) == 75:
        # Live test: the old default (75) sat above the qualify threshold, so autopilot never approved anyone.
        settings.auto_approve_min_fit = float(frappe.db.get_value(
            "Sales Qualification Profile", {"company": company}, "qualify_threshold", order_by="creation asc") or 60)
    if "daily_digest" in data:
        settings.daily_digest = 1 if data["daily_digest"] else 0
    if "digest_recipients" in data:
        settings.digest_recipients = "\n".join(
            line.strip() for line in str(data["digest_recipients"] or "").replace(",", "\n").splitlines()
            if line.strip())[:2000] or None
    if "task_assignee" in data:
        user = (data["task_assignee"] or "").strip()
        if user and not frappe.db.get_value("User", user, "enabled"):
            frappe.throw(_("No active user {0}.").format(frappe.utils.escape_html(user)))
        settings.task_assignee = user or None
    if "ai_triage" in data:
        settings.autopilot_ai_triage = 1 if data["ai_triage"] else 0
    if "auto_segments" in data:
        settings.autopilot_auto_segments = 1 if data["auto_segments"] else 0
    settings.autopilot_enabled = 1 if enable else 0
    if enable:
        settings.auto_approve_enabled = 1  # strong leads by the Company's own thresholds
        settings.autopilot_consent_by = frappe.session.user
    settings.save()
    log_activity(company, "autopilot_on" if enable else "autopilot_off", settings,
                 _("Agents may research, find, score and draft; launching and sending stay with a person.")
                 if enable else "", agent="Governance")
    if enable:
        assert_entitled(company)
        enqueue_run(company, "switched on")
    return {"enabled": enable}


@frappe.whitelist()
def run_now() -> None:
    from reckon_sales_agent.agents.orchestrator import enqueue_run

    _require_manager()
    company = current_company()
    assert_entitled(company)
    enqueue_run(company, "run now")


@frappe.whitelist()
def act(action: str, args=None):
    """One click from the inbox. Approvals reuse the checked API paths; agent steps run in the background."""
    from reckon_sales_agent import api
    from reckon_sales_agent.agents.orchestrator import DOERS, enqueue_step

    args = _args(args)
    company = current_company()
    if action in DOERS:
        _require_manager()
        assert_entitled(company)
        ref = {k: str(v) for k, v in args.items() if k in ("brief", "discovery", "campaign")}
        ref.update({k: int(v or 0) for k, v in args.items() if k in ("count", "with_email")})
        enqueue_step(company, action, ref)
        return "queued"
    if action == "approve_segments":
        from reckon_sales_agent.research.market import approve

        _require_manager()
        doc = get_tenant_doc("Sales Market Brief", args.get("brief"), "write")
        keep = [str(k) for k in args.get("keep") or []]
        if not keep:
            frappe.throw(_("Keep at least one segment."))
        created = approve(doc, keep)
        _nudge(company)
        return created
    if action == "approve_campaign":
        return api.approve_campaign(args.get("campaign"), int(args.get("acknowledge_issues") or 0))
    if action == "pause_campaign":
        return api.pause_campaign(args.get("campaign"))
    if action == "approve_messages":
        return api.approve_messages(json.dumps([str(m) for m in args.get("messages") or []]))
    if action == "send_digest":
        from reckon_sales_agent.agents.digest import send_company

        # A preview of today's digest for the person asking (managers get theirs, salespeople their calls).
        return send_company(company, only_user=frappe.session.user, force=True, as_manager=_can_manage())
    if action == "call_outcome":
        from reckon_sales_agent.campaigns.calls import OUTCOMES, call_message, record_call_outcome

        doctype = args.get("doctype") if args.get("doctype") in ("ToDo", "CRM Task") else None
        task, outcome = str(args.get("task") or ""), str(args.get("outcome") or "")
        message = call_message(task)
        if not doctype or outcome not in OUTCOMES or not message:
            frappe.throw(_("Unknown call task or outcome."))
        get_tenant_doc("Sales Outreach Message", message, "read")  # the call belongs to the user's Company
        frappe.get_doc(doctype, task).check_permission("write")
        return record_call_outcome(doctype, task, outcome, str(args.get("note") or "")[:500],
                                   args.get("callback_on") or None)
    if action == "task_done":
        todo = frappe.get_doc("ToDo", str(args.get("todo")))
        if todo.reference_type != "Sales Prospect" or todo.get("rsa_company") != company:
            frappe.throw(_("Not one of your Company's tasks."), frappe.PermissionError)
        todo.check_permission("write")
        todo.db_set("status", "Closed")
        log_activity(company, "call_task_done", get_tenant_doc("Sales Prospect", todo.reference_name, "read"),
                     _("Marked done in Agent Studio"), agent="Engagement")
        return "closed"
    if action == "accept_ai":
        return _accept_ai(company)
    if action == "review":
        if args.get("decision") not in ("approve", "reject"):
            frappe.throw(_("Unknown decision."))
        count = api.review_prospects(json.dumps([str(p) for p in args.get("prospects") or []]), args["decision"],
                                     _("Decided in Agent Studio"))
        _nudge(company)
        return count
    frappe.throw(_("Unknown action."))


def ai_suggestions(company: str) -> dict:
    """Pending leads the AI leaned on either way (verdicts under the autopilot's confidence bar included)."""
    rows = frappe.get_all("Sales Prospect", filters={"company": company, "review_status": "Pending",
                                                     "ai_triage_verdict": ["in", ["approve", "reject"]]},
                          fields=["name", "ai_triage_verdict"], limit=2000)
    return {verdict: [r.name for r in rows if r.ai_triage_verdict == verdict] for verdict in ("approve", "reject")}


def _accept_ai(company: str) -> dict:
    """A person accepts every AI lean in one click; unsure leads stay. Same path as a manual review."""
    from reckon_sales_agent import api

    api._require_approver()
    found = ai_suggestions(company)
    note = _("Accepted the AI's suggestion in Agent Studio")
    for decision, names in found.items():
        for start in range(0, len(names), 200):  # review_prospects takes at most 200 at a time
            api.review_prospects(json.dumps(names[start:start + 200]), decision, note)
    _nudge(company)
    return {"approved": len(found["approve"]), "rejected": len(found["reject"])}


def _nudge(company: str) -> None:
    """After a person decides, let the autopilot carry on at once instead of at the next hour."""
    from reckon_sales_agent.agents.orchestrator import enqueue_run

    if get_settings(company).get("autopilot_enabled"):
        enqueue_run(company, "after your decision")


def _ai_label(company: str) -> str:
    """Which AI this Company uses, e.g. "OpenAI · gpt-x" (no keys or addresses)."""
    from reckon_sales_agent.providers.factory import ai_setup

    try:
        setup = ai_setup(company)
    except Exception:
        return ""
    return " · ".join(part for part in (setup["label"], setup["model"]) if part)

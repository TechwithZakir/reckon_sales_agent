"""Automations on the Frappe side: enrol people, move each one through the flow, and keep the safety checks of campaigns.

How it fits together
* An automation owns a hidden Sales Campaign. Its steps are the flow's send steps, so approval, suppression, consent,
  pacing, the sending window, the daily limit, tracking and reporting are exactly those of a campaign. A message step
  writes a draft through ``campaigns.engine.draft_message``; the run then waits until that message is sent.
* A person's journey is a Sales Automation Run: where they are, when they are next checked, and the steps taken. Waiting
  runs are picked up by a scheduled job; a sent message wakes its run at once.
* Switching an automation on is a person's decision (it is the campaign approval). Changing the flow switches it off.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import frappe
from frappe import _
from frappe.utils import add_to_date, get_datetime, now_datetime

from reckon_sales_agent.automation import flow as fl
from reckon_sales_agent.campaigns import tags as tag_rules
from reckon_sales_agent.usage import NotEntitled, assert_entitled, get_settings, log_activity

MAX_STEPS = 40  # steps one person can take in one pass (the flow is acyclic, so this is only a safety net)
TICK_LIMIT = 300
REPLY_EVENTS = ("replied", "positive_reply", "meeting_requested")
EVENT_TYPES = {"opened": ("opened",), "clicked": ("clicked",), "replied": REPLY_EVENTS}
LIVE = ("Active", "Waiting")


def flow_of(auto) -> dict:
    try:
        return fl.normalize(json.loads(auto.flow or "{}"))
    except ValueError:
        return fl.new_flow()


def template_status(company: str):
    def lookup(name):
        row = frappe.db.get_value("Sales Message Template", {"name": name, "company": company}, ["channel", "status"])
        return tuple(row) if row else None

    return lookup


# Triggers ------------------------------------------------------------------


def _trigger_matches(trigger: dict, event: str, ctx: dict) -> bool:
    if event == "signup":
        return not trigger.get("form") or trigger["form"] == ctx.get("form")
    if event == "tag_added":
        return bool(trigger.get("tag")) and trigger["tag"] == tag_rules.clean(ctx.get("tag"))
    if event == "deal_stage":
        return not trigger.get("status") or trigger["status"].lower() == str(ctx.get("status") or "").lower()
    return event == "reply_received"


def fire(company: str, event: str, prospect: str, **ctx) -> int:
    """An event happened to a person: start every active automation of the Company that begins on it. Returns how many."""
    started = 0
    for name in frappe.get_all("Sales Automation", filters={"company": company, "status": "Active"}, pluck="name"):
        auto = frappe.get_doc("Sales Automation", name)
        flow = flow_of(auto)
        trigger = flow["nodes"][flow["start"]]["config"]
        if trigger["event"] == event and _trigger_matches(trigger, event, ctx):
            if enroll(auto, prospect, ctx.get("source") or event, reenter=trigger.get("reenter")):
                started += 1
    return started


def _eligible_person(company: str, prospect: str) -> str:
    """'' when the person may be enrolled, else why not."""
    from reckon_sales_agent.campaigns.suppression import is_suppressed

    row = frappe.db.get_value("Sales Prospect", prospect, ["company", "review_status", "do_not_contact", "email", "phone"], as_dict=True)
    if not row or row.company != company:
        return "unknown person"
    if row.review_status != "Approved":
        return "not approved"
    if row.do_not_contact or is_suppressed(company, email=row.email or None, phone=row.phone or None):
        return "opted out"
    return ""


def enroll(auto, prospect: str, source: str = "", reenter: bool = False) -> str | None:
    """Put one person into the automation (once, unless it allows re-entry after the last run has ended)."""
    if auto.status != "Active" or _eligible_person(auto.company, prospect):
        return None
    if reenter:
        if frappe.db.exists("Sales Automation Run", {"automation": auto.name, "prospect": prospect, "status": ["in", list(LIVE)]}):
            return None
        key = f"{auto.name}:{prospect}:{now_datetime().strftime('%Y%m%d%H%M%S')}"
    else:
        key = f"{auto.name}:{prospect}"
        if frappe.db.exists("Sales Automation Run", {"idempotency_key": key}):
            return None
    flow = flow_of(auto)
    now = now_datetime()
    run = frappe.get_doc({
        "doctype": "Sales Automation Run", "company": auto.company, "automation": auto.name, "prospect": prospect, "status": "Active",
        "current_node": flow["start"], "node_entered_on": now, "started_on": now, "source": (source or "")[:140],
        "idempotency_key": key, "path": json.dumps([{"node": flow["start"], "at": str(now)}]),
    }).insert(ignore_permissions=True)
    frappe.enqueue("reckon_sales_agent.automation.engine.advance_run", queue="short", enqueue_after_commit=True, run_name=run.name)
    return run.name


def enroll_many(auto, prospects: list[str], source: str = "manual") -> dict:
    counts = {"enrolled": 0, "skipped": 0}
    for name in prospects:
        counts["enrolled" if enroll(auto, name, source) else "skipped"] += 1
    return counts


# Moving people along -------------------------------------------------------


def _finish(run, status: str, reason: str) -> None:
    run.db_set({"status": status, "stop_reason": reason[:140], "finished_on": now_datetime(), "wake_at": None, "waiting_message": None})
    if status == "Completed":
        from reckon_sales_agent.campaigns.webhook_service import emit_person

        emit_person(run.company, "automation_completed", run.prospect, automation=run.automation, reason=reason[:140])
    if run.get("member"):
        member = frappe.db.get_value("Sales Campaign Member", run.member, ["status", "campaign"], as_dict=True)
        if member and member.status == "Active":
            frappe.db.set_value("Sales Campaign Member", run.member, {"status": "Completed", "stop_reason": "automation ended"})
        if member:
            from reckon_sales_agent.campaigns.engine import _refresh_metrics

            _refresh_metrics(member.campaign)


def _stop_reason(run, auto, prospect) -> str:
    from reckon_sales_agent.campaigns.suppression import is_suppressed

    if prospect.do_not_contact or is_suppressed(run.company, email=prospect.email or None, phone=prospect.phone or None):
        return "opted out"
    if run.get("member"):
        member = frappe.db.get_value("Sales Campaign Member", run.member, ["status", "stop_reason"], as_dict=True)
        if member and member.status == "Stopped" and (member.stop_reason != "replied" or auto.stop_on_reply):
            return member.stop_reason or "stopped"
    return ""


def _ensure_member(run, auto, prospect):
    if run.get("member"):
        return frappe.get_doc("Sales Campaign Member", run.member)
    key = f"{auto.campaign}:{run.prospect}"
    name = frappe.db.get_value("Sales Campaign Member", {"idempotency_key": key})
    if name:
        member = frappe.get_doc("Sales Campaign Member", name)
        if member.status != "Active":
            member.db_set({"status": "Active", "stop_reason": None})
    else:
        member = frappe.get_doc({
            "doctype": "Sales Campaign Member", "company": run.company, "campaign": auto.campaign, "prospect": run.prospect,
            "crm_lead": prospect.crm_lead, "email": prospect.email, "phone": prospect.phone, "status": "Active",
            "eligibility_reason": "Started by an automation.", "idempotency_key": key,
            "unsubscribe_token": frappe.generate_hash(length=32), "next_action_on": None,
        }).insert(ignore_permissions=True)
    run.db_set("member", member.name)
    run.member = member.name
    return member


def _record(path: list, node_id: str, **extra) -> None:
    path.append({"node": node_id, "at": str(now_datetime()), **extra})


def _event_happened(messages: list[str], check: str) -> bool:
    if not messages:
        return False
    return bool(frappe.db.count("Sales Communication Event", {"message": ["in", messages], "event_type": ["in", list(EVENT_TYPES[check])]}))


def _messages_for(run, path: list, ref: str) -> list[str]:
    if ref != "any":
        return [p["message"] for p in path if p.get("node") == ref and p.get("message")][-1:]
    return [p["message"] for p in path if p.get("message")]


def advance_run(run_name: str) -> None:
    """Move one person forward until they must wait (for time, a message or an event) or the flow ends."""
    run = frappe.get_doc("Sales Automation Run", run_name)
    if run.status not in LIVE:
        return
    auto = frappe.get_doc("Sales Automation", run.automation)
    if auto.status != "Active":
        return  # paused: the person waits where they are
    try:
        assert_entitled(run.company)
    except NotEntitled:
        return
    settings = get_settings(run.company)
    if settings.kill_switch:
        return
    flow = flow_of(auto)
    prospect = frappe.get_doc("Sales Prospect", run.prospect)
    path = json.loads(run.path or "[]")
    for _step in range(MAX_STEPS):
        node = flow["nodes"].get(run.current_node)
        if not node:
            return _finish(run, "Completed", "the flow changed")
        reason = _stop_reason(run, auto, prospect)
        if reason:
            run.db_set("path", json.dumps(path))
            return _finish(run, "Stopped", reason)
        action, value = _execute(run, auto, flow, node, prospect, settings, path)
        if action == "wait":
            run.db_set({"status": "Waiting", "wake_at": value, "path": json.dumps(path)})
            return None
        if action == "stop":
            run.db_set("path", json.dumps(path))
            return _finish(run, "Stopped" if value.startswith("message") else "Completed", value)
        if value is None:  # no exit: the person has finished
            run.db_set("path", json.dumps(path))
            return _finish(run, "Completed", "reached the end")
        run.db_set({"current_node": value, "node_entered_on": now_datetime(), "status": "Active", "wake_at": None,
                    "waiting_message": None})
        run.current_node = value
        run.waiting_message = None
        run.node_entered_on = now_datetime()
    run.db_set("path", json.dumps(path))
    return None


def _execute(run, auto, flow, node, prospect, settings, path):
    """Run the person's current step. Returns ('go', next step id or None), ('wait', when) or ('stop', reason)."""
    kind, cfg, node_id = node["type"], node["config"], run.current_node
    now = now_datetime()
    if kind == "trigger":
        return "go", node.get("next")
    if kind == "send":
        return _send(run, auto, flow, node, prospect, settings, path)
    if kind == "wait":
        due = add_to_date(get_datetime(run.node_entered_on), minutes=fl.wait_minutes(cfg))
        if now >= due:
            _record(path, node_id, result="waited")
            return "go", node.get("next")
        return "wait", due
    if kind == "condition":
        return _condition(run, node, prospect, path, now)
    if kind == "action":
        done = _action(run, cfg, prospect, settings)
        _record(path, node_id, result=done)
        return ("stop", "ended by the flow") if cfg["do"] == "stop" else ("go", node.get("next"))
    if kind == "webhook":
        _record(path, node_id, result=_webhook(run, auto, cfg, prospect))
        return "go", node.get("next")
    return "go", node.get("next")


def _send(run, auto, flow, node, prospect, settings, path):
    from reckon_sales_agent.campaigns.engine import draft_message
    from reckon_sales_agent.providers.channels import reachability

    node_id = run.current_node
    if run.waiting_message:
        status = frappe.db.get_value("Sales Outreach Message", run.waiting_message, "status")
        if status in ("Sent", "Dry Run"):
            return "go", node.get("next")
        if status in ("Cancelled", "Failed", None):
            return "stop", f"message {(status or 'removed').lower()}"
        return "wait", None  # still a draft or waiting for its turn: checked again on the next pass
    channel = frappe.db.get_value("Sales Message Template", node["config"].get("template"), "channel")
    reachable, why, _recipient = reachability(channel or "Email", prospect, settings)
    if not reachable:
        _record(path, node_id, result=f"skipped: {why}")
        return "go", node.get("next")  # like a campaign: a step the person cannot receive is skipped
    member = _ensure_member(run, auto, prospect)
    campaign = frappe.get_doc("Sales Campaign", auto.campaign)
    number = fl.send_nodes(flow).index(node_id) + 1
    step = next((s for s in campaign.steps if s.step_no == number), None)
    if not step:
        return "stop", "message step missing: switch the automation on again"
    message = draft_message(campaign, member, step, f"{run.name}:{node_id}")
    run.db_set("waiting_message", message)
    run.waiting_message = message
    _record(path, node_id, message=message, result="drafted")
    return "wait", None


def _condition(run, node, prospect, path, now):
    cfg, node_id = node["config"], run.current_node
    check = cfg["check"]
    if check in fl.EVENT_CHECKS:
        if _event_happened(_messages_for(run, path, cfg["ref"]), check):
            _record(path, node_id, result="yes")
            return "go", node.get("yes")
        window_end = add_to_date(get_datetime(run.node_entered_on), days=cfg.get("wait_days") or 0)
        if cfg.get("wait_days") and now < window_end:
            return "wait", window_end
        _record(path, node_id, result="no")
        return "go", node.get("no")
    if check == "tag":
        answer = tag_rules.has(prospect.get("tags"), cfg.get("tag"))
    elif check == "confirmed":
        answer = prospect.get("optin_status") != "Unconfirmed"
    else:
        from reckon_sales_agent.campaigns.segment_service import person_in

        answer = person_in(run.company, run.prospect, cfg.get("segment"))
    _record(path, node_id, result="yes" if answer else "no")
    return "go", node.get("yes") if answer else node.get("no")


def _action(run, cfg, prospect, settings) -> str:
    from reckon_sales_agent.campaigns.tag_service import add_tags, remove_tags

    do, value = cfg["do"], cfg.get("value")
    if do == "add_tag":
        return "tag added" if add_tags(run.company, run.prospect, value, f"automation {run.automation}") else "tag already there"
    if do == "remove_tag":
        remove_tags(run.prospect, value)
        return "tag removed"
    if do in ("set_city", "set_industry"):
        frappe.db.set_value("Sales Prospect", run.prospect, "city" if do == "set_city" else "industry", value)
        return "field set"
    if do in ("create_task", "notify"):
        from reckon_sales_agent.providers.channels import create_task

        title = value or "Follow up"
        label = prospect.contact_name or prospect.business_name
        create_task(run.prospect, f"{title}: {label}", f"Created by the automation '{run.automation}'.", settings)
        return "task created"
    return "stopped"


def _webhook(run, auto, cfg, prospect) -> str:
    """Call the address with the person's details, signed when the automation has a secret. A failed call never stops the
    person: it is written on their journey."""
    import requests

    from reckon_sales_agent.research.url_safety import validate_url

    url = cfg.get("url")
    try:
        validate_url(url)  # public addresses only: never the server's own network
        body = json.dumps({
            "automation": auto.name, "run": run.name, "at": str(now_datetime()),
            "person": {"id": prospect.name, "email": prospect.email, "phone": prospect.phone, "name": prospect.contact_name or prospect.business_name,
                       "tags": tag_rules.normalize(prospect.get("tags"))}}, ensure_ascii=False).encode()
        headers = {"Content-Type": "application/json"}
        secret = auto.get_password("webhook_secret", raise_exception=False)
        if secret:
            headers["X-Reckon-Signature"] = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        response = requests.post(url, data=body, headers=headers, timeout=10, allow_redirects=False)
        return f"webhook {response.status_code}"
    except Exception as exc:
        return f"webhook failed: {type(exc).__name__}"[:140]


# Scheduled work and hooks --------------------------------------------------


def run_due() -> None:
    """Every few minutes: people whose wait is over, and people waiting for a message to be sent."""
    now = now_datetime()
    names = frappe.get_all("Sales Automation Run", filters={"status": "Waiting"}, or_filters=[["wake_at", "<=", now], ["wake_at", "is", "not set"]],
                           pluck="name", order_by="modified asc", limit=TICK_LIMIT)
    for name in names:
        try:
            advance_run(name)
            frappe.db.commit()
        except Exception:
            frappe.db.rollback()
            frappe.log_error(title="Sales Agent automation step failed", reference_doctype="Sales Automation Run", reference_name=name)
    try:
        poll_segments()
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        frappe.log_error(title="Sales Agent automation segment check failed")


def poll_segments() -> int:
    """Automations that begin when someone joins a segment: enrol the people now in it who have not been enrolled."""
    from reckon_sales_agent.campaigns.segment_service import resolve

    enrolled = 0
    for name in frappe.get_all("Sales Automation", filters={"status": "Active"}, pluck="name"):
        auto = frappe.get_doc("Sales Automation", name)
        trigger = flow_of(auto)["nodes"][flow_of(auto)["start"]]["config"]
        if trigger["event"] != "segment_joined" or not trigger.get("segment"):
            continue
        key = f"rsa_auto_seg:{auto.name}"
        if frappe.cache.get_value(key):
            continue  # looked at in the last half hour
        frappe.cache.set_value(key, 1, expires_in_sec=1800)
        segment = frappe.db.get_value("Sales Segment", {"company": auto.company, "name": trigger["segment"]}) or \
            frappe.db.get_value("Sales Segment", {"company": auto.company, "segment_name": trigger["segment"]})
        if not segment:
            continue
        for person in resolve(frappe.get_doc("Sales Segment", segment))[:TICK_LIMIT]:
            if enroll(auto, person["name"], f"segment {trigger['segment']}"):
                enrolled += 1
    return enrolled


def message_sent(member) -> None:
    """A message of an automation was sent: wake its run now instead of waiting for the next pass."""
    run = frappe.db.get_value("Sales Automation Run", {"member": member.name, "status": "Waiting"}, "name")
    if run:
        frappe.enqueue("reckon_sales_agent.automation.engine.advance_run", queue="short", enqueue_after_commit=True, run_name=run)


def on_deal_update(doc, method=None) -> None:
    """``CRM Deal.on_update``: a deal changed stage, which starts automations that begin on a stage."""
    if not doc.get("lead") or not doc.has_value_changed("status"):
        return
    prospect = frappe.db.get_value("Sales Prospect", {"crm_lead": doc.lead}, ["name", "company"], as_dict=True)
    if prospect:
        try:
            fire(prospect.company, "deal_stage", prospect.name, status=doc.status, source=f"deal {doc.name}")
        except Exception:
            frappe.log_error(title="Sales Agent automation trigger failed", message=f"deal {doc.name}")


# Switching on --------------------------------------------------------------


def sync_campaign(auto) -> str | None:
    """The hidden campaign that carries the automation's messages: one step per send step, in reading order. A flow with no
    message step needs none (a campaign must have at least one step)."""
    flow = flow_of(auto)
    steps = [{"step_no": number, "message_template": flow["nodes"][node_id]["config"]["template"], "delay_days": 0}
             for number, node_id in enumerate(fl.send_nodes(flow), start=1)]
    if not steps:
        return None
    if auto.campaign and frappe.db.exists("Sales Campaign", auto.campaign):
        campaign = frappe.get_doc("Sales Campaign", auto.campaign)
        campaign.set("steps", steps)
        campaign.flags.ignore_permissions = True
        campaign.save()
        return campaign.name
    campaign = frappe.get_doc({"doctype": "Sales Campaign", "company": auto.company, "campaign_name": f"Automation: {auto.automation_name}"[:140],
                               "automation": auto.name, "status": "Draft", "language": "English", "daily_limit": 1000, "steps": steps})
    campaign.flags.ignore_permissions = True
    campaign.insert(ignore_permissions=True)
    frappe.db.set_value("Sales Automation", auto.name, "campaign", campaign.name)
    auto.campaign = campaign.name
    return campaign.name


def activate(auto, user: str, acknowledge_issues: bool = False) -> dict:
    """Switch the automation on. Everything that must be right is checked first, in plain words."""
    from reckon_sales_agent.agents.approvals import campaign_payload, fingerprint

    assert_entitled(auto.company)
    flow = flow_of(auto)
    problems = fl.issues(flow, template_status(auto.company))
    if problems:
        frappe.throw("<br>".join(frappe.utils.escape_html(p["message"]) for p in problems[:8]), title=_("Fix these first"))
    campaign_name = sync_campaign(auto)
    now = now_datetime()
    if campaign_name:
        campaign = frappe.get_doc("Sales Campaign", campaign_name)
        if campaign.get("content_status") == "Needs review" and not acknowledge_issues:
            frappe.throw(_("The content check found issues:") + "<br>" + "<br>".join(
                frappe.utils.escape_html(line) for line in (campaign.content_issues or "").splitlines()[:15]), title=_("Review the content first"))
        campaign.db_set({"status": "Active", "approved_by": user, "approved_on": now,
                         "approval_fingerprint": fingerprint(campaign_payload(campaign)), "approved_audience_size": 0})
    auto.db_set({"status": "Active", "activated_by": user, "activated_on": now})
    auto.status = "Active"
    log_activity(auto.company, "automation_switched_on", auto, f"{len(fl.send_nodes(flow))} message steps", agent="Governance",
                 policy_outcome="approved by a person")
    return {"status": "Active", "campaign": campaign_name}


def pause(auto) -> None:
    auto.db_set("status", "Paused")
    auto.status = "Paused"
    log_activity(auto.company, "automation_paused", auto)


# Numbers -------------------------------------------------------------------


def stats(auto) -> dict:
    """How many people reached each step, where they are now, and how the runs ended."""
    rows = frappe.get_all("Sales Automation Run", filters={"automation": auto.name},
                          fields=["status", "current_node", "path", "stop_reason"], limit=20000)
    by_status: dict[str, int] = {}
    reached: dict[str, int] = {}
    here: dict[str, int] = {}
    reasons: dict[str, int] = {}
    for row in rows:
        by_status[row.status] = by_status.get(row.status, 0) + 1
        if row.status in LIVE:
            here[row.current_node] = here.get(row.current_node, 0) + 1
        if row.stop_reason and row.status in ("Stopped", "Completed"):
            reasons[row.stop_reason] = reasons.get(row.stop_reason, 0) + 1
        try:
            seen = {p["node"] for p in json.loads(row.path or "[]") if isinstance(p, dict)}
        except ValueError:
            seen = set()
        for node_id in seen:
            reached[node_id] = reached.get(node_id, 0) + 1
    return {"total": len(rows), "by_status": by_status, "reached": reached, "here": here, "reasons": reasons}

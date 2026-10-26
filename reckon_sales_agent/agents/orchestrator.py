"""Orchestrator: moves the sales pipeline forward on its own, stopping only where a person must decide.

Each run reads a snapshot of the Company's pipeline and plans one step per
agent: "do" steps run now (within the autonomy matrix), "ask" steps go to the
Agent Studio's Needs-you inbox, "wait" steps are work already in progress.

    Research   website -> business profile -> market brief -> segments -> discovery -> scoring
    Content    a draft pilot campaign, written by AI, for each segment with enough approved leads
    Governance launching a campaign and approving outbound messages stay with a person
    Engagement replies, answers and follow-up tasks (already event driven)
    Analytics  pilot measurement and scale / stop recommendations

``plan`` is pure (no Frappe) so the decisions are unit-tested; ``run`` does them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

DO, ASK, WAIT = "do", "ask", "wait"
BRIEF_MAX_AGE_DAYS = 30
PILOT_CHECK_HOURS = 24


@dataclass
class Step:
    agent: str
    key: str
    kind: str
    title: str
    detail: str = ""
    ref: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


def plan(state: dict) -> list[Step]:
    """The next steps for a pipeline snapshot. ``state`` holds counts and names only, never contact data."""
    auto = bool(state.get("autopilot"))
    steps: list[Step] = []
    add = steps.append

    # Research: who we are, which market, which segments.
    brief = state.get("brief_status")
    if not state.get("has_profile"):
        add(Step("Research", "onboard", ASK, "Tell the agent your website",
                 "One line is enough: the agent reads your site and fills in your business profile."))
    elif state.get("onboarding"):
        add(Step("Research", "onboard", WAIT, "Reading your website"))
    elif brief in (None, "Failed") or (brief == "Approved" and state.get("brief_age_days", 0) > BRIEF_MAX_AGE_DAYS):
        add(Step("Research", "research_market", DO if auto or brief is None else ASK, "Research the market",
                 "Web research on your industries, buyers and competitors."
                 if brief != "Failed" else "The last market research failed; try again."))
    elif brief == "Researching":
        add(Step("Research", "research_market", WAIT, "Researching your market"))
    elif brief == "Ready":
        add(Step("Research", "approve_segments", DO if auto and state.get("auto_segments") else ASK,
                 "Choose the segments to target", "The agent proposed customer segments from its research.",
                 {"brief": state.get("brief")}))

    # Discovery: find leads for every chosen segment.
    if brief == "Approved":
        if not state.get("sources_ready"):
            add(Step("Research", "sources", ASK, "No lead source is switched on",
                     "Ask your provider to enable Brave Search or another lead source."))
        elif state.get("profiles_without_discovery"):
            add(Step("Research", "start_discovery", DO if auto else ASK, "Find leads for the new segments",
                     f"{state['profiles_without_discovery']} segment(s) have no lead search yet."))
        elif auto and state.get("unscheduled_searches"):
            # Live test: the brief's lead searches ran once and never again, so the pipeline dried up.
            add(Step("Research", "keep_finding", DO, "Keep finding leads every week",
                     f"{state['unscheduled_searches']} segment search(es) were not repeating."))
        if state.get("running_jobs"):
            add(Step("Research", "discovery", WAIT, "Finding and researching leads",
                     f"{state['running_jobs']} search job(s) running."))

    # Review: clear misfits are set aside and strong leads approved by policy; the rest go to a person.
    set_aside = state.get("pending_foreign", 0) + state.get("pending_weak", 0) + state.get("pending_demo", 0)
    if set_aside and auto:
        parts = [f"{state[key]} {label}" for key, label in (
            ("pending_foreign", "in another country"), ("pending_weak", "scored below your review threshold"),
            ("pending_demo", "from the demo source")) if state.get(key)]
        add(Step("Research", "auto_triage", DO, "Set aside weak and out-of-market leads", ", ".join(parts) + "."))
    if state.get("pending_untriaged") and state.get("ai"):
        if auto and state.get("ai_triage"):
            add(Step("Research", "ai_triage", DO, "Judge borderline leads with AI",
                     f"{state['pending_untriaged']} lead(s) not yet judged; clear-cut ones are decided, "
                     "unsure ones come to you with the agent's reasoning."))
        elif not auto:
            add(Step("Research", "ai_triage", ASK, "Let the agent pre-sort your leads",
                     f"The AI judges {state['pending_untriaged']} borderline lead(s) and explains each verdict."))
    if state.get("lessons"):
        add(Step("Research", "learn_targeting", DO if auto else ASK, "Sharpen the lead searches",
                 "; ".join(state["lessons"])[:500]))
    if state.get("missing_email"):
        add(Step("Research", "find_contacts", DO if auto else ASK, "Find emails for approved leads",
                 f"{state['missing_email']} approved lead(s) have a website but no email."))
    if state.get("pending_qualified") and auto and state.get("auto_approve"):
        add(Step("Research", "auto_review", DO, "Approve strong leads",
                 f"{state['pending_qualified']} qualified lead(s) checked against your autopilot rules."))
    # Qualified leads the autopilot rules decline (score under the bar, no contact...) go to a person, not limbo.
    pending_human = state.get("pending_human", 0) + state.get("pending_held", 0) + (
        0 if auto and state.get("auto_approve") else state.get("pending_qualified", 0))
    if auto:
        pending_human = max(0, pending_human - set_aside)
    if pending_human:
        add(Step("Research", "review", ASK, "Review leads", f"{pending_human} lead(s) need your decision."))

    # Content: a draft pilot campaign per segment once it has enough approved leads.
    for segment in state.get("segments_ready") or []:
        if segment.get("count", 0) >= int(state.get("campaign_min_prospects") or 5):
            add(Step("Content", "draft_campaign", DO if auto and state.get("ai") else ASK,
                     f"Write a pilot campaign for {segment['label']}",
                     f"{segment['count']} approved lead(s) are not in any campaign yet "
                     f"({segment.get('with_email', 0)} with email; the rest get a salesperson's call).",
                     {"discovery": segment["discovery"], "count": segment["count"],
                      "with_email": segment.get("with_email", 0)}))

    # Governance: launching and sending are a person's decision.
    for campaign in state.get("campaigns_pending") or []:
        add(Step("Governance", "approve_campaign", ASK, f"Approve campaign: {campaign['label']}",
                 campaign.get("detail", ""), {"campaign": campaign["name"]}))
    if state.get("drafts_waiting"):
        add(Step("Engagement", "approve_drafts", ASK, "Approve messages",
                 f"{state['drafts_waiting']} message(s) are drafted and waiting for approval."))
    if state.get("open_followups"):
        add(Step("Engagement", "followups", ASK, "Answer your leads",
                 f"{state['open_followups']} reply follow-up(s) are waiting for a person."))

    # Analytics: measure pilots and recommend; scaling or stopping is a person's decision.
    for name in state.get("pilots_to_check") or []:
        add(Step("Analytics", "pilot_check", DO, "Measure the pilot", ref={"campaign": name}))
    for campaign in state.get("pilot_verdicts") or []:
        if campaign["verdict"] == "scale":
            add(Step("Analytics", "scale_campaign", ASK, f"Scale up {campaign['label']}",
                     "The pilot beats its hold-out group with confidence.", {"campaign": campaign["name"]}))
        elif campaign["verdict"] == "stop":
            add(Step("Analytics", "pause_campaign", ASK, f"Stop {campaign['label']}",
                     "The pilot does no better than its hold-out group.", {"campaign": campaign["name"]}))
    return steps


def pilot_channels(with_email: int, total: int, whatsapp: bool = False) -> list[str]:
    """The pilot's channel order. Most Bangladeshi distributors list only a phone: then a salesperson's call
    (with an AI script) leads, and email follows for those who have one."""
    channels = ["Email", "Call Task"] if total and with_email * 2 >= total else ["Call Task", "Email"]
    return channels + (["WhatsApp"] if whatsapp else [])


def lane_status(steps: list[Step], agent: str) -> str:
    kinds = {s.kind for s in steps if s.agent == agent}
    return "needs_you" if ASK in kinds else "working" if kinds & {DO, WAIT} else "idle"


def pick_segments(segments: list[dict], limit: int = 3) -> list[str]:
    """Which proposed segments autopilot keeps: the best-priority ones (1 is best), at most ``limit``."""
    ranked = sorted(segments, key=lambda s: (int(s.get("priority") or 5), s.get("idx") or 0))
    best = [s for s in ranked if int(s.get("priority") or 5) <= 2] or ranked[:1]
    return [s["name"] for s in best[:limit]]


# --------------------------------------------------------------------------- Frappe side


def collect_state(company: str) -> dict:
    import frappe
    from frappe.utils import add_to_date, date_diff, now_datetime, nowdate

    from reckon_sales_agent.providers.router import active
    from reckon_sales_agent.research.market import business_profile
    from reckon_sales_agent.usage import get_settings, platform_settings

    settings = get_settings(company)
    platform = platform_settings()
    profile = business_profile(company, create=False)
    state = {
        "autopilot": bool(settings.get("autopilot_enabled")),
        "auto_segments": bool(settings.get("autopilot_auto_segments")),
        "auto_approve": bool(settings.auto_approve_enabled),
        "campaign_min_prospects": settings.get("autopilot_campaign_min_prospects") or 5,
        "ai": bool(platform.get("ai_enabled") and settings.ai_enabled),
        "has_profile": bool(profile and (profile.what_we_sell or profile.products or profile.target_industries)),
        "onboarding": bool(profile and profile.get("onboarding_status") == "Reading website"),
        "sources_ready": bool(active("places") or active("page_context")),
    }
    brief = frappe.db.get_value("Sales Market Brief", profile.latest_brief,
                                ["name", "status", "researched_on", "approved_on"], as_dict=True) \
        if profile and profile.latest_brief else None
    if brief:
        state.update(brief=brief.name, brief_status=brief.status,
                     brief_age_days=date_diff(nowdate(), brief.approved_on or brief.researched_on or nowdate()))
        if brief.status == "Approved":
            targets = frappe.get_all("Sales Market Segment", filters={"parent": brief.name, "include": 1},
                                     pluck="targeting_profile")
            searched = set(frappe.get_all("Sales Discovery Campaign", filters={"company": company,
                                                                               "targeting_profile": ["in", targets]},
                                          pluck="targeting_profile")) if targets else set()
            state["profiles_without_discovery"] = len([t for t in targets if t and t not in searched])
            state["unscheduled_searches"] = len(_unscheduled(company, targets))
    count = lambda doctype, **f: frappe.db.count(doctype, {"company": company, **f})  # noqa: E731
    state["running_jobs"] = count("Sales Discovery Job", status=["in", ["Queued", "Running"]])
    state["pending_qualified"], state["pending_held"] = _split_qualified(company, settings)
    state["pending_human"] = count("Sales Prospect", review_status="Pending", qualification_status="Needs Review")
    foreign = {name for name, _reason in foreign_pending(company)}
    state["pending_foreign"] = len(foreign)
    demo = set(demo_pending(company)) - foreign
    state["pending_demo"] = len(demo)
    state["pending_weak"] = len(set(weak_pending(company)) - foreign - demo)
    from reckon_sales_agent.agents.contacts import missing_email
    from reckon_sales_agent.agents.learning import lessons
    from reckon_sales_agent.agents.triage import untriaged

    state["ai_triage"] = bool(settings.get("autopilot_ai_triage"))
    state["pending_untriaged"] = len(untriaged(company)) if state["ai"] else 0
    state["lessons"] = [
        f"{lesson['label']}: " + ", ".join(filter(None, [
            "skip " + "/".join(lesson["exclude"]) if lesson["exclude"] else "",
            "stop searching " + "/".join(lesson["retire"]) if lesson["retire"] else ""]))
        for lesson in lessons(company)]
    state["missing_email"] = len(missing_email(company))
    state["segments_ready"] = _segments_ready(company)
    state["campaigns_pending"] = [
        {"name": c.name, "label": c.campaign_name,
         "detail": "Content check: " + (c.content_status or "Not checked")}
        for c in frappe.get_all("Sales Campaign", filters={"company": company, "status": "Pending Approval"},
                                fields=["name", "campaign_name", "content_status"], limit=10)]
    state["drafts_waiting"] = count("Sales Outreach Message", status="Draft")
    state["open_followups"] = _open_followups(company)
    since = add_to_date(now_datetime(), hours=-PILOT_CHECK_HOURS)
    pilots = frappe.get_all("Sales Campaign", filters={"company": company, "status": "Active", "pilot_mode": 1},
                            fields=["name", "campaign_name", "pilot_verdict", "pilot_checked_on"], limit=20)
    state["pilots_to_check"] = [p.name for p in pilots if not p.pilot_checked_on or p.pilot_checked_on < since]
    state["pilot_verdicts"] = [{"name": p.name, "label": p.campaign_name, "verdict": p.pilot_verdict}
                               for p in pilots if p.pilot_verdict in ("scale", "stop")]
    return state


def _split_qualified(company: str, settings) -> tuple[int, int]:
    """Pending qualified leads: (the autopilot rules would approve, they would not).

    Live test: a qualified lead under the auto-approve bar was retried every hour and never shown to a person.
    With autopilot's approval off, every qualified lead is a person's decision.
    """
    import frappe
    from frappe.utils import nowdate

    from reckon_sales_agent.autopilot import auto_approval_decision

    pending = frappe.get_all("Sales Prospect", filters={"company": company, "review_status": "Pending",
                                                        "qualification_status": "Qualified"},
                             fields=["review_status", "qualification_status", "do_not_contact", "contactability",
                                     "possible_duplicate_of", "fit_score", "evidence_confidence", "deal_probability",
                                     "email", "phone"], limit=2000)
    if not settings.auto_approve_enabled:
        return len(pending), 0
    approved_today = frappe.db.count("Sales Agent Activity", {"company": company, "action": "prospect_auto_approved",
                                                              "creation": [">=", f"{nowdate()} 00:00:00"]})
    rules = settings.as_dict()
    passing = sum(1 for p in pending if auto_approval_decision(p, rules, approved_today)[0])
    return passing, len(pending) - passing


def review_threshold(company: str) -> float:
    import frappe

    value = frappe.db.get_value("Sales Qualification Profile", {"company": company}, "review_threshold",
                                order_by="creation asc")
    return float(value or 40)


def weak_pending(company: str) -> list[str]:
    """Pending leads whose website was read and still scored below the review threshold.

    Live test: leads with no website or an unreachable one scored 13-16 for lack of evidence, not for being
    misfits (Biorex Healthcare, Islamia Drug House), and were set aside. Only a low score backed by the
    business's own pages counts; the rest go to AI triage, which judges the listing and may say "unsure".
    """
    import frappe

    return frappe.get_all("Sales Prospect", filters={
        "company": company, "review_status": "Pending", "qualification_status": "Needs Review",
        "research_status": "Done", "fit_score": ["<", review_threshold(company)],
    }, pluck="name", limit=2000)


def demo_pending(company: str) -> list[str]:
    """Pending leads from the built-in demo source (made-up businesses on .example sites)."""
    import frappe

    return frappe.get_all("Sales Prospect", filters={"company": company, "review_status": "Pending",
                                                     "source_type": "fixture"}, pluck="name", limit=2000)


def _unscheduled(company: str, targets: list[str]) -> list[str]:
    """The approved segments' lead searches that do not repeat."""
    import frappe

    if not targets:
        return []
    return frappe.get_all("Sales Discovery Campaign", filters={
        "company": company, "targeting_profile": ["in", targets], "status": ["!=", "Cancelled"],
        "schedule": ["is", "not set"]}, pluck="name")


def foreign_pending(company: str) -> list[tuple[str, str]]:
    """Pending leads outside their campaign's market: (prospect, reason). Found before the market filter existed."""
    import frappe

    from reckon_sales_agent.discovery.targeting import foreign_business, market_country

    markets: dict = {}
    found = []
    for row in frappe.get_all("Sales Prospect", filters={"company": company, "review_status": "Pending"},
                              fields=["name", "website", "address", "country", "discovery_campaign"], limit=2000):
        if row.discovery_campaign not in markets:
            target = frappe.db.get_value("Sales Discovery Campaign", row.discovery_campaign, "targeting_profile") \
                if row.discovery_campaign else None
            markets[row.discovery_campaign] = market_country(
                {"locations": frappe.get_all("Sales Target Location", filters={"parent": target},
                                             fields=["country"])} if target else {})
        reason = foreign_business({"website": row.website, "address": row.address, "country": row.country},
                                  markets[row.discovery_campaign])
        if reason:
            found.append((row.name, reason))
    return found


def _segments_ready(company: str) -> list[dict]:
    """Discovery campaigns whose approved, reachable leads are in no sales campaign and have no open campaign."""
    import frappe

    open_for = set(frappe.get_all("Sales Campaign", filters={"company": company,
                                                             "status": ["in", ["Draft", "Pending Approval"]]},
                                  pluck="discovery_campaign"))
    in_campaign = set(frappe.get_all("Sales Campaign Member", filters={"company": company}, pluck="prospect"))
    ready = []
    for disc in frappe.get_all("Sales Discovery Campaign", filters={"company": company},
                               fields=["name", "campaign_name"], limit=50):
        if disc.name in open_for:
            continue
        # Reachable: a business email, or a phone and a CRM lead for a salesperson's call (phone-first pilot).
        rows = frappe.get_all("Sales Prospect", filters={"company": company, "discovery_campaign": disc.name,
                                                         "review_status": "Approved", "do_not_contact": 0},
                              fields=["name", "email", "phone", "crm_lead"])
        free = [r for r in rows if r.name not in in_campaign and (r.email or (r.phone and r.crm_lead))]
        if free:
            ready.append({"discovery": disc.name, "label": disc.campaign_name, "count": len(free),
                          "with_email": sum(1 for r in free if r.email)})
    return ready


def _open_followups(company: str) -> int:
    import frappe

    leads = frappe.get_all("Sales Prospect", filters={"company": company, "crm_lead": ["is", "set"]}, pluck="crm_lead")
    tasks = frappe.db.count("CRM Task", {"reference_doctype": "CRM Lead", "reference_docname": ["in", leads],
                                         "status": ["in", ["Backlog", "Todo", "In Progress"]]}) if leads else 0
    todos = frappe.db.count("ToDo", {"reference_type": "Sales Prospect", "status": "Open", "rsa_company": company})
    return tasks + todos


def run(company: str, trigger: str = "schedule") -> dict:
    """Plan and do this Company's automatic steps. Each step is isolated: one failure never stops the rest."""
    import frappe
    from frappe.utils import now_datetime

    from reckon_sales_agent.usage import log_activity

    steps = plan(collect_state(company))
    done, failed = [], []
    for step in steps:
        if step.kind != DO:
            continue
        try:
            result = DOERS[step.key](company, step)
            frappe.db.commit()
            done.append(f"{step.title}: {result}" if result else step.title)
        except Exception as exc:
            frappe.db.rollback()
            frappe.log_error(title=f"Sales Agent autopilot: {step.key}", reference_doctype="Company",
                             reference_name=company)
            failed.append(f"{step.title}: {str(exc)[:160]}")
    asks = [s.title for s in steps if s.kind == ASK]
    summary = "; ".join(done) or "Nothing to do automatically."
    if failed:
        summary += " Failed: " + "; ".join(failed)
    if asks:
        summary += f" Waiting for you: {len(asks)}."
    frappe.db.set_value("Sales Agent Settings", company, {"autopilot_last_run": now_datetime(),
                                                          "autopilot_summary": summary[:1000]})
    if done or failed or trigger != "schedule":  # a person who pressed "Run agents now" sees the outcome
        log_activity(company, "autopilot_run", None, f"[{trigger}] {summary}", actor_type="agent",
                     agent="Governance", policy_outcome="automatic within the autonomy matrix")
    frappe.db.commit()
    return {"done": done, "failed": failed, "asks": asks}


def run_all() -> None:
    """Hourly: every Company with autopilot on."""
    import frappe

    from reckon_sales_agent.usage import NotEntitled, assert_entitled

    for company in frappe.get_all("Sales Agent Settings", filters={"autopilot_enabled": 1, "enabled": 1},
                                  pluck="company"):
        try:
            assert_entitled(company)
            run(company)
        except NotEntitled:
            frappe.db.rollback()


def run_step(company: str, key: str, ref: dict | None = None) -> None:
    """One automatic step a person started from the Agent Studio (autopilot off, or "do it now")."""
    import frappe

    from reckon_sales_agent.usage import log_activity

    step = Step("Governance", key, DO, key.replace("_", " "), ref=ref or {})
    try:
        result = DOERS[key](company, step)
        log_activity(company, f"autopilot_{key}", None, str(result or "done")[:500], actor_type="agent",
                     policy_outcome="started by a person")
    except Exception as exc:
        frappe.db.rollback()
        frappe.log_error(title=f"Sales Agent step: {key}", reference_doctype="Company", reference_name=company)
        log_activity(company, f"autopilot_{key}_failed", None, str(exc)[:500], actor_type="agent")
    frappe.db.commit()


def enqueue_step(company: str, key: str, ref: dict | None = None) -> None:
    import frappe

    if key not in DOERS:
        frappe.throw(f"Unknown step {key}.")
    frappe.enqueue("reckon_sales_agent.agents.orchestrator.run_step", queue="long", timeout=1800,
                   enqueue_after_commit=True, company=company, key=key, ref=ref or {})


def enqueue_run(company: str, trigger: str = "user") -> None:
    import frappe

    frappe.enqueue("reckon_sales_agent.agents.orchestrator.run", queue="long", timeout=1800,
                   enqueue_after_commit=True, job_id=f"sales-autopilot-{company}", deduplicate=True,
                   company=company, trigger=trigger)


# --------------------------------------------------------------------------- the automatic steps


def _research_market(company: str, step: Step) -> str:
    from reckon_sales_agent.research.market import business_profile, start_research

    return start_research(business_profile(company, create=False))


def _approve_segments(company: str, step: Step) -> str:
    import frappe

    from reckon_sales_agent.research.market import approve

    brief = frappe.get_doc("Sales Market Brief", step.ref["brief"])
    keep = pick_segments([{"name": r.name, "priority": r.priority, "idx": r.idx} for r in brief.segments])
    created = approve(brief, keep)
    return f"{len(created)} segment(s) chosen"


def smart_sources(company: str) -> str:
    """The Company's Smart Sources connector (every active lead source), created when autopilot needs it."""
    import frappe

    name = frappe.db.get_value("Sales Source Connector", {"company": company, "connector_type": "multi_source"})
    if name:
        doc = frappe.get_doc("Sales Source Connector", name)
        if not (doc.enabled and doc.policy_reviewed):
            doc.db_set({"enabled": 1, "policy_reviewed": 1})  # the manager confirmed when turning autopilot on
        return name
    return frappe.get_doc({"doctype": "Sales Source Connector", "company": company, "connector_type": "multi_source",
                           "connector_name": "Smart Sources", "enabled": 1, "policy_reviewed": 1}) \
        .insert(ignore_permissions=True).name


def _start_discovery(company: str, step: Step) -> str:
    import frappe
    from frappe.utils import nowdate

    from reckon_sales_agent.discovery.runner import build_plan
    from reckon_sales_agent.jobs import enqueue_discovery
    from reckon_sales_agent.research.market import business_profile
    from reckon_sales_agent.usage import get_settings

    settings = get_settings(company)
    profile = business_profile(company, create=False)
    targets = frappe.get_all("Sales Market Segment", filters={"parent": profile.latest_brief, "include": 1},
                             fields=["targeting_profile", "segment_name"])
    searched = set(frappe.get_all("Sales Discovery Campaign", filters={"company": company}, pluck="targeting_profile"))
    new = [t for t in targets if t.targeting_profile and t.targeting_profile not in searched]
    connector = smart_sources(company)
    per_segment = max(10, int(settings.get("autopilot_weekly_leads") or 50) // max(1, len(targets)))
    started = 0
    for target in new:
        campaign = frappe.get_doc({
            "doctype": "Sales Discovery Campaign", "company": company,
            "campaign_name": f"Autopilot · {target.segment_name}"[:140],
            "source_connector": connector, "targeting_profile": target.targeting_profile,
            "qualification_profile": frappe.db.get_value("Sales Qualification Profile", {"company": company}),
            "target_count": min(per_segment, settings.max_results_per_job or 100), "per_query_limit": 20,
            "auto_research": 1, "schedule": "Weekly", "run_at_time": "09:00",
        })
        build_plan(campaign)
        campaign.insert(ignore_permissions=True)
        campaign.db_set({"status": "Planned", "next_run_on": nowdate()})
        try:
            enqueue_discovery(campaign)  # over the concurrent-job limit: the hourly schedule starts it later
            started += 1
        except frappe.ValidationError:
            frappe.clear_messages()
    return f"{len(new)} lead search(es) set up, {started} started now"


def _auto_review(company: str, step: Step) -> str:
    import frappe

    from reckon_sales_agent.autopilot import maybe_auto_approve

    names = frappe.get_all("Sales Prospect", filters={"company": company, "review_status": "Pending",
                                                      "qualification_status": "Qualified"},
                           pluck="name", order_by="deal_probability desc", limit=50)
    approved = sum(1 for name in names if maybe_auto_approve(name))
    return f"{approved} of {len(names)} approved"


def _auto_triage(company: str, step: Step) -> str:
    import frappe

    from reckon_sales_agent.crm_sync import review

    foreign = foreign_pending(company)[:200]
    for name, reason in foreign:
        review(frappe.get_doc("Sales Prospect", name), "reject", f"Autopilot: outside your market ({reason}).")
    done = {n for n, _r in foreign}
    demo = [name for name in demo_pending(company)[:500] if name not in done]
    for name in demo:
        review(frappe.get_doc("Sales Prospect", name), "reject", "Autopilot: demo data from the built-in test source.")
    done.update(demo)
    threshold = review_threshold(company)
    weak = [name for name in weak_pending(company)[:500] if name not in done]
    for name in weak:
        review(frappe.get_doc("Sales Prospect", name), "reject",
               f"Autopilot: fit score below your review threshold ({threshold:g}). Approve it to bring it back.")
    return f"{len(foreign)} outside your market, {len(weak)} weak" + (f", {len(demo)} demo" if demo else "")


def _keep_finding(company: str, step: Step) -> str:
    """Make the approved segments' searches repeat weekly; one that never ran this week starts now."""
    import frappe
    from frappe.utils import add_days, nowdate

    from reckon_sales_agent.discovery.runner import build_plan
    from reckon_sales_agent.jobs import enqueue_discovery
    from reckon_sales_agent.research.market import business_profile

    profile = business_profile(company, create=False)
    targets = frappe.get_all("Sales Market Segment", filters={"parent": profile.latest_brief, "include": 1},
                             pluck="targeting_profile")
    names = _unscheduled(company, targets)
    started = 0
    for name in names:
        campaign = frappe.get_doc("Sales Discovery Campaign", name)
        last = str(campaign.last_run_on)[:10] if campaign.last_run_on else ""
        due_now = not last or last < str(add_days(nowdate(), -7))
        campaign.db_set({"schedule": "Weekly", "run_at_time": "09:00",
                         "next_run_on": add_days(nowdate() if due_now else last, 7)})
        if due_now and not frappe.db.exists("Sales Discovery Job", {"discovery_campaign": name,
                                                                    "status": ["in", ["Queued", "Running"]]}):
            build_plan(campaign)  # the next keywords and places after the last run (plan cursor)
            campaign.flags.ignore_permissions = True
            campaign.save()
            try:
                enqueue_discovery(campaign)
                started += 1
            except frappe.ValidationError:
                frappe.clear_messages()  # over the concurrent-job limit: it runs next week or on "Run agents now"
    return f"{len(names)} search(es) now weekly, {started} started now"


def _ai_triage(company: str, step: Step) -> str:
    from reckon_sales_agent.agents.triage import triage_batch
    from reckon_sales_agent.usage import get_settings

    settings = get_settings(company)
    apply = bool(settings.get("autopilot_enabled") and settings.get("autopilot_ai_triage"))
    counts = triage_batch(company, apply)
    if not apply:
        return f"{counts['judged']} judged; verdicts are shown for your review"
    return f"{counts['judged']} judged: {counts['approve']} approved, {counts['reject']} set aside, " \
           f"{counts['person']} for you"


def _learn_targeting(company: str, step: Step) -> str:
    from reckon_sales_agent.agents.learning import apply_lessons

    return apply_lessons(company)


def _find_contacts(company: str, step: Step) -> str:
    from reckon_sales_agent.agents.contacts import find_batch

    counts = find_batch(company)
    return f"{counts['found']} of {counts['checked']} found"


def campaign_offer(company: str) -> str:
    from reckon_sales_agent.research.market import business_profile

    profile = business_profile(company, create=False)
    products = [p for p in ((profile.products if profile else "") or "").splitlines() if p.strip()]
    what = products[0] if products else "our software"
    return f"A free 15-minute demo of {what}"


def _draft_campaign(company: str, step: Step) -> str:
    import frappe

    from reckon_sales_agent.agents.content_agent import write_sequence
    from reckon_sales_agent.usage import get_settings, log_activity

    settings = get_settings(company)
    disc = frappe.db.get_value("Sales Discovery Campaign", step.ref["discovery"],
                               ["name", "campaign_name", "targeting_profile"], as_dict=True)
    label = disc.campaign_name.replace("Autopilot · ", "")
    campaign = frappe.get_doc({
        "doctype": "Sales Campaign", "company": company, "campaign_name": f"Pilot · {label}"[:140],
        "discovery_campaign": disc.name, "targeting_profile": disc.targeting_profile,
        "offer": campaign_offer(company), "language": "English", "minimum_fit_score": 0,
        "daily_limit": min(20, settings.daily_message_limit or 20),
        "pilot_mode": 1, "holdout_percent": 20, "pilot_max_members": 30,
        "steps": [{"step_no": 1, "channel": "Email", "delay_days": 0, "subject_template": "Draft",
                   "body_template": "Draft"}],
    }).insert(ignore_permissions=True)
    write_sequence(campaign, 3, pilot_channels(step.ref.get("with_email", 0), step.ref.get("count", 0),
                                               bool(settings.whatsapp_enabled)))
    campaign.reload()
    campaign.db_set("status", "Pending Approval")
    log_activity(company, "campaign_submitted", campaign, "Drafted by autopilot; a person approves the launch",
                 actor_type="agent", agent="Content", policy_outcome="needs a person (launch_campaign)")
    return campaign.name


def _pilot_check(company: str, step: Step) -> str:
    import frappe

    from reckon_sales_agent.agents.analytics_agent import pilot_report

    return pilot_report(frappe.get_doc("Sales Campaign", step.ref["campaign"]))["verdict"]


DOERS = {
    "research_market": _research_market,
    "approve_segments": _approve_segments,
    "start_discovery": _start_discovery,
    "auto_review": _auto_review,
    "auto_triage": _auto_triage,
    "keep_finding": _keep_finding,
    "ai_triage": _ai_triage,
    "learn_targeting": _learn_targeting,
    "find_contacts": _find_contacts,
    "draft_campaign": _draft_campaign,
    "pilot_check": _pilot_check,
}

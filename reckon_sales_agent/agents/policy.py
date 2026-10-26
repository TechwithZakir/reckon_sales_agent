"""Autonomy and approval matrix for the sales agents (pure: no Frappe imports).

Four agents act for the Company: Research (discovery, company research,
scoring), Content (drafts, localisation, fact checks), Engagement (replies,
follow-ups, routing) and Analytics (conversions, attribution, optimisation).
Before any agent acts, ``decide`` says whether it may act alone, needs a
person's approval, or is blocked.

Approval is a permission boundary, not a confidence threshold: no model
score can turn a consent denial, suppression entry or missing approval into
an "allow". Unknown actions need a person.
"""

from __future__ import annotations

from dataclasses import dataclass

AUTOMATIC = "automatic"
WITHIN_LIMITS = "automatic_within_limits"
HUMAN = "human_approval"
BLOCK = "block"

ALLOW = "allow"
NEEDS_APPROVAL = "needs_approval"
DEFER = "defer"  # allowed, but not now (daily limit, quiet hours)
BLOCKED = "blocked"

AGENTS = ("Research", "Content", "Engagement", "Analytics", "Governance")

# action: (agent, default rule)
MATRIX: dict[str, tuple[str, str]] = {
    "research_company": ("Research", AUTOMATIC),
    "score_lead": ("Research", AUTOMATIC),
    "create_crm_lead": ("Research", AUTOMATIC),  # with deduplication
    "generate_draft": ("Content", AUTOMATIC),
    "send_approved_message": ("Engagement", WITHIN_LIMITS),
    "publish_approved_content": ("Content", WITHIN_LIMITS),
    "answer_routine_question": ("Engagement", AUTOMATIC),  # where channel rules permit
    "change_commercial_terms": ("Engagement", HUMAN),  # pricing, discounts, contracts
    "launch_campaign": ("Governance", HUMAN),
    "expand_audience": ("Governance", HUMAN),
    "delete_records": ("Governance", HUMAN),
    "handle_complaint": ("Engagement", HUMAN),
    "handle_legal_request": ("Engagement", HUMAN),
    "make_uncertain_claim": ("Content", HUMAN),
    "analyze_campaign": ("Analytics", AUTOMATIC),
}
# Actions that reach a person outside the Company.
CONTACT_ACTIONS = frozenset({"send_approved_message", "answer_routine_question", "publish_approved_content"})


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str
    agent: str

    @property
    def allowed(self) -> bool:
        return self.outcome == ALLOW


def decide(action: str, context: dict | None = None) -> Decision:
    """May ``action`` run now? ``context`` describes the facts, never a model's confidence.

    Context keys: suppressed, consent (True/False/None), kill_switch, approved, approval_current,
    within_limits, channel_allows (for routine answers), require_review (Company tightening).
    """
    ctx = context or {}
    agent, rule = MATRIX.get(action, ("Governance", HUMAN))
    if action in CONTACT_ACTIONS:
        if ctx.get("suppressed"):
            return Decision(BLOCKED, "The recipient opted out or is on the suppression list.", agent)
        if ctx.get("consent") is False:
            return Decision(BLOCKED, "There is no valid permission to contact this recipient.", agent)
        if ctx.get("kill_switch"):
            return Decision(BLOCKED, "Outreach is paused by the Company's kill switch.", agent)
    if rule == BLOCK:
        return Decision(BLOCKED, "This action is never allowed.", agent)
    if rule == HUMAN:
        if ctx.get("approved") and ctx.get("approval_current", True):
            return Decision(ALLOW, "Approved by a person.", agent)
        return Decision(NEEDS_APPROVAL, "A person must approve this action.", agent)
    if rule == WITHIN_LIMITS:
        if not ctx.get("approved"):
            return Decision(NEEDS_APPROVAL, "Only approved content can go out.", agent)
        if not ctx.get("approval_current", True):
            return Decision(NEEDS_APPROVAL, "The content, audience, channel or schedule changed after approval.", agent)
        if ctx.get("within_limits") is False:
            return Decision(DEFER, "Daily or campaign sending limit reached; it will go out later.", agent)
        return Decision(ALLOW, "Approved and within limits.", agent)
    if action == "answer_routine_question" and not ctx.get("channel_allows", False):
        return Decision(NEEDS_APPROVAL, "The channel's rules do not allow an automatic answer here.", agent)
    if ctx.get("require_review") and action in CONTACT_ACTIONS:
        return Decision(NEEDS_APPROVAL, "The Company requires a person to review this.", agent)
    return Decision(ALLOW, "Automatic under the Company's policy.", agent)


def agent_for(activity_action: str) -> str:
    """Which agent an audit-trail action belongs to (for activities logged before agents existed)."""
    action = activity_action or ""
    if action.startswith(("discovery", "research", "market", "qualif", "prospect", "website", "targeting",
                          "connector", "studio", "crm_synced", "source_data", "job_")):
        return "Research"
    if action.startswith(("draft", "content")):
        return "Content"
    if action.startswith(("reply", "member", "message_sent", "follow", "unsubscribe")):
        return "Engagement"
    if action.startswith(("campaign_analy", "insight", "attribution", "pilot")):
        return "Analytics"
    return "Governance"


def audience_grew_materially(approved_size: int, current_size: int) -> bool:
    """More than half again the approved audience (and at least 10 more) needs a fresh approval."""
    approved = int(approved_size or 0)
    current = int(current_size or 0)
    return approved > 0 and current - approved >= max(10, approved // 2)

"""Social publishing: the Content agent writes, a person approves, the agent publishes through official APIs.

Publishing is "automatic within the approved scope" (see ``agents.policy``):
only an approved post whose content, media, accounts and schedule still
match the approval goes out, and only while the vendor has social
publishing switched on. A platform that cannot take a post through its API
(for example Instagram without an image) gets a task for a person instead.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import get_datetime, get_url, now_datetime

from reckon_sales_agent.agents.approvals import approval_current, fingerprint
from reckon_sales_agent.agents.content import check_step, knowledge_prompt
from reckon_sales_agent.agents.policy import ALLOW, decide
from reckon_sales_agent.agents.social import (
    SOCIAL_SCHEMA,
    SOCIAL_SYSTEM,
    SocialError,
    client_for,
    compose,
    post_payload,
    target_issues,
)
from reckon_sales_agent.constants import USAGE_AI
from reckon_sales_agent.providers.factory import get_llm
from reckon_sales_agent.providers.llm import LLMError, untrusted
from reckon_sales_agent.usage import log_activity, platform_settings, remaining, reserve

POST = "Sales Social Post"
ACCOUNT = "Sales Social Account"


def _platform(target) -> str:
    return target.platform or frappe.db.get_value(ACCOUNT, target.social_account, "platform") or ""


def target_text(post, target) -> str:
    return compose(target.caption or post.content or "", post.hashtags)


def apply_check(post) -> None:
    """Content check for every target: claims, figures, offers (approved knowledge) and platform limits."""
    from reckon_sales_agent.agents.content_agent import _brand, approved_knowledge

    if not post.targets:
        post.content_status, post.content_issues = "Not checked", None
        return
    _voice, banned, _profile = _brand(post.company)
    knowledge = approved_knowledge(post.company, post.get("language"))
    knowledge_text = "\n".join(f"{k.title}\n{k.content}" for k in knowledge)
    pricing_text = "\n".join(k.content for k in knowledge if k.category in ("Pricing", "Offer"))
    issues = []
    for index, target in enumerate(post.targets, start=1):
        platform = _platform(target)
        text = target_text(post, target)
        issues += check_step({"step_no": index, "channel": platform, "subject_template": "", "body_template": text},
                             knowledge_text, pricing_text, banned)
        issues += target_issues(platform, text, bool(post.image))
    post.content_status = "Needs review" if issues else "Passed"
    post.content_issues = "\n".join(issues)[:5000] or None


def write_post(post) -> int:
    """Claude writes a caption per target platform, with hashtags and alt text, from approved knowledge."""
    from reckon_sales_agent.agents.content_agent import _brand, _segment, approved_knowledge

    if post.status not in ("Draft", "Pending Approval"):
        frappe.throw(_("Only drafts can be rewritten."))
    llm = get_llm(post.company)
    if not llm:
        frappe.throw(_("Turn on AI in Sales Agent Settings to write with AI."))
    if remaining(post.company, USAGE_AI) <= 0:
        frappe.throw(_("Monthly AI limit reached."))
    if not post.targets:
        for account in frappe.get_all(ACCOUNT, filters={"company": post.company, "enabled": 1},
                                      fields=["name", "platform"]):
            post.append("targets", {"social_account": account.name, "platform": account.platform})
    platforms = sorted({_platform(t) for t in post.targets} - {""})
    if not platforms:
        frappe.throw(_("Add a social account first."))
    voice, banned, profile = _brand(post.company)
    knowledge = approved_knowledge(post.company, post.get("language"))
    reserve(post.company, USAGE_AI, 1, post)
    frappe.db.commit()
    segment = _segment(frappe._dict({"targeting_profile": post.targeting_profile, "discovery_campaign": None}))
    try:
        data = llm.complete_json(
            SOCIAL_SYSTEM + f" Brand voice: {voice}. Never use: {', '.join(banned) or 'n/a'}.",
            untrusted("seller", "\n".join(f"{k}: {v}" for k, v in profile.items() if v and k != "banned_phrases"))
            + "\n" + untrusted("audience", segment) + "\n"
            + untrusted("approved knowledge", knowledge_prompt(knowledge)) + "\n"
            + untrusted("topic", f"{post.title}\n{post.content or ''}") + "\n"
            + f"Language: {post.get('language') or 'English'}\nPlatforms: {', '.join(platforms)}",
            SOCIAL_SCHEMA, max_tokens=4000)
    except LLMError as exc:
        frappe.throw(str(exc))
    written = {p.get("platform"): p for p in data.get("posts") or [] if isinstance(p, dict)}
    count = 0
    for target in post.targets:
        draft = written.get(_platform(target))
        if draft and str(draft.get("caption") or "").strip():
            target.caption = compose(str(draft["caption"]).strip(), draft.get("hashtags") or [])[:3000]
            count += 1
    if not post.alt_text and data.get("alt_text"):
        post.alt_text = " ".join(str(data["alt_text"]).split())[:500]
    post.save()
    log_activity(post.company, "content_social_written", post, f"{count} platform captions", actor_type="agent",
                 agent="Social", policy_outcome="automatic (draft only)")
    return count


def submit(post) -> None:
    if post.status not in ("Draft", "Failed"):
        frappe.throw(_("Only drafts can be submitted."))
    if not post.targets:
        frappe.throw(_("Choose at least one account to publish to."))
    post.db_set("status", "Pending Approval")
    log_activity(post.company, "social_submitted", post, agent="Governance")


def approve(post, acknowledge_issues: bool = False) -> str:
    if post.status not in ("Pending Approval", "Draft"):
        frappe.throw(_("Submit the post for approval first."))
    if post.content_status == "Needs review" and not acknowledge_issues:
        frappe.throw(_("The content check found issues:") + "<br>" + "<br>".join(
            frappe.utils.escape_html(line) for line in (post.content_issues or "").splitlines()[:15]),
            title=_("Review the content first"))
    future = post.scheduled_at and get_datetime(post.scheduled_at) > now_datetime()
    status = "Scheduled" if future else "Approved"
    post.db_set({"status": status, "approved_by": frappe.session.user, "approved_on": now_datetime(),
                 "approval_fingerprint": fingerprint(post_payload(post))})
    log_activity(post.company, "social_approved", post, status, agent="Governance", policy_outcome="approved by a person")
    return status


def _image(post) -> tuple[str | None, bytes | None]:
    """Public URL (for Meta) and bytes (for LinkedIn's upload) of the post's image."""
    if not post.image:
        return None, None
    file_name = frappe.db.get_value("File", {"file_url": post.image}, "name")
    if not file_name:
        return None, None
    file = frappe.get_doc("File", file_name)
    if file.is_private:
        raise SocialError("The image is private; make the file public so the platform can fetch it.")
    return get_url(file.file_url), file.get_content()


def publish(post) -> str:
    """Publish an approved post to each target that is not yet published; returns the post's new status."""
    settings = platform_settings()
    decision = decide("publish_approved_content", {
        "approved": post.status in ("Approved", "Scheduled", "Partly Published", "Failed") and bool(post.approved_by),
        "approval_current": approval_current(post.approval_fingerprint, post_payload(post)),
    })
    if decision.outcome != ALLOW:
        frappe.throw(_(decision.reason))
    if not settings.get("social_enabled"):
        frappe.throw(_("Social publishing is switched off by the platform vendor."))
    try:
        image_url, image_bytes = _image(post)
    except SocialError as exc:
        frappe.throw(str(exc))
    for target in post.targets:
        if target.status == "Published":
            continue
        account = frappe.get_doc(ACCOUNT, target.social_account)
        platform = account.platform
        text = target_text(post, target)
        problems = target_issues(platform, text, bool(image_url))
        try:
            if not account.enabled:
                raise SocialError(f"{account.account_name} is disabled.")
            if problems and any("only publishes posts with an image" in p for p in problems):
                raise SocialError(problems[0], manual=True)
            client = client_for(platform, account.account_id,
                                account.get_password("access_token", raise_exception=False) or "",
                                meta_version=settings.get("meta_graph_version") or "v23.0",
                                linkedin_version=settings.get("linkedin_api_version") or "202509")
            frappe.db.commit()  # no open transaction while waiting on the platform
            result = client.publish(text, link=post.link_url, image_url=image_url, image_bytes=image_bytes,
                                    alt_text=post.alt_text, title=post.title)
            target.db_set({"status": "Published", "external_post_id": result["id"][:140], "post_url": result["url"],
                           "published_on": now_datetime(), "error": None})
        except SocialError as exc:
            target.db_set({"status": "Manual" if exc.manual else "Failed", "error": str(exc)[:500]})
            if exc.manual:
                _manual_task(post, account, text, str(exc))
    states = [t.status for t in frappe.get_doc(POST, post.name).targets]
    status = ("Published" if all(s in ("Published", "Manual") for s in states) and "Published" in states
              else "Partly Published" if "Published" in states else "Failed")
    post.db_set({"status": status, "published_on": now_datetime() if "Published" in states else None})
    log_activity(post.company, "social_published", post, f"{status}: {states.count('Published')}/{len(states)}",
                 actor_type="agent", agent="Social", policy_outcome=decision.outcome)
    return status


def _manual_task(post, account, text: str, reason: str) -> None:
    """The platform's API cannot take this post: a person posts it by hand."""
    frappe.get_doc({
        "doctype": "ToDo",
        "description": f"Post manually on {account.platform} ({account.account_name}): {post.title}\n\n{reason}\n\n{text}",
        "allocated_to": post.owner,
        "reference_type": POST,
        "reference_name": post.name,
        "priority": "Medium",
    }).insert(ignore_permissions=True)


def publish_due_posts() -> None:
    """Hourly: publish scheduled posts whose time has come."""
    for name in frappe.get_all(POST, filters={"status": "Scheduled", "scheduled_at": ["<=", now_datetime()]},
                               pluck="name", limit=200):
        try:
            publish(frappe.get_doc(POST, name))
            frappe.db.commit()
        except Exception:
            frappe.db.rollback()
            frappe.db.set_value(POST, name, "status", "Failed")
            frappe.log_error(title="Sales Agent social publishing failed", reference_doctype=POST, reference_name=name)
            frappe.db.commit()


def check_account(account) -> str:
    settings = platform_settings()
    try:
        client = client_for(account.platform, account.account_id,
                            account.get_password("access_token", raise_exception=False) or "",
                            meta_version=settings.get("meta_graph_version") or "v23.0",
                            linkedin_version=settings.get("linkedin_api_version") or "202509")
        name = client.check()
        account.db_set({"last_check": f"OK · {name} · {now_datetime():%Y-%m-%d %H:%M}", "last_error": None})
        return name
    except SocialError as exc:
        account.db_set({"last_check": f"Failed · {now_datetime():%Y-%m-%d %H:%M}", "last_error": str(exc)[:500]})
        frappe.throw(str(exc))

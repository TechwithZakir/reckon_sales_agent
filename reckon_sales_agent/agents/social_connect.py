"""Connect social accounts with each platform's own sign-in (OAuth), instead of pasting tokens.

* Meta (Facebook Pages, their Instagram professional accounts, Messenger): Facebook Login with the system
  provider's Meta app. The code is exchanged for a long-lived user token, then ``/me/accounts`` lists the Pages
  the person manages with a Page token each (a Page token from a long-lived user token does not expire) and the
  Instagram account linked to each Page. Each Page is subscribed to the app's Messenger webhook so messages reach
  Conversations.
* LinkedIn organization pages: LinkedIn's 3-legged OAuth with the provider's LinkedIn app; the token lasts
  60 days and is refreshed with the refresh token when LinkedIn issued one, else the Company is asked to
  reconnect a week before it ends.

The ``state`` sent through the platform is signed and names the Company, the user and an expiry, so a callback
can only connect accounts for the person who started it. Nothing here posts or messages anyone.
The URL, state and parsing helpers are pure.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

META_VERSION = "v23.0"
LINKEDIN_VERSION = "202509"
META_SCOPES = ("pages_show_list", "pages_read_engagement", "pages_read_user_content", "pages_manage_posts",
               "pages_manage_metadata", "pages_messaging", "instagram_basic", "instagram_content_publish",
               "instagram_manage_messages", "instagram_manage_comments", "leads_retrieval", "pages_manage_ads",
               "business_management")
LINKEDIN_SCOPES = ("w_organization_social", "r_organization_social", "rw_organization_admin")
# Lead Gen forms: a separate LinkedIn approval (Lead Sync API), so a separate connection.
LINKEDIN_LEAD_SCOPES = ("r_marketing_leadgen_automation", "r_organization_admin")
STATE_TTL = 900  # seconds to finish signing in
PROVIDERS = ("meta", "linkedin", "linkedin_leads")


def sign_state(data: dict, secret: str, now: float | None = None) -> str:
    body = dict(data, exp=int((now or time.time()) + STATE_TTL))
    raw = base64.urlsafe_b64encode(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).decode().rstrip("=")
    mac = hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{raw}.{mac}"


def read_state(state: str, secret: str, now: float | None = None) -> dict | None:
    """The signed data, or None when it was altered or has expired."""
    raw, _, mac = (state or "").partition(".")
    expected = hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()[:32]
    if not raw or not hmac.compare_digest(mac, expected):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    except ValueError:
        return None
    if not isinstance(data, dict) or int(data.get("exp") or 0) < (now or time.time()):
        return None
    return data


def authorize_url(provider: str, client_id: str, redirect_uri: str, state: str) -> str:
    if provider == "meta":
        return f"https://www.facebook.com/{META_VERSION}/dialog/oauth?" + urlencode({
            "client_id": client_id, "redirect_uri": redirect_uri, "state": state, "response_type": "code",
            "scope": ",".join(META_SCOPES)})
    if provider in ("linkedin", "linkedin_leads"):
        return "https://www.linkedin.com/oauth/v2/authorization?" + urlencode({
            "response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri, "state": state,
            "scope": " ".join(LINKEDIN_LEAD_SCOPES if provider == "linkedin_leads" else LINKEDIN_SCOPES)})
    raise ValueError(provider)


def meta_accounts(pages: list[dict]) -> list[dict]:
    """Sales Social Account values from ``/me/accounts`` (each Page, and its Instagram account when linked)."""
    out = []
    for page in pages or []:
        if not isinstance(page, dict) or not page.get("id") or not page.get("access_token"):
            continue
        tasks = set(page.get("tasks") or [])
        if tasks and not tasks & {"MANAGE", "CREATE_CONTENT", "MODERATE", "MESSAGING"}:
            continue  # a Page role that cannot post or answer
        out.append({"platform": "Facebook Page", "account_id": str(page["id"]), "account_name": page.get("name") or "",
                    "token": page["access_token"], "linked_page_id": None})
        ig = page.get("instagram_business_account") or {}
        if ig.get("id"):
            out.append({"platform": "Instagram", "account_id": str(ig["id"]),
                        "account_name": ig.get("username") or f"{page.get('name') or ''} (Instagram)",
                        "token": page["access_token"], "linked_page_id": str(page["id"])})
    return out


def linkedin_organizations(acls: dict) -> list[str]:
    """Organization IDs the person administers, from ``organizationAcls?q=roleAssignee``."""
    out = []
    for row in (acls or {}).get("elements") or []:
        urn = str(row.get("organization") or row.get("organizationTarget") or "")
        if row.get("state", "APPROVED") == "APPROVED" and urn.startswith("urn:li:organization:"):
            out.append(urn.rsplit(":", 1)[-1])
    return sorted(set(out))


# --------------------------------------------------------------------------- Frappe side


def _secret() -> str:
    from frappe.utils.password import get_encryption_key

    return get_encryption_key()


def redirect_uri() -> str:
    from frappe.utils import get_url

    return get_url("/api/method/reckon_sales_agent.api_channels.social_callback")


def _app(provider: str) -> tuple[str, str]:
    import frappe
    from frappe import _

    from reckon_sales_agent.usage import platform_settings

    platform = platform_settings()
    linkedin = ("linkedin_client_id", "linkedin_client_secret")
    fields = {"meta": ("meta_app_id", "meta_app_secret"), "linkedin": linkedin, "linkedin_leads": linkedin}
    id_field, secret_field = fields[provider]
    client_id = platform.get(id_field)
    secret = platform.get_password(secret_field, raise_exception=False) if platform.get(secret_field) else None
    if not client_id or not secret:
        frappe.throw(_("The system provider has not set up the {0} app yet.").format(
            "Meta" if provider == "meta" else "LinkedIn"))
    return client_id, secret


def start(company: str, user: str, provider: str) -> str:
    """The platform's sign-in URL for this Company and user."""
    client_id, _secret_value = _app(provider)
    state = sign_state({"c": company, "u": user, "p": provider}, _secret())
    return authorize_url(provider, client_id, redirect_uri(), state)


def finish(state: str, code: str, user: str) -> tuple[str, list[str], list[str]]:
    """Exchange the code and save the accounts; returns (company, saved names, skipped names).

    An account another Company already runs is skipped and reported; the rest still connect."""
    import frappe
    from frappe import _

    data = read_state(state, _secret())
    if not data or data.get("u") != user or data.get("p") not in PROVIDERS:
        frappe.throw(_("This sign-in link expired or belongs to someone else. Start again from Channels."),
                     frappe.PermissionError)
    company, provider = data["c"], data["p"]
    accounts = _meta(code) if provider == "meta" else _linkedin(code, lead_gen=provider == "linkedin_leads")
    saved, skipped = [], []
    for account in accounts:
        try:
            saved.append(save_account(company, user, account))
        except frappe.ValidationError:
            skipped.append(account.get("account_name") or account["account_id"])
    from reckon_sales_agent.usage import log_activity

    log_activity(company, "social_connected", None, ", ".join(saved)[:500] or "no accounts", agent="Social")
    return company, saved, skipped


def _get(url: str, **kw) -> dict:
    import frappe
    import requests

    from reckon_sales_agent.providers.llm import http_reason

    try:
        response = requests.request(kw.pop("method", "GET"), url, timeout=30, **kw)
    except requests.RequestException:
        frappe.throw("The platform could not be reached; try again.")
    if response.status_code >= 400:
        frappe.throw(f"The platform refused: {http_reason(response)}")
    return response.json() if response.content else {}


def _meta(code: str) -> list[dict]:
    client_id, secret = _app("meta")
    base = f"https://graph.facebook.com/{META_VERSION}"
    short = _get(f"{base}/oauth/access_token", params={"client_id": client_id, "client_secret": secret,
                                                       "redirect_uri": redirect_uri(), "code": code})
    long = _get(f"{base}/oauth/access_token", params={"grant_type": "fb_exchange_token", "client_id": client_id,
                                                      "client_secret": secret, "fb_exchange_token": short["access_token"]})
    pages = _get(f"{base}/me/accounts", params={
        "fields": "id,name,access_token,tasks,instagram_business_account{id,username}", "limit": 100,
        "access_token": long["access_token"]})
    accounts = meta_accounts(pages.get("data") or [])
    for account in accounts:
        if account["platform"] == "Facebook Page":
            # Messages and comments on the Page reach our webhook (and so Conversations).
            _get(f"{base}/{account['account_id']}/subscribed_apps", method="POST",
                 params={"subscribed_fields": "messages,messaging_postbacks,feed,leadgen",
                         "access_token": account["token"]})
    return accounts


def _linkedin(code: str, lead_gen: bool = False) -> list[dict]:
    from frappe.utils import add_to_date, now_datetime

    client_id, secret = _app("linkedin")
    token = _get("https://www.linkedin.com/oauth/v2/accessToken", method="POST", data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri(), "client_id": client_id,
        "client_secret": secret})
    headers = {"Authorization": f"Bearer {token['access_token']}", "LinkedIn-Version": LINKEDIN_VERSION,
               "X-Restli-Protocol-Version": "2.0.0"}
    acls = _get("https://api.linkedin.com/rest/organizationAcls", headers=headers,
                params={"q": "roleAssignee", "role": "ADMINISTRATOR", "state": "APPROVED"})
    expires = add_to_date(now_datetime(), seconds=int(token.get("expires_in") or 5184000)).date()
    out = []
    for org in linkedin_organizations(acls):
        info = _get(f"https://api.linkedin.com/rest/organizations/{org}", headers=headers)
        out.append({"platform": "LinkedIn Lead Gen" if lead_gen else "LinkedIn", "account_id": org,
                    "account_name": info.get("localizedName") or org,
                    "token": token["access_token"], "refresh_token": token.get("refresh_token"),
                    "expires_on": expires, "linked_page_id": None})
    return out


def save_account(company: str, user: str, account: dict) -> str:
    import frappe

    name = frappe.db.get_value("Sales Social Account", {"company": company, "platform": account["platform"],
                                                        "account_id": account["account_id"]})
    doc = frappe.get_doc("Sales Social Account", name) if name else frappe.new_doc("Sales Social Account")
    doc.update({"company": company, "platform": account["platform"], "account_id": account["account_id"],
                "account_name": (account.get("account_name") or account["account_id"])[:140], "enabled": 1,
                "access_token": account["token"], "token_expires_on": account.get("expires_on"),
                "connected_by": user, "linked_page_id": account.get("linked_page_id"), "last_error": None,
                "last_check": f"Connected {frappe.utils.now_datetime():%Y-%m-%d %H:%M}"})
    if account.get("refresh_token"):
        doc.refresh_token = account["refresh_token"]
    doc.flags.ignore_permissions = True
    doc.save()
    return f"{doc.platform}: {doc.account_name}"


def refresh_accounts() -> None:
    """Daily: refresh LinkedIn tokens that end within a week, and check every connected account still works."""
    import frappe
    from frappe.utils import add_days, getdate, nowdate

    from reckon_sales_agent.agents.social_agent import check_account

    for row in frappe.get_all("Sales Social Account", filters={"enabled": 1}, fields=["name", "platform",
                                                                                       "token_expires_on"]):
        account = frappe.get_doc("Sales Social Account", row.name)
        try:
            if (row.platform in ("LinkedIn", "LinkedIn Lead Gen") and row.token_expires_on
                    and getdate(row.token_expires_on) <= getdate(add_days(nowdate(), 7))):
                _refresh_linkedin(account)
            check_account(account)
        except Exception as exc:
            frappe.db.rollback()
            frappe.db.set_value("Sales Social Account", row.name, "last_error", str(exc)[:500])
        frappe.db.commit()


def _refresh_linkedin(account) -> None:
    import frappe
    from frappe.utils import add_to_date, now_datetime

    refresh = account.get_password("refresh_token", raise_exception=False) if account.get("refresh_token") else None
    if not refresh:
        frappe.throw("The LinkedIn connection ends soon: reconnect LinkedIn on the Channels page.")
    client_id, secret = _app("linkedin")
    token = _get("https://www.linkedin.com/oauth/v2/accessToken", method="POST", data={
        "grant_type": "refresh_token", "refresh_token": refresh, "client_id": client_id, "client_secret": secret})
    account.access_token = token["access_token"]
    account.token_expires_on = add_to_date(now_datetime(), seconds=int(token.get("expires_in") or 5184000)).date()
    if token.get("refresh_token"):
        account.refresh_token = token["refresh_token"]
    account.flags.ignore_permissions = True
    account.save()

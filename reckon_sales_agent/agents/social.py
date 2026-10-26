"""Social publishing rules and official API clients (pure: no Frappe imports).

Only official, documented APIs are used:

* Facebook Page: Graph API ``POST /{page-id}/feed`` (text, link) or
  ``POST /{page-id}/photos`` (image by public URL, with caption).
* Instagram professional account: content publishing, ``POST /{ig-user-id}/media``
  (image URL, caption, alt text) then ``POST /{ig-user-id}/media_publish``.
  Instagram does not publish text-only posts.
* LinkedIn organization page: Posts API ``POST /rest/posts``; images are
  uploaded first through the Images API (``initializeUpload`` + upload URL).

Anything a platform cannot do through its API becomes a task for a person;
nothing is ever automated through a browser.
"""

from __future__ import annotations

import re

import requests

from reckon_sales_agent.providers.llm import UNTRUSTED_RULES

PLATFORMS = ("Facebook Page", "Instagram", "LinkedIn")
CAPTION_LIMITS = {"Facebook Page": 63000, "Instagram": 2200, "LinkedIn": 3000}
MAX_HASHTAGS = {"Facebook Page": 10, "Instagram": 30, "LinkedIn": 10}
HASHTAG = re.compile(r"#[\wঀ-৿]+")


class SocialError(Exception):
    """A platform refused or could not be reached; ``manual`` means a person must post it instead."""

    def __init__(self, message: str, manual: bool = False):
        super().__init__(message)
        self.manual = manual


def clean_hashtags(value) -> list[str]:
    items = value if isinstance(value, list) else re.split(r"[\s,]+", str(value or ""))
    tags = []
    for item in items:
        tag = "#" + re.sub(r"[^\wঀ-৿]", "", str(item).lstrip("#"))
        if len(tag) > 1 and tag.lower() not in {t.lower() for t in tags}:
            tags.append(tag)
    return tags


def compose(caption: str, hashtags) -> str:
    """Final text: the caption, then the hashtags that are not already in it."""
    text = (caption or "").strip()
    present = {t.lower() for t in HASHTAG.findall(text)}
    extra = [t for t in clean_hashtags(hashtags) if t.lower() not in present]
    return f"{text}\n\n{' '.join(extra)}".strip() if extra else text


def target_issues(platform: str, text: str, has_image: bool) -> list[str]:
    """What stops this target from publishing through the platform's API."""
    issues = []
    if platform not in PLATFORMS:
        return [f"{platform}: not a supported platform."]
    if not text.strip() and not has_image:
        issues.append(f"{platform}: nothing to post.")
    if len(text) > CAPTION_LIMITS[platform]:
        issues.append(f"{platform}: {len(text)} characters; the limit is {CAPTION_LIMITS[platform]}.")
    if len(HASHTAG.findall(text)) > MAX_HASHTAGS[platform]:
        issues.append(f"{platform}: more than {MAX_HASHTAGS[platform]} hashtags.")
    if platform == "Instagram" and not has_image:
        issues.append("Instagram: the API only publishes posts with an image; attach one or post it manually.")
    return issues


def post_payload(post) -> dict:
    """What a person approves for a social post: content, media, link, accounts and schedule."""
    get = (lambda f: post.get(f)) if isinstance(post, dict) else (lambda f: getattr(post, f, None))
    targets = sorted((str((t.get("social_account") if isinstance(t, dict) else t.social_account) or ""),
                      str((t.get("caption") if isinstance(t, dict) else t.caption) or ""))
                     for t in (get("targets") or []))
    return {"content": get("content") or "", "hashtags": get("hashtags") or "", "alt_text": get("alt_text") or "",
            "image": get("image") or "", "link_url": get("link_url") or "",
            "scheduled_at": str(get("scheduled_at") or ""), "targets": [list(t) for t in targets]}


SOCIAL_SYSTEM = (
    "You write social media posts for a B2B company in Bangladesh, for its own Facebook Page, Instagram account "
    "and LinkedIn page. Use ONLY facts from the approved knowledge: never invent prices, discounts, offers, client "
    "names, numbers, awards or guarantees. Write one version per platform: Facebook friendly and short (up to 80 "
    "words); Instagram visual and concise with line breaks (up to 60 words); LinkedIn professional and insightful "
    "(up to 150 words). Suggest up to 5 relevant hashtags per platform (English or Bangla, no spaces). Write "
    "accessible alt text describing the kind of image that would suit the post (one sentence). Write in the "
    "requested language; for Bangla keep product names in English. " + UNTRUSTED_RULES
)
SOCIAL_SCHEMA = {
    "type": "object",
    "properties": {
        "posts": {"type": "array", "items": {
            "type": "object",
            "properties": {"platform": {"type": "string", "enum": list(PLATFORMS)}, "caption": {"type": "string"},
                           "hashtags": {"type": "array", "items": {"type": "string"}}},
            "required": ["platform", "caption", "hashtags"],
            "additionalProperties": False,
        }},
        "alt_text": {"type": "string"},
    },
    "required": ["posts", "alt_text"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------- official API clients

def _check(response, platform: str) -> dict:
    try:
        data = response.json() if response.content else {}
    except ValueError:
        data = {}
    if response.status_code >= 400:
        error = (data.get("error") or {}) if isinstance(data, dict) else {}
        message = error.get("message") if isinstance(error, dict) else None
        message = message or (data.get("message") if isinstance(data, dict) else None) or f"HTTP {response.status_code}"
        raise SocialError(f"{platform}: {str(message)[:300]}")
    return data if isinstance(data, dict) else {}


class FacebookPage:
    platform = "Facebook Page"

    def __init__(self, page_id: str, token: str, version: str = "v23.0", session=None, timeout: int = 30):
        self.page_id, self.token, self.version = page_id, token, version
        self.session = session or requests.Session()
        self.timeout = timeout
        self.base = f"https://graph.facebook.com/{version}"

    def check(self) -> str:
        data = _check(self.session.get(f"{self.base}/{self.page_id}", params={"fields": "name", "access_token": self.token},
                                       timeout=self.timeout), self.platform)
        return data.get("name") or self.page_id

    def publish(self, text: str, link: str | None = None, image_url: str | None = None, **_kw) -> dict:
        if image_url:
            data = _check(self.session.post(f"{self.base}/{self.page_id}/photos", data={
                "url": image_url, "caption": text, "access_token": self.token}, timeout=self.timeout), self.platform)
            post_id = data.get("post_id") or data.get("id")
        else:
            body = {"message": text, "access_token": self.token}
            if link:
                body["link"] = link
            post_id = _check(self.session.post(f"{self.base}/{self.page_id}/feed", data=body, timeout=self.timeout),
                             self.platform).get("id")
        if not post_id:
            raise SocialError(f"{self.platform}: no post id returned.")
        return {"id": post_id, "url": f"https://www.facebook.com/{post_id}"}


class Instagram:
    platform = "Instagram"

    def __init__(self, ig_user_id: str, token: str, version: str = "v23.0", session=None, timeout: int = 60):
        self.user_id, self.token = ig_user_id, token
        self.session = session or requests.Session()
        self.timeout = timeout
        self.base = f"https://graph.facebook.com/{version}"

    def check(self) -> str:
        data = _check(self.session.get(f"{self.base}/{self.user_id}", params={"fields": "username",
                                       "access_token": self.token}, timeout=self.timeout), self.platform)
        return data.get("username") or self.user_id

    def publish(self, text: str, image_url: str | None = None, alt_text: str | None = None, **_kw) -> dict:
        if not image_url:
            raise SocialError("Instagram: the API only publishes posts with an image.", manual=True)
        container = {"image_url": image_url, "caption": text, "access_token": self.token}
        if alt_text:
            container["alt_text"] = alt_text[:1000]
        creation = _check(self.session.post(f"{self.base}/{self.user_id}/media", data=container, timeout=self.timeout),
                          self.platform).get("id")
        if not creation:
            raise SocialError("Instagram: the media container was not created.")
        media_id = _check(self.session.post(f"{self.base}/{self.user_id}/media_publish", data={
            "creation_id": creation, "access_token": self.token}, timeout=self.timeout), self.platform).get("id")
        if not media_id:
            raise SocialError("Instagram: the post was not published.")
        link = _check(self.session.get(f"{self.base}/{media_id}", params={"fields": "permalink",
                                       "access_token": self.token}, timeout=self.timeout), self.platform)
        return {"id": media_id, "url": link.get("permalink") or ""}


class LinkedInOrganization:
    platform = "LinkedIn"

    def __init__(self, organization_id: str, token: str, version: str = "202509", session=None, timeout: int = 30):
        org = str(organization_id).strip()
        self.author = org if org.startswith("urn:li:") else f"urn:li:organization:{org}"
        self.token, self.version = token, version
        self.session = session or requests.Session()
        self.timeout = timeout
        self.headers = {"Authorization": f"Bearer {token}", "LinkedIn-Version": version,
                        "X-Restli-Protocol-Version": "2.0.0", "Content-Type": "application/json"}

    def check(self) -> str:
        org_id = self.author.rsplit(":", 1)[-1]
        data = _check(self.session.get(f"https://api.linkedin.com/rest/organizations/{org_id}", headers=self.headers,
                                       timeout=self.timeout), self.platform)
        name = data.get("localizedName") or (data.get("name") or {}).get("localized", {})
        return name if isinstance(name, str) and name else self.author

    def _upload_image(self, image: bytes) -> str:
        init = _check(self.session.post("https://api.linkedin.com/rest/images?action=initializeUpload",
                                        json={"initializeUploadRequest": {"owner": self.author}},
                                        headers=self.headers, timeout=self.timeout), self.platform)
        value = init.get("value") or {}
        if not value.get("uploadUrl") or not value.get("image"):
            raise SocialError("LinkedIn: image upload could not start.")
        response = self.session.put(value["uploadUrl"], data=image, headers={"Authorization": f"Bearer {self.token}"},
                                    timeout=self.timeout)
        if response.status_code >= 400:
            raise SocialError(f"LinkedIn: image upload failed (HTTP {response.status_code}).")
        return value["image"]

    def publish(self, text: str, link: str | None = None, image_bytes: bytes | None = None,
                alt_text: str | None = None, title: str | None = None, **_kw) -> dict:
        body = {
            "author": self.author, "commentary": text, "visibility": "PUBLIC",
            "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
            "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False,
        }
        if image_bytes:
            body["content"] = {"media": {"id": self._upload_image(image_bytes), "altText": (alt_text or "")[:4000]}}
        elif link:
            body["content"] = {"article": {"source": link, "title": (title or link)[:200]}}
        response = self.session.post("https://api.linkedin.com/rest/posts", json=body, headers=self.headers,
                                     timeout=self.timeout)
        _check(response, self.platform)
        urn = response.headers.get("x-restli-id") or response.headers.get("X-RestLi-Id")
        if not urn:
            raise SocialError("LinkedIn: no post id returned.")
        return {"id": urn, "url": f"https://www.linkedin.com/feed/update/{urn}"}


def client_for(platform: str, account_id: str, token: str, *, meta_version: str = "v23.0",
               linkedin_version: str = "202509", session=None):
    if platform == "Facebook Page":
        return FacebookPage(account_id, token, meta_version, session=session)
    if platform == "Instagram":
        return Instagram(account_id, token, meta_version, session=session)
    if platform == "LinkedIn":
        return LinkedInOrganization(account_id, token, linkedin_version, session=session)
    raise SocialError(f"{platform} is not supported through an official API here.", manual=True)

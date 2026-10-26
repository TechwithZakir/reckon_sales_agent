"""Social publishing: rules, approval binding and the official API clients (no network, no bench)."""
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1]))

from reckon_sales_agent.agents.approvals import fingerprint  # noqa: E402
from reckon_sales_agent.agents.social import (  # noqa: E402
    SOCIAL_SCHEMA,
    FacebookPage,
    Instagram,
    LinkedInOrganization,
    SocialError,
    clean_hashtags,
    client_for,
    compose,
    post_payload,
    target_issues,
)

APP = Path(__file__).parents[1] / "reckon_sales_agent"


def reply(status=200, payload=None, headers=None):
    body = json.dumps(payload or {}).encode()
    return SimpleNamespace(status_code=status, content=body, json=lambda: payload or {}, headers=headers or {})


class Session:
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def _next(self, method, url, **kw):
        self.calls.append((method, url, kw))
        return self.replies.pop(0)

    def get(self, url, **kw):
        return self._next("GET", url, **kw)

    def post(self, url, **kw):
        return self._next("POST", url, **kw)

    def put(self, url, **kw):
        return self._next("PUT", url, **kw)


class RuleTests(unittest.TestCase):
    def test_hashtags(self):
        self.assertEqual(clean_hashtags("DMS, #distribution ফার্মা #dms"), ["#DMS", "#distribution", "#ফার্মা"])
        self.assertEqual(compose("New: Reckon DMS #DMS", ["#DMS", "pharma"]), "New: Reckon DMS #DMS\n\n#pharma")
        self.assertEqual(compose("Hello", ""), "Hello")

    def test_platform_limits(self):
        self.assertTrue(any("only publishes posts with an image" in i for i in target_issues("Instagram", "Hi", False)))
        self.assertEqual(target_issues("Instagram", "Hi", True), [])
        self.assertTrue(target_issues("LinkedIn", "x" * 3001, False))
        self.assertTrue(target_issues("Instagram", " ".join(f"#t{i}" for i in range(31)), True))
        self.assertTrue(target_issues("TikTok", "Hi", True))
        self.assertTrue(target_issues("Facebook Page", "  ", False))

    def test_approval_covers_text_media_accounts_and_time(self):
        post = {"content": "Reckon DMS for distributors", "hashtags": "#DMS", "alt_text": "", "image": "/files/a.png",
                "link_url": "", "scheduled_at": "2026-11-01 10:00:00",
                "targets": [{"social_account": "FB", "caption": "FB text"}, {"social_account": "LI", "caption": ""}]}
        stored = fingerprint(post_payload(post))
        reordered = {**post, "targets": list(reversed(post["targets"]))}
        self.assertEqual(stored, fingerprint(post_payload(reordered)))
        for change in ({"image": "/files/b.png"}, {"scheduled_at": "2026-11-02 10:00:00"},
                       {"targets": post["targets"] + [{"social_account": "IG", "caption": ""}]},
                       {"targets": [{"social_account": "FB", "caption": "FB text, 50% off!"}, post["targets"][1]]}):
            self.assertNotEqual(stored, fingerprint(post_payload({**post, **change})), change)

    def test_schema_is_strict(self):
        self.assertFalse(SOCIAL_SCHEMA["additionalProperties"])
        item = SOCIAL_SCHEMA["properties"]["posts"]["items"]
        self.assertEqual(set(item["required"]), set(item["properties"]))


class FacebookTests(unittest.TestCase):
    def test_text_with_link_goes_to_the_feed(self):
        session = Session(reply(200, {"id": "123_456"}))
        result = FacebookPage("123", "tok", "v23.0", session=session).publish("Hello", link="https://reckon.tech")
        method, url, kw = session.calls[0]
        self.assertEqual((method, url), ("POST", "https://graph.facebook.com/v23.0/123/feed"))
        self.assertEqual(kw["data"], {"message": "Hello", "access_token": "tok", "link": "https://reckon.tech"})
        self.assertEqual(result, {"id": "123_456", "url": "https://www.facebook.com/123_456"})

    def test_image_goes_to_photos_and_errors_are_explained(self):
        session = Session(reply(200, {"id": "9", "post_id": "123_9"}))
        result = FacebookPage("123", "tok", session=session).publish("Hi", image_url="https://x/a.png")
        self.assertTrue(session.calls[0][1].endswith("/123/photos"))
        self.assertEqual(session.calls[0][2]["data"]["url"], "https://x/a.png")
        self.assertEqual(result["id"], "123_9")
        bad = Session(reply(400, {"error": {"message": "Invalid OAuth access token."}}))
        with self.assertRaises(SocialError) as ctx:
            FacebookPage("123", "tok", session=bad).publish("Hi")
        self.assertIn("Invalid OAuth access token", str(ctx.exception))


class InstagramTests(unittest.TestCase):
    def test_container_then_publish_then_permalink(self):
        session = Session(reply(200, {"id": "C1"}), reply(200, {"id": "M1"}),
                          reply(200, {"permalink": "https://www.instagram.com/p/abc/"}))
        result = Instagram("IG1", "tok", "v23.0", session=session).publish("Caption", image_url="https://x/a.png",
                                                                            alt_text="A van")
        self.assertEqual([c[1].rsplit("/", 1)[-1] for c in session.calls], ["media", "media_publish", "M1"])
        self.assertEqual(session.calls[0][2]["data"]["alt_text"], "A van")
        self.assertEqual(session.calls[1][2]["data"]["creation_id"], "C1")
        self.assertEqual(result, {"id": "M1", "url": "https://www.instagram.com/p/abc/"})

    def test_text_only_is_a_manual_task(self):
        with self.assertRaises(SocialError) as ctx:
            Instagram("IG1", "tok", session=Session()).publish("Caption")
        self.assertTrue(ctx.exception.manual)


class LinkedInTests(unittest.TestCase):
    def test_text_and_article_posts(self):
        session = Session(reply(201, {}, {"x-restli-id": "urn:li:share:77"}))
        result = LinkedInOrganization("555", "tok", "202509", session=session).publish(
            "Insight", link="https://reckon.tech/blog", title="Blog")
        method, url, kw = session.calls[0]
        self.assertEqual(url, "https://api.linkedin.com/rest/posts")
        self.assertEqual(kw["json"]["author"], "urn:li:organization:555")
        self.assertEqual(kw["json"]["content"]["article"]["source"], "https://reckon.tech/blog")
        self.assertEqual(kw["headers"]["LinkedIn-Version"], "202509")
        self.assertEqual(kw["headers"]["X-Restli-Protocol-Version"], "2.0.0")
        self.assertEqual(result["url"], "https://www.linkedin.com/feed/update/urn:li:share:77")

    def test_image_is_uploaded_first(self):
        session = Session(reply(200, {"value": {"uploadUrl": "https://upload.linkedin/x", "image": "urn:li:image:9"}}),
                          reply(201), reply(201, {}, {"x-restli-id": "urn:li:share:78"}))
        LinkedInOrganization("urn:li:organization:555", "tok", session=session).publish("Hi", image_bytes=b"png",
                                                                                         alt_text="Logo")
        self.assertIn("initializeUpload", session.calls[0][1])
        self.assertEqual((session.calls[1][0], session.calls[1][2]["data"]), ("PUT", b"png"))
        self.assertEqual(session.calls[2][2]["json"]["content"]["media"], {"id": "urn:li:image:9", "altText": "Logo"})

    def test_unknown_platform_is_manual(self):
        with self.assertRaises(SocialError) as ctx:
            client_for("TikTok", "1", "tok")
        self.assertTrue(ctx.exception.manual)


class WiringTests(unittest.TestCase):
    def read(self, *parts):
        return APP.joinpath(*parts).read_text(encoding="utf-8")

    def test_governance(self):
        controller = self.read("reckon_sales_agent", "doctype", "sales_social_post", "sales_social_post.py")
        self.assertIn("approval_current(self.approval_fingerprint, post_payload(self))", controller)
        agent = self.read("agents", "social_agent.py")
        publish = agent.split("def publish(")[1].split("\ndef ")[0]
        self.assertLess(publish.index('decide("publish_approved_content"'), publish.index("client.publish("))
        self.assertLess(publish.index('social_enabled'), publish.index("client.publish("))
        self.assertIn("_manual_task(", publish)
        api = self.read("api.py")
        self.assertIn("_require_approver()", api.split("def approve_social_post(")[1].split("\ndef ")[0])
        self.assertIn("social_agent.publish_due_posts", self.read("hooks.py"))

    def test_registration(self):
        from reckon_sales_agent.constants import CHILD_DOCTYPES, COMPANY_DOCTYPES

        self.assertTrue({"Sales Social Account", "Sales Social Post"} <= set(COMPANY_DOCTYPES))
        self.assertIn("Sales Social Post Target", CHILD_DOCTYPES)
        sidebar = json.loads(self.read("workspace_sidebar", "sales_agent.json"))
        self.assertTrue({"Sales Social Post", "Sales Social Account"} <= {i.get("link_to") for i in sidebar["items"]})
        account = json.loads(self.read("reckon_sales_agent", "doctype", "sales_social_account", "sales_social_account.json"))
        token = next(f for f in account["fields"] if f["fieldname"] == "access_token")
        self.assertEqual(token["fieldtype"], "Password")  # stored encrypted, never returned
        settings = json.loads(self.read("reckon_sales_agent", "doctype", "sales_agent_platform_settings",
                                        "sales_agent_platform_settings.json"))
        defaults = {f["fieldname"]: f.get("default") for f in settings["fields"]}
        self.assertEqual(defaults["social_enabled"], "0")


if __name__ == "__main__":
    unittest.main()

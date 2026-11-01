"""Chat channels (Messenger, Instagram, website chat), social sign-in, new Studio agents, vendor-only AI (no bench)."""
import hashlib
import hmac
import json
import sys
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).parents[1]))

from reckon_sales_agent.agents.chat import (  # noqa: E402
    meta_events,
    origin_allowed,
    send_params,
    verify_meta_signature,
    visitor_fields,
    within_window,
)
from reckon_sales_agent.agents.omni import choose_channel  # noqa: E402
from reckon_sales_agent.agents.orchestrator import ASK, plan  # noqa: E402
from reckon_sales_agent.agents.social_connect import (  # noqa: E402
    authorize_url,
    linkedin_organizations,
    meta_accounts,
    read_state,
    sign_state,
)

APP = Path(__file__).parents[1] / "reckon_sales_agent"
DOCTYPES = APP / "reckon_sales_agent" / "doctype"
READY = {"has_profile": True, "brief_status": "Approved", "brief": "B1", "sources_ready": True, "ai": True}
NOW = datetime(2026, 10, 27, 12, 0)


def read(*parts):
    return APP.joinpath(*parts).read_text(encoding="utf-8")


def doctype(name):
    return json.loads((DOCTYPES / name / f"{name}.json").read_text(encoding="utf-8"))


def messenger(text="Price for 100 units?", **message):
    return {"object": "page", "entry": [{"id": "PAGE1", "messaging": [{
        "sender": {"id": "PSID9"}, "recipient": {"id": "PAGE1"}, "timestamp": 1792000000000,
        "message": {"mid": "m_1", "text": text, **message}}]}]}


class MetaWebhookTests(unittest.TestCase):
    def test_signature_is_the_app_secret_hmac_of_the_raw_body(self):
        body = json.dumps(messenger()).encode()
        good = "sha256=" + hmac.new(b"app-secret", body, hashlib.sha256).hexdigest()
        self.assertTrue(verify_meta_signature("app-secret", body, good))
        self.assertFalse(verify_meta_signature("app-secret", body + b" ", good))
        self.assertFalse(verify_meta_signature("", body, good))  # no app secret set: refuse everything
        self.assertFalse(verify_meta_signature("app-secret", body, None))

    def test_messages_are_parsed_and_echoes_skipped(self):
        [event] = meta_events(messenger())
        self.assertEqual((event["channel"], event["account_id"], event["contact_id"], event["external_id"]),
                         ("Messenger", "PAGE1", "PSID9", "m_1"))
        self.assertEqual(event["text"], "Price for 100 units?")
        self.assertEqual(meta_events(messenger(is_echo=True)), [])  # our own reply coming back
        ig = {**messenger(), "object": "instagram"}
        self.assertEqual(meta_events(ig)[0]["channel"], "Instagram")
        self.assertEqual(meta_events({"object": "whatsapp_business_account", "entry": []}), [])

    def test_attachments_and_receipts(self):
        [photo] = meta_events(messenger(text="", attachments=[{"type": "image"}]))
        self.assertEqual(photo["text"], "[sent image]")
        receipt = {"object": "page", "entry": [{"id": "P", "messaging": [{"sender": {"id": "U"},
                                                                           "recipient": {"id": "P"},
                                                                           "read": {"watermark": 1}}]}]}
        self.assertEqual(meta_events(receipt), [])

    def test_replies_only_inside_the_24_hour_window(self):
        self.assertTrue(within_window(NOW - timedelta(hours=23), NOW))
        self.assertFalse(within_window(NOW - timedelta(hours=25), NOW))
        self.assertFalse(within_window(None, NOW))
        self.assertEqual(send_params("PSID9", "Hi")["messaging_type"], "RESPONSE")


class WebChatTests(unittest.TestCase):
    def test_origins(self):
        self.assertTrue(origin_allowed("https://shop.example", ""))
        allowed = "https://www.example.com\nhttps://example.com/"
        self.assertTrue(origin_allowed("https://example.com", allowed))
        self.assertFalse(origin_allowed("https://evil.example", allowed))
        self.assertFalse(origin_allowed(None, allowed))

    def test_visitor_input(self):
        fields, error = visitor_fields({"text": "  Do you deliver   to Chattogram? ", "email": "A@B.COM",
                                        "phone": "+880 1711-000000", "name": "Rahim"})
        self.assertIsNone(error)
        self.assertEqual((fields["text"], fields["email"], fields["phone"]),
                         ("Do you deliver to Chattogram?", "a@b.com", "+8801711000000"))
        self.assertEqual(visitor_fields({"text": " "})[1], "Write a message.")
        self.assertIn("email", visitor_fields({"text": "hi", "email": "nope"})[1])

    def test_widget_is_safe_on_any_website(self):
        widget = (APP / "public" / "js" / "reckon_webchat.js").read_text(encoding="utf-8")
        self.assertIn('credentials: "omit"', widget)  # never the visitor's cookies for our site
        self.assertIn('"Content-Type": "text/plain"', widget)  # no pre-flight request
        self.assertIn("textContent = text", widget)  # replies are shown as text, never HTML
        api = read("api_channels.py")
        self.assertIn("@rate_limit(limit=20, seconds=300)", api)
        self.assertIn("origin_allowed(origin", api.split("def webchat_send(")[1])


class ChooseChatChannelTests(unittest.TestCase):
    def test_answer_where_they_wrote(self):
        prospect = {"email": "a@b.com", "phone": "+8801711000000", "whatsapp_consent": 1}
        chat = {"channel": "Messenger", "at": NOW - timedelta(hours=2)}
        self.assertEqual(choose_channel(prospect, None, NOW, chat)[0], "Messenger")
        old = {"channel": "Messenger", "at": NOW - timedelta(hours=30)}
        self.assertEqual(choose_channel(prospect, None, NOW, old)[0], "Email")  # Meta's window closed
        web = {"channel": "Web Chat", "at": NOW - timedelta(days=3)}
        self.assertEqual(choose_channel(prospect, None, NOW, web)[0], "Web Chat")
        newer_wa = NOW - timedelta(hours=1)
        self.assertEqual(choose_channel(prospect, newer_wa, NOW, chat)[0], "WhatsApp")
        self.assertEqual(choose_channel(prospect, None, NOW)[0], "Email")  # unchanged without a chat


class SocialConnectTests(unittest.TestCase):
    def test_state_is_signed_and_expires(self):
        state = sign_state({"c": "Acme", "u": "a@acme.com", "p": "meta"}, "s3cret", now=1000)
        self.assertEqual(read_state(state, "s3cret", now=1100)["c"], "Acme")
        self.assertIsNone(read_state(state, "s3cret", now=1000 + 901))  # expired
        self.assertIsNone(read_state(state, "other", now=1100))
        raw, mac = state.split(".")
        self.assertIsNone(read_state(raw[:-2] + "xx." + mac, "s3cret", now=1100))  # altered
        self.assertIsNone(read_state("", "s3cret"))

    def test_authorize_urls_ask_only_for_page_permissions(self):
        state = sign_state({"c": "Acme"}, "k", now=time.time())
        meta = urlparse(authorize_url("meta", "APP", "https://x/cb", state))
        query = parse_qs(meta.query)
        self.assertEqual(meta.netloc, "www.facebook.com")
        self.assertIn("pages_messaging", query["scope"][0])
        self.assertNotIn("email", query["scope"][0].split(","))
        linkedin = parse_qs(urlparse(authorize_url("linkedin", "CID", "https://x/cb", state)).query)
        self.assertEqual(linkedin["scope"][0], "w_organization_social r_organization_social rw_organization_admin")
        with self.assertRaises(ValueError):
            authorize_url("tiktok", "a", "b", "c")

    def test_pages_and_linked_instagram(self):
        accounts = meta_accounts([
            {"id": "1", "name": "Acme", "access_token": "T1", "tasks": ["MANAGE"],
             "instagram_business_account": {"id": "17841", "username": "acme.bd"}},
            {"id": "2", "name": "Read only", "access_token": "T2", "tasks": ["ANALYZE"]},
            {"id": "3", "name": "No token"},
        ])
        self.assertEqual([(a["platform"], a["account_id"]) for a in accounts],
                         [("Facebook Page", "1"), ("Instagram", "17841")])
        self.assertEqual(accounts[1]["linked_page_id"], "1")

    def test_linkedin_admin_organizations(self):
        acls = {"elements": [{"organization": "urn:li:organization:42", "state": "APPROVED"},
                             {"organization": "urn:li:organization:7", "state": "REQUESTED"},
                             {"organization": "urn:li:person:1"}]}
        self.assertEqual(linkedin_organizations(acls), ["42"])


class StudioAgentTests(unittest.TestCase):
    def test_new_agents_have_lanes(self):
        studio = read("api_agent_studio.py")
        for agent in ("Data Quality", "Conversations", "Meetings", "Social"):
            self.assertIn(f'"{agent}"', studio.split("AGENTS = (")[1].split(")")[0])
            self.assertIn(f'"{agent}": [', studio)  # its metrics
        options = next(f for f in doctype("sales_agent_activity")["fields"] if f["fieldname"] == "agent")["options"]
        for agent in ("Data Quality", "Conversations", "Meetings", "Social"):
            self.assertIn(agent, options.split("\n"))

    def test_steps_belong_to_the_new_agents(self):
        steps = plan({**READY, "autopilot": True, "data_issues": 3, "meetings_to_book": 1, "conversations_waiting": 2,
                      "replies_to_draft": 2, "social_waiting": 1, "channels_broken": 1})
        agents = {s.key: s.agent for s in steps}
        self.assertEqual(agents.get("data_quality"), "Data Quality")
        self.assertEqual(agents.get("meetings"), "Meetings")
        self.assertEqual(agents.get("conversations"), "Conversations")
        self.assertEqual(agents.get("draft_replies"), "Conversations")
        social = [s for s in steps if s.agent == "Social"]
        self.assertEqual({s.key for s in social}, {"approve_social", "channels"})
        self.assertTrue(all(s.kind == ASK for s in social))


class ChannelSchemaTests(unittest.TestCase):
    def test_reply_channels_and_chat_messages(self):
        channel = next(f for f in doctype("sales_outreach_message")["fields"] if f["fieldname"] == "channel")
        for name in ("Messenger", "Instagram", "Web Chat"):
            self.assertIn(name, channel["options"].split("\n"))
        chat = doctype("sales_chat_message")
        fields = {f["fieldname"]: f for f in chat["fields"]}
        self.assertEqual(fields["external_id"].get("unique"), 1)  # Meta retries webhooks
        self.assertEqual(fields["channel"]["options"], "Messenger\nInstagram\nWeb Chat\nSMS\nVoice\nWhatsApp")
        self.assertIn("Sales Chat Message", read("constants.py").split("COMPANY_DOCTYPES = (")[1].split(")")[0])
        self.assertIn('"sales-channels"', read("constants.py"))

    def test_social_tokens_are_secret(self):
        fields = {f["fieldname"]: f for f in doctype("sales_social_account")["fields"]}
        self.assertEqual((fields["access_token"]["fieldtype"], fields["refresh_token"]["fieldtype"]),
                         ("Password", "Password"))
        platform = {f["fieldname"]: f for f in doctype("sales_agent_platform_settings")["fields"]}
        for name in ("meta_app_secret", "meta_verify_token", "linkedin_client_secret"):
            self.assertEqual(platform[name]["fieldtype"], "Password")


class VendorOnlyAITests(unittest.TestCase):
    def test_company_ai_fields_are_the_system_providers(self):
        doc = doctype("sales_agent_settings")
        fields = {f["fieldname"]: f for f in doc["fields"]}
        names = ("ai_provider_override", "ai_model_override", "ai_api_key_override", "ai_base_url_override")
        for name in names:
            self.assertEqual(fields[name].get("permlevel"), 1)
        level_one = {p["role"] for p in doc["permissions"] if p.get("permlevel") == 1}
        self.assertEqual(level_one, {"System Manager", "Reckon Vendor Superuser"})
        controller = read("reckon_sales_agent", "doctype", "sales_agent_settings", "sales_agent_settings.py")
        self.assertIn("PLAN_FIELDS + AI_FIELDS", controller)
        platform = doctype("sales_agent_platform_settings")
        self.assertEqual({p["role"] for p in platform["permissions"]}, {"System Manager", "Reckon Vendor Superuser"})


if __name__ == "__main__":
    unittest.main()

"""Conversation desk (owner, status, tags, AI mode, human replies), SMS gateways, Twilio and the review fixes
(no bench)."""
import base64
import hashlib
import hmac
import json
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from reckon_sales_agent.agents.conversations import (  # noqa: E402
    clean_tag,
    effective_mode,
    parse_agents,
    parse_tags,
    pick_agent,
)
from reckon_sales_agent.agents.omni import auto_answer_decision, choose_channel  # noqa: E402
from reckon_sales_agent.agents.policy import ALLOW, NEEDS_APPROVAL  # noqa: E402
from reckon_sales_agent.providers.sms import (  # noqa: E402
    STOP,
    bd_number,
    build_request,
    parse_result,
    twilio_signature,
    valid_twilio,
)
from reckon_sales_agent.providers.twilio import (  # noqa: E402
    call_status,
    click_to_call_params,
    dial,
    gather,
    sendgrid_events,
    sendgrid_payload,
    twiml,
    verify_sendgrid,
)

APP = Path(__file__).parents[1] / "reckon_sales_agent"
NOW = datetime(2026, 10, 28, 12, 0)
GOOD = {"grounded": True, "needs_person": False}


def read(*parts):
    return APP.joinpath(*parts).read_text(encoding="utf-8")


class DeskTests(unittest.TestCase):
    def test_ai_mode(self):
        self.assertEqual(effective_mode("Company default", True), "Autopilot")
        self.assertEqual(effective_mode(None, False), "Suggest only")
        self.assertEqual(effective_mode("Human only", True), "Human only")
        self.assertEqual(effective_mode("Autopilot", False), "Autopilot")

    def test_assignment_goes_to_the_least_busy(self):
        agents = parse_agents("a@x.com\nnot an email\n B@X.com ")
        self.assertEqual(agents, ["a@x.com", "b@x.com"])
        self.assertEqual(pick_agent(agents, {"a@x.com": 3, "b@x.com": 1}), "b@x.com")
        self.assertEqual(pick_agent(agents, {}), "a@x.com")  # tie: list order
        self.assertIsNone(pick_agent([], {}))

    def test_tags(self):
        self.assertEqual(parse_tags(",vip,needs-human"), ["vip", "needs-human"])
        self.assertEqual(clean_tag("  VIP <script> "), "vip script")
        self.assertEqual(clean_tag("পাইকারি"), "পাইকারি")

    def test_human_takes_over_and_autopilot_hands_off(self):
        omni = read("agents", "omni.py")
        compose = omni.split("def compose(")[1]
        self.assertIn('convo.db_set("ai_mode", "Human only")', compose)
        self.assertIn("approve_message(message)", compose)  # sent as the person's approved message
        draft = omni.split("def draft_reply(")[1].split("\ndef ")[0]
        self.assertIn("handoff(company, prospect.name", draft)
        self.assertIn("allow_auto and bool(settings.get(\"chat_auto_answer\"))", draft)
        chat = read("agents", "chat.py").split("def auto_draft(")[1]
        self.assertIn('if mode == "Human only":', chat)
        self.assertIn('allow_auto=mode == "Autopilot"', chat)

    def test_a_person_asking_for_a_suggestion_gets_a_draft(self):
        # Review fix: with fast answers on, "AI suggest" used to send at once.
        suggest = read("api_conversations.py").split("def suggest(")[1].split("\ndef ")[0]
        self.assertNotIn("allow_auto", suggest)

    def test_autopilot_whatsapp_is_opt_in(self):
        self.assertEqual(auto_answer_decision(True, "WhatsApp", GOOD, [], "question").outcome, NEEDS_APPROVAL)
        both = ("Messenger", "Instagram", "Web Chat", "WhatsApp")
        self.assertEqual(auto_answer_decision(True, "WhatsApp", GOOD, [], "question", channels=both).outcome, ALLOW)
        self.assertEqual(auto_answer_decision(True, "Email", GOOD, [], "question", channels=both).outcome,
                         NEEDS_APPROVAL)

    def test_inbound_everywhere_opens_the_conversation(self):
        self.assertIn("touch_inbound(", read("agents", "chat.py").split("def receive_chat(")[1])
        engine = read("campaigns", "engine.py")
        self.assertIn("touch_inbound(message.company", engine.split("def receive_reply(")[1])
        self.assertIn('receive_chat(company, "WhatsApp"', engine.split("def _whatsapp_conversation(")[1])  # the shared chat path


class ReviewFixTests(unittest.TestCase):
    def test_web_chat_never_joins_an_existing_lead(self):
        source = read("agents", "chat.py").split("def _prospect_for(")[1].split("\ndef ")[0]
        self.assertIn('trusted = channel != "Web Chat"', source)
        self.assertIn("and email and trusted", source)
        self.assertIn("and phone and trusted", source)

    def test_no_redirects_for_recordings(self):
        self.assertIn("allow_redirects=False", read("agents", "voice.py"))

    def test_verify_token_constant_time(self):
        self.assertIn("hmac.compare_digest(offered, token)", read("api_channels.py"))

    def test_linkedin_pages(self):
        self.assertIn("&start={page * 100}", read("leads_bridge.py"))


class SmsTests(unittest.TestCase):
    def test_bangladeshi_gateways(self):
        self.assertEqual(bd_number("01711-000000"), "8801711000000")
        self.assertEqual(bd_number("+8801711000000"), "8801711000000")
        bulk = build_request("BulkSMSBD", to="+8801711000000", text="Hi", key="K", sender="8809617")
        self.assertEqual((bulk["url"], bulk["data"]["number"], bulk["data"]["senderid"]),
                         ("https://bulksmsbd.net/api/smsapi", "8801711000000", "8809617"))
        ssl = build_request("SSL Wireless", to="01711000000", text="Hi", key="T", sender="", account="SID",
                            reference="MSG-1")
        self.assertEqual((ssl["json"]["sid"], ssl["json"]["msisdn"], ssl["json"]["csms_id"]), ("SID", "8801711000000", "MSG-1"))
        self.assertEqual(parse_result("BulkSMSBD", 200, {"response_code": 202, "message_id": "9"}), (True, "9"))
        self.assertFalse(parse_result("BulkSMSBD", 200, {"response_code": 1007, "error_message": "Balance"})[0])
        self.assertEqual(parse_result("SSL Wireless", 200, {"status": "SUCCESS", "smsinfo": [{"reference_id": "R"}]}),
                         (True, "R"))

    def test_twilio_sms_and_rcs(self):
        rcs = build_request("Twilio (SMS and RCS)", to="+8801711000000", text="Hi", key="tok", sender="+1555",
                            account="AC1", messaging_service="MG1")
        self.assertEqual(rcs["data"].get("MessagingServiceSid"), "MG1")  # RCS where supported, SMS fallback
        self.assertNotIn("From", rcs["data"])
        self.assertEqual(rcs["auth"], ("AC1", "tok"))
        plain = build_request("Twilio (SMS and RCS)", to="8801711000000", text="Hi", key="t", sender="+1555", account="AC1")
        self.assertEqual((plain["data"]["From"], plain["data"]["To"]), ("+1555", "+8801711000000"))
        self.assertEqual(parse_result("Twilio (SMS and RCS)", 201, {"sid": "SM1"}), (True, "SM1"))

    def test_stop_words(self):
        for text in ("STOP", " stop ", "unsubscribe", "বন্ধ"):
            self.assertTrue(STOP.match(text), text)
        self.assertFalse(STOP.match("please stop by tomorrow"))

    def test_twilio_signature(self):
        # Twilio's documented example.
        url = "https://mycompany.com/myapp.php?foo=1&bar=2"
        params = {"CallSid": "CA1234567890ABCDE", "Caller": "+12349013030", "Digits": "1234", "From": "+12349013030",
                  "To": "+18005551212"}
        token = "12345"
        expected = base64.b64encode(hmac.new(token.encode(), (url + "".join(
            f"{k}{params[k]}" for k in sorted(params))).encode(), hashlib.sha1).digest()).decode()
        self.assertEqual(twilio_signature(token, url, params), expected)
        self.assertTrue(valid_twilio(token, url, params, expected))
        self.assertFalse(valid_twilio(token, url, {**params, "Digits": "9"}, expected))
        self.assertFalse(valid_twilio("", url, params, expected))

    def test_texting_us_opens_an_sms_reply(self):
        prospect = {"phone": "+8801711000000", "sms_consent": 1, "email": "a@b.com"}
        self.assertEqual(choose_channel(prospect, None, NOW, {"channel": "SMS", "at": NOW - timedelta(days=2)})[0], "SMS")
        no_consent = {**prospect, "sms_consent": 0}
        self.assertEqual(choose_channel(no_consent, None, NOW, {"channel": "SMS", "at": NOW})[0], "Email")


class TwilioTests(unittest.TestCase):
    def test_twiml_is_escaped(self):
        xml = twiml(gather("Price < 100 & more", "https://x/turn?company=A&B", "bn-BD"))
        self.assertIn("Price &lt; 100 &amp; more", xml)
        self.assertIn('action="https://x/turn?company=A&amp;B"', xml)
        self.assertIn('input="speech"', xml)
        self.assertTrue(xml.startswith('<?xml version="1.0" encoding="UTF-8"?><Response>'))
        self.assertIn('record="record-from-answer-dual"', dial("+880171", "+1555", True, "https://x/rec"))

    def test_click_to_call_rings_the_salesperson_first(self):
        params = click_to_call_params("+8801711111111", "+8801722222222", "+15550001111", "Karim & Sons",
                                      "https://x/status", True, "https://x/rec")
        self.assertEqual((params["To"], params["From"]), ("+8801711111111", "+15550001111"))
        self.assertIn("<Number>+8801722222222</Number>", params["Twiml"])
        self.assertIn("Karim &amp; Sons", params["Twiml"])
        self.assertIn("check_call(company)", read("providers", "twilio.py").split("def click_to_call(")[1])

    def test_statuses(self):
        self.assertEqual(call_status("no-answer"), "No Answer")
        self.assertEqual(call_status("in-progress"), "In Progress")
        self.assertEqual(call_status("busy"), "Busy")

    def test_voice_assistant_answers_only_what_it_may(self):
        source = read("providers", "twilio.py").split("def voice_answer(")[1].split("\ndef ")[0]
        self.assertIn('if data.get("needs_person") or not data.get("grounded"):', source)
        self.assertIn("MAX_TURNS", source)
        self.assertIn("handoff(company, prospect", source)
        self.assertIn("I am an AI assistant", read("api_twilio.py") + read("reckon_sales_agent", "doctype",
                      "sales_agent_settings", "sales_agent_settings.json"))

    def test_every_webhook_is_verified(self):
        api = read("api_twilio.py")
        for name in ("voice", "voice_turn", "call_status", "recording", "sms"):
            body = api.split(f"def {name}(")[1].split("\ndef ")[0]
            self.assertIn("_verified(settings)", body, name)
        self.assertIn("verify_sendgrid(", api.split("def sendgrid_events(")[1])

    def test_sendgrid(self):
        payload = sendgrid_payload("a@b.com", "sales@x.com", "X Ltd", "Hello", "<p>Hi</p>", "MSG-1")
        self.assertEqual(payload["personalizations"][0]["custom_args"], {"message": "MSG-1"})
        events = sendgrid_events([{"event": "bounce", "sg_event_id": "e1", "email": "a@b.com", "message": "MSG-1"},
                                  {"event": "bounce", "type": "blocked", "sg_event_id": "e2"},
                                  {"event": "open", "sg_event_id": "e3"}, {"event": "spamreport", "sg_event_id": "e4"}])
        self.assertEqual([(e["id"], e["type"], e["bounce_type"]) for e in events],
                         [("sg:e1", "bounce", "hard"), ("sg:e2", "bounce", "soft"), ("sg:e4", "spamreport", "hard")])

    def test_sendgrid_signature(self):
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import ec
        except ImportError:
            self.skipTest("cryptography not installed")
        key = ec.generate_private_key(ec.SECP256R1())
        public = base64.b64encode(key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
        body, stamp = json.dumps([{"event": "delivered"}]).encode(), "1700000000"
        signature = base64.b64encode(key.sign(stamp.encode() + body, ec.ECDSA(hashes.SHA256()))).decode()
        self.assertTrue(verify_sendgrid(public, signature, stamp, body))
        self.assertFalse(verify_sendgrid(public, signature, stamp, body + b" "))
        self.assertFalse(verify_sendgrid(None, signature, stamp, body))


class SchemaTests(unittest.TestCase):
    def test_conversation_doctype(self):
        doc = json.loads(read("reckon_sales_agent", "doctype", "sales_conversation", "sales_conversation.json"))
        fields = {f["fieldname"]: f for f in doc["fields"]}
        self.assertEqual(fields["ai_mode"]["options"], "Company default\nAutopilot\nSuggest only\nHuman only")
        self.assertEqual(fields["status"]["options"], "Open\nResolved")
        self.assertIn("Sales Conversation", read("constants.py").split("COMPANY_DOCTYPES = (")[1].split(")")[0])

    def test_secrets_are_passwords(self):
        doc = json.loads(read("reckon_sales_agent", "doctype", "sales_agent_settings", "sales_agent_settings.json"))
        kinds = {f["fieldname"]: f["fieldtype"] for f in doc["fields"]}
        for name in ("twilio_auth_token", "sendgrid_api_key", "sms_api_key"):
            self.assertEqual(kinds[name], "Password", name)


if __name__ == "__main__":
    unittest.main()

"""Engagement agent: intents, routine answers, WhatsApp service window, signed email events (no bench needed)."""
import json
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from reckon_sales_agent.agents.engagement import (  # noqa: E402
    ANSWER_SCHEMA,
    DRAFT,
    ESCALATE,
    SEND,
    answer_route,
    normalize_email_events,
    sign,
    verify_signature,
    within_service_window,
)
from reckon_sales_agent.campaigns.replies import SCHEMA, actions_for, classify_rules, resolve  # noqa: E402

APP = Path(__file__).parents[1] / "reckon_sales_agent"


class IntentTests(unittest.TestCase):
    def test_complaints_and_objections_in_english_and_bangla(self):
        self.assertEqual(classify_rules("This is spam, I will report you."), "complaint")
        self.assertEqual(classify_rules("আপনার বিরুদ্ধে অভিযোগ করব"), "complaint")
        self.assertEqual(classify_rules("Looks good but it is too expensive for us"), "objection")
        self.assertEqual(classify_rules("দাম বেশি"), "objection")
        self.assertEqual(classify_rules("Please unsubscribe me, this is spam"), "unsubscribe")  # opt-out first

    def test_rules_for_opt_outs_and_complaints_cannot_be_overturned(self):
        self.assertEqual(resolve("complaint", "interested"), "complaint")
        self.assertEqual(resolve("unsubscribe", "question"), "unsubscribe")
        self.assertEqual(resolve("question", "objection"), "objection")
        self.assertEqual(resolve("other", "irrelevant"), "irrelevant")

    def test_actions(self):
        complaint = actions_for("complaint")
        self.assertTrue(complaint["stop"] and complaint["suppress"])
        self.assertEqual(complaint["task"][0], "High")
        irrelevant = actions_for("irrelevant")
        self.assertFalse(irrelevant["stop"] or irrelevant["suppress"] or irrelevant["task"])
        self.assertIsNone(irrelevant["reschedule_days"])  # the sequence keeps its schedule
        self.assertTrue(actions_for("objection")["stop"])
        self.assertTrue({"objection", "complaint", "irrelevant"} <= set(SCHEMA["properties"]["classification"]["enum"]))


class AnswerRouteTests(unittest.TestCase):
    def test_sensitive_topics_always_go_to_a_person(self):
        for topic in ("pricing_exception", "contract", "complaint", "legal"):
            self.assertEqual(answer_route(True, [topic], [], True)[0], ESCALATE, topic)

    def test_unanswerable_issues_and_review(self):
        self.assertEqual(answer_route(False, ["product"], [], True)[0], ESCALATE)
        self.assertEqual(answer_route(True, ["product"], ["Step 0: figure"], True)[0], DRAFT)
        self.assertEqual(answer_route(True, ["product"], [], False)[0], DRAFT)
        self.assertEqual(answer_route(True, ["product", "pricing_standard"], [], True)[0], SEND)

    def test_answer_schema_is_strict(self):
        self.assertFalse(ANSWER_SCHEMA["additionalProperties"])
        self.assertEqual(set(ANSWER_SCHEMA["required"]), set(ANSWER_SCHEMA["properties"]))


class WhatsAppWindowTests(unittest.TestCase):
    def test_free_form_only_within_24_hours_of_their_message(self):
        now = datetime(2026, 10, 26, 12, 0)
        self.assertTrue(within_service_window(now - timedelta(hours=23, minutes=59), now))
        self.assertFalse(within_service_window(now - timedelta(hours=24), now))
        self.assertFalse(within_service_window(None, now))  # never wrote: templates only


class EmailEventTests(unittest.TestCase):
    BODY = json.dumps({"events": [
        {"id": "ev1", "type": "bounce", "bounce_type": "hard", "email": "Info@X.com", "message_id": "MSG-1"},
        {"id": "ev2", "type": "Bounce", "bounceType": "Permanent", "recipient": "a@b.com", "message": "MSG-2"},
        {"id": "ev3", "type": "bounce", "bounce_type": "soft", "email": "c@d.com", "message_id": "MSG-3"},
        {"id": "ev4", "event": "spamreport", "email": "e@f.com", "message_id": "MSG-4"},
        {"type": "bounce", "email": "no-id@x.com"},
        {"id": "ev5", "type": "opened", "email": "g@h.com"},
    ]}).encode()

    def test_signature(self):
        secret = "s3cret"
        signature = sign(secret, self.BODY)
        self.assertTrue(verify_signature(secret, self.BODY, signature))
        self.assertTrue(verify_signature(secret, self.BODY, f"sha256={signature}"))
        self.assertFalse(verify_signature(secret, self.BODY + b" ", signature))
        self.assertFalse(verify_signature("other", self.BODY, signature))
        self.assertFalse(verify_signature(None, self.BODY, signature))  # no secret configured: refuse everything
        self.assertFalse(verify_signature(secret, self.BODY, None))

    def test_events_are_normalised(self):
        events = normalize_email_events(json.loads(self.BODY))
        self.assertEqual([(e["id"], e["type"], e["hard"]) for e in events],
                         [("ev1", "bounce", True), ("ev2", "bounce", True), ("ev3", "bounce", False),
                          ("ev4", "complaint", False)])  # no id, and opens, are ignored
        self.assertEqual(events[0]["email"], "info@x.com")
        self.assertEqual(events[1]["message"], "MSG-2")


class WiringTests(unittest.TestCase):
    def read(self, *parts):
        return APP.joinpath(*parts).read_text(encoding="utf-8")

    def test_engine(self):
        engine = self.read("campaigns", "engine.py")
        receive = engine.split("def receive_reply(")[1].split("\ndef ")[0]
        self.assertLess(receive.index('"received:{source_key}"'), receive.index("classify_rules(text)"))  # dedupe first
        send = engine.split("def send_message(")[1].split("\ndef ")[0]
        self.assertIn("within_service_window(prospect.get(\"whatsapp_last_inbound\"), now_datetime())", send)
        self.assertIn("is_reply = bool(message.get(\"is_reply\"))", send)
        # Replies skip sequence checks, never the safety ones.
        self.assertLess(send.index("is_suppressed("), send.index("decide(\"send_approved_message\""))
        self.assertIn('if member.status != "Active":', engine.split("def _advance(")[1].split("\ndef ")[0])
        follow = engine.split("def classify_and_follow_up(")[1].split("\ndef ")[0]
        self.assertIn("answer_question(message, text, source_key)", follow)

    def test_a_follow_up_is_never_dropped(self):
        # Live test: an escalated question from an approved prospect with no CRM lead left no task at all.
        channels = self.read("providers", "channels.py")
        task = channels.split("def create_task(")[1].split("\ndef ")[0]
        self.assertNotIn("raise ChannelUnavailable", task)
        self.assertIn("_sync_approved(prospect_name)", task)
        self.assertIn("_todo(prospect_name", task)
        todo = channels.split("def _todo(")[1].split("\ndef ")[0]
        self.assertIn('"rsa_company": company', todo)  # tenant-scoped like every CRM record

    def test_redelivered_email_is_recognised_by_message_id(self):
        engine = self.read("campaigns", "engine.py")
        handler = engine.split("def handle_communication(")[1].split("\ndef ")[0]
        self.assertIn('doc.get("message_id")', handler)
        self.assertIn('f"email:{key}"', handler)

    def test_webhook_verifies_before_acting(self):
        api = self.read("api.py")
        hook = api.split("def email_events(")[1].split("\ndef ")[0]
        self.assertIn("allow_guest=True", api.split("def email_events(")[0][-80:])
        self.assertLess(hook.index("verify_signature("), hook.index("apply_email_event("))
        agent = self.read("agents", "engagement_agent.py")
        apply = agent.split("def apply_email_event(")[1].split("\ndef ")[0]
        self.assertLess(apply.index("idempotency_key"), apply.index("_suppress_member("))  # retries are no-ops
        self.assertIn("handle_communication_status", self.read("hooks.py"))

    def test_routine_answers_use_policy_and_approved_knowledge(self):
        agent = self.read("agents", "engagement_agent.py")
        answer = agent.split("def answer_question(")[1].split("\ndef ")[0]
        self.assertIn("approved_knowledge(message.company)", answer)
        self.assertIn('decide("answer_routine_question"', answer)
        self.assertIn("check_step(", answer)

    def test_fields(self):
        def fields(folder):
            doc = json.loads(self.read("reckon_sales_agent", "doctype", folder, f"{folder}.json"))
            return {f["fieldname"]: f for f in doc["fields"]}

        self.assertIn("auto_answer_questions", fields("sales_agent_settings"))
        self.assertEqual(fields("sales_agent_settings")["auto_answer_questions"]["default"], "0")  # off until chosen
        self.assertIn("email_webhook_secret", fields("sales_agent_platform_settings"))
        self.assertTrue({"whatsapp_template", "whatsapp_template_params"} <= set(fields("sales_campaign_step")))
        self.assertTrue({"is_reply", "auto_approved_by_policy", "whatsapp_template"} <= set(fields("sales_outreach_message")))
        self.assertIn("whatsapp_last_inbound", fields("sales_prospect"))
        self.assertIn("received", fields("sales_communication_event")["event_type"]["options"])


if __name__ == "__main__":
    unittest.main()

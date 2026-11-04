"""Brevo's transactional webhook: events map onto the engine's suppression rules (no network, no bench)."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from reckon_sales_agent.agents.engagement import normalize_email_events  # noqa: E402
from reckon_sales_agent.providers.brevo import normalize_events  # noqa: E402

APP = Path(__file__).parents[1] / "reckon_sales_agent"


def event(kind, **extra):
    base = {"event": kind, "email": "Lead@Example.com", "message-id": "<201798300811.5787683@relay.example>",
            "ts_epoch": 1767225600000, "id": 7}
    base.update(extra)
    return base


class BrevoEventMappingTests(unittest.TestCase):
    def test_hard_bounce_and_invalid_and_blocked_are_hard(self):
        for kind in ("hard_bounce", "invalid_email", "blocked"):
            [item] = normalize_events([event(kind)])
            self.assertEqual((item["type"], item["bounce_type"]), ("bounce", "hard"), kind)

    def test_soft_bounce_is_soft(self):
        [item] = normalize_events([event("soft_bounce")])
        self.assertEqual((item["type"], item["bounce_type"]), ("bounce", "soft"))

    def test_spam_and_unsubscribe_and_delivered(self):
        self.assertEqual(normalize_events([event("spam")])[0]["type"], "spamreport")
        self.assertEqual(normalize_events([event("unsubscribed")])[0]["type"], "unsubscribe")
        self.assertEqual(normalize_events([event("delivered")])[0]["type"], "delivered")

    def test_opens_and_clicks_are_ignored(self):
        self.assertEqual(normalize_events([event("opened"), event("click"), event("request")]), [])

    def test_the_message_id_links_the_event_to_the_outreach_message(self):
        [item] = normalize_events([event("hard_bounce")])
        self.assertEqual(item["message"], "<201798300811.5787683@relay.example>")

    def test_each_event_gets_its_own_id(self):
        first = normalize_events([event("delivered", ts_epoch=1)])[0]["id"]
        second = normalize_events([event("delivered", ts_epoch=2)])[0]["id"]
        self.assertNotEqual(first, second)

    def test_a_list_or_one_object_both_work(self):
        self.assertEqual(len(normalize_events([event("delivered"), event("spam")])), 2)
        self.assertEqual(len(normalize_events(event("delivered"))), 1)


class EngineShapeTests(unittest.TestCase):
    def test_the_engine_reads_brevo_events_as_it_reads_sendgrid_events(self):
        items = normalize_events([event("hard_bounce"), event("unsubscribed"), event("spam")])
        kinds = [(e["type"], e["hard"]) for e in normalize_email_events(items)]
        self.assertEqual(kinds, [("bounce", True), ("unsubscribe", False), ("complaint", False)])

    def test_unsubscribe_is_a_known_engine_event(self):
        source = (APP / "agents" / "engagement.py").read_text(encoding="utf-8")
        self.assertIn('"unsubscribe": "unsubscribe"', source)

    def test_unsubscribe_suppresses_and_stops_the_sequence(self):
        source = (APP / "agents" / "engagement_agent.py").read_text(encoding="utf-8")
        body = source.split("def apply_email_event(")[1].split("\ndef ")[0]
        self.assertIn('"unsubscribe": "unsubscribed"', body)
        self.assertIn("_suppress_member(message.company, member", body)
        self.assertIn('member.db_set({"status": "Stopped"', body)


class EndpointTests(unittest.TestCase):
    def test_the_endpoint_is_a_guest_post_checked_by_a_company_secret(self):
        source = (APP / "api_brevo.py").read_text(encoding="utf-8")
        self.assertIn('@frappe.whitelist(allow_guest=True, methods=["POST"])', source)
        self.assertIn("hmac.compare_digest", source)
        self.assertIn('get_password("brevo_webhook_secret"', source)
        self.assertIn("if not expected or not key", source)  # no secret set: refuse everything

    def test_the_secret_is_a_password_field_and_saveable(self):
        doc = json.loads((APP / "reckon_sales_agent" / "doctype" / "sales_agent_settings"
                          / "sales_agent_settings.json").read_text(encoding="utf-8"))
        fields = {f["fieldname"]: f for f in doc["fields"] if f.get("fieldname")}
        self.assertEqual(fields["brevo_webhook_secret"]["fieldtype"], "Password")
        self.assertIn("brevo_webhook_secret", doc["field_order"])
        source = (APP / "api_channels.py").read_text(encoding="utf-8")
        self.assertIn('"brevo_webhook_secret": "secret"', source)


if __name__ == "__main__":
    unittest.main()

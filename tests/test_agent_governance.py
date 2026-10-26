"""Agent governance: the autonomy matrix and approvals bound to exactly what was approved (no bench needed)."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from reckon_sales_agent.agents.approvals import (  # noqa: E402
    approval_current,
    campaign_payload,
    fingerprint,
    message_payload,
)
from reckon_sales_agent.agents.policy import (  # noqa: E402
    ALLOW,
    BLOCKED,
    DEFER,
    MATRIX,
    NEEDS_APPROVAL,
    agent_for,
    audience_grew_materially,
    decide,
)

APP = Path(__file__).parents[1] / "reckon_sales_agent"


class PolicyTests(unittest.TestCase):
    def test_permission_boundaries_ignore_model_confidence(self):
        for ctx in ({"suppressed": True}, {"consent": False}, {"kill_switch": True}):
            decision = decide("send_approved_message", {**ctx, "approved": True, "confidence": 0.99})
            self.assertEqual(decision.outcome, BLOCKED, ctx)
        self.assertEqual(decide("answer_routine_question", {"suppressed": True, "channel_allows": True}).outcome,
                         BLOCKED)

    def test_matrix_defaults(self):
        for action in ("research_company", "score_lead", "create_crm_lead", "generate_draft", "analyze_campaign"):
            self.assertEqual(decide(action).outcome, ALLOW, action)
        for action in ("launch_campaign", "expand_audience", "change_commercial_terms", "delete_records",
                       "handle_complaint", "handle_legal_request", "make_uncertain_claim"):
            self.assertEqual(decide(action, {"confidence": 1.0}).outcome, NEEDS_APPROVAL, action)
            self.assertEqual(decide(action, {"approved": True}).outcome, ALLOW, action)
        self.assertEqual(decide("something_new").outcome, NEEDS_APPROVAL)  # unknown: a person decides

    def test_sending_needs_a_current_approval_and_room_in_the_limits(self):
        self.assertEqual(decide("send_approved_message", {}).outcome, NEEDS_APPROVAL)
        self.assertEqual(decide("send_approved_message", {"approved": True, "approval_current": False}).outcome,
                         NEEDS_APPROVAL)
        self.assertEqual(decide("send_approved_message", {"approved": True, "within_limits": False}).outcome, DEFER)
        self.assertEqual(decide("send_approved_message", {"approved": True, "within_limits": True}).outcome, ALLOW)

    def test_routine_answers_only_where_the_channel_allows(self):
        self.assertEqual(decide("answer_routine_question", {}).outcome, NEEDS_APPROVAL)
        self.assertEqual(decide("answer_routine_question", {"channel_allows": True}).outcome, ALLOW)
        self.assertEqual(decide("answer_routine_question", {"channel_allows": True, "require_review": True}).outcome,
                         NEEDS_APPROVAL)

    def test_every_action_names_an_agent(self):
        self.assertEqual({agent for agent, _rule in MATRIX.values()},
                         {"Research", "Content", "Engagement", "Analytics", "Governance"})
        self.assertEqual(agent_for("discovery_completed"), "Research")
        self.assertEqual(agent_for("market_brief_approved"), "Research")
        self.assertEqual(agent_for("reply_interested"), "Engagement")
        self.assertEqual(agent_for("campaign_analyzed"), "Analytics")
        self.assertEqual(agent_for("campaign_approved"), "Governance")

    def test_material_audience_growth(self):
        self.assertFalse(audience_grew_materially(100, 140))
        self.assertTrue(audience_grew_materially(100, 150))
        self.assertTrue(audience_grew_materially(4, 14))  # at least 10 more
        self.assertFalse(audience_grew_materially(4, 12))
        self.assertFalse(audience_grew_materially(0, 500))  # nothing approved yet


CAMPAIGN = {
    "offer": "DMS for pharma distributors", "discovery_campaign": "DISC-1", "minimum_fit_score": 40,
    "start_date": "2026-11-01", "end_date": "2026-11-30", "daily_limit": 30,
    "steps": [{"step_no": 2, "channel": "WhatsApp", "delay_days": 3, "subject_template": "",
               "body_template": "Hi again", "use_ai_personalisation": 0},
              {"step_no": 1, "channel": "Email", "delay_days": 0, "subject_template": "Hello",
               "body_template": "Hi {{ business_name }}", "use_ai_personalisation": 1}],
}


class ApprovalBindingTests(unittest.TestCase):
    def test_any_change_to_content_audience_channel_or_schedule_voids_the_approval(self):
        stored = fingerprint(campaign_payload(CAMPAIGN))
        self.assertTrue(approval_current(stored, campaign_payload(CAMPAIGN)))
        changes = {
            "content": {"steps": [{**CAMPAIGN["steps"][1], "body_template": "Hi there"}, CAMPAIGN["steps"][0]]},
            "channel": {"steps": [{**CAMPAIGN["steps"][1], "channel": "SMS"}, CAMPAIGN["steps"][0]]},
            "audience": {"minimum_fit_score": 20},
            "audience source": {"discovery_campaign": "DISC-2"},
            "schedule": {"end_date": "2026-12-31"},
            "limit": {"daily_limit": 300},
            "offer": {"offer": "50% discount"},
        }
        for label, change in changes.items():
            self.assertFalse(approval_current(stored, campaign_payload({**CAMPAIGN, **change})), label)

    def test_step_order_in_the_table_does_not_matter(self):
        reordered = {**CAMPAIGN, "steps": list(reversed(CAMPAIGN["steps"]))}
        self.assertEqual(fingerprint(campaign_payload(CAMPAIGN)), fingerprint(campaign_payload(reordered)))

    def test_message_binding(self):
        message = {"channel": "Email", "recipient": "info@lazzpharma.com", "subject": "Hello", "body": "<p>Hi</p>"}
        stored = fingerprint(message_payload(message))
        self.assertTrue(approval_current(stored, message_payload(message)))
        self.assertFalse(approval_current(stored, message_payload({**message, "body": "<p>Hi, 50% off</p>"})))
        self.assertFalse(approval_current(stored, message_payload({**message, "recipient": "other@x.com"})))
        self.assertTrue(approval_current(None, message_payload(message)))  # approved before binding existed


class WiringTests(unittest.TestCase):
    def test_send_path_checks_policy_and_bound_approvals(self):
        engine = (APP / "campaigns" / "engine.py").read_text(encoding="utf-8")
        send = engine.split("def send_message(")[1].split("\ndef ")[0]
        self.assertIn('decide("send_approved_message"', send)
        self.assertIn("approval_current(campaign.approval_fingerprint, campaign_payload(campaign))", send)
        self.assertIn("approval_current(message.get(\"approval_fingerprint\"), message_payload(message))", send)
        self.assertIn("fingerprint(message_payload(message))", engine.split("def approve_message(")[1].split("\ndef ")[0])
        api = (APP / "api.py").read_text(encoding="utf-8").split("def approve_campaign(")[1].split("\ndef ")[0]
        self.assertIn("fingerprint(campaign_payload(doc))", api)
        controller = (APP / "reckon_sales_agent" / "doctype" / "sales_campaign" / "sales_campaign.py").read_text(
            encoding="utf-8")
        self.assertIn("campaign_payload(self)", controller)

    def test_approval_is_voided_for_every_editor(self):
        # Live test: an administrator edited an approved post and it stayed Approved. Admins are no exception.
        for folder, marker in (("sales_campaign", "if changed and self.status in"),
                               ("sales_social_post", 'if (self.status in ("Approved", "Scheduled")')):
            controller = (APP / "reckon_sales_agent" / "doctype" / folder / f"{folder}.py").read_text(encoding="utf-8")
            condition = controller.split(marker)[1].split(":\n")[0]
            self.assertNotIn("is_system_actor", condition, folder)
            self.assertIn("flags.ignore_permissions", condition, folder)  # only the engine's own writes are exempt
        message = (APP / "reckon_sales_agent" / "doctype" / "sales_outreach_message" / "sales_outreach_message.py")
        self.assertIn('self.status, self.approved_by, self.approval_fingerprint = "Draft", None, None',
                      message.read_text(encoding="utf-8"))

    def test_doctype_fields(self):
        def fields(folder):
            doc = json.loads((APP / "reckon_sales_agent" / "doctype" / folder / f"{folder}.json").read_text(
                encoding="utf-8"))
            return {f["fieldname"]: f for f in doc["fields"]}

        self.assertIn("approval_fingerprint", fields("sales_campaign"))
        self.assertIn("approved_audience_size", fields("sales_campaign"))
        self.assertIn("approval_fingerprint", fields("sales_outreach_message"))
        self.assertIn("Governance", fields("sales_agent_activity")["agent"]["options"])
        self.assertIn("approval_invalidated", fields("sales_communication_event")["event_type"]["options"])
        self.assertIn("plan_cursor", fields("sales_discovery_campaign"))


if __name__ == "__main__":
    unittest.main()

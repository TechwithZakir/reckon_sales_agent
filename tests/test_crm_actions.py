"""CRM actions, Phase B: what the copilot may propose, what runs now, and what waits for approval (no bench)."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from reckon_sales_agent.agents.crm_actions import (  # noqa: E402
    APPROVAL,
    AUTOMATIC,
    allowed_for,
    field_change,
    validate_payload,
)
from reckon_sales_agent.agents.orchestrator import ASK, plan  # noqa: E402

APP = Path(__file__).parents[1] / "reckon_sales_agent"


class ValidationTests(unittest.TestCase):
    def test_a_task_needs_a_title_and_a_valid_date(self):
        self.assertEqual(validate_payload("create_task", {"title": " Call back ", "due_date": "2026-12-01"}),
                         {"title": "Call back", "due_date": "2026-12-01"})
        with self.assertRaises(ValueError):
            validate_payload("create_task", {"title": ""})
        with self.assertRaises(ValueError):
            validate_payload("create_task", {"title": "x", "due_date": "01/12/2026"})

    def test_probability_is_a_percentage(self):
        self.assertEqual(validate_payload("set_probability", {"probability": "70"}), {"probability": 70.0})
        with self.assertRaises(ValueError):
            validate_payload("set_probability", {"probability": 120})

    def test_value_cannot_be_negative_or_text(self):
        with self.assertRaises(ValueError):
            validate_payload("set_deal_value", {"value": -5})
        with self.assertRaises(ValueError):
            validate_payload("set_deal_value", {"value": "lots"})

    def test_reassign_needs_a_user(self):
        with self.assertRaises(ValueError):
            validate_payload("reassign", {"user": "sales"})

    def test_unknown_actions_are_refused(self):
        with self.assertRaises(ValueError):
            validate_payload("delete_lead", {})


class RulesTests(unittest.TestCase):
    def test_only_tasks_and_notes_run_automatically(self):
        self.assertEqual(set(AUTOMATIC), {"create_task", "add_note"})

    def test_every_change_to_a_deal_or_lead_needs_approval(self):
        for action in ("set_stage", "set_deal_value", "set_probability", "set_close_date", "reassign"):
            self.assertIn(action, APPROVAL)
            self.assertNotIn(action, AUTOMATIC)

    def test_deal_changes_are_only_for_deals(self):
        self.assertTrue(allowed_for("CRM Deal", "set_stage"))
        self.assertFalse(allowed_for("CRM Lead", "set_stage"))
        self.assertTrue(allowed_for("CRM Lead", "create_task"))
        self.assertFalse(allowed_for("Sales Prospect", "create_task"))

    def test_the_change_sets_the_crm_field(self):
        self.assertEqual(field_change("CRM Deal", "set_stage", {"stage": "Negotiation"}), {"status": "Negotiation"})
        self.assertEqual(field_change("CRM Lead", "reassign", {"user": "a@b.co"}), {"lead_owner": "a@b.co"})
        self.assertEqual(field_change("CRM Deal", "reassign", {"user": "a@b.co"}), {"deal_owner": "a@b.co"})


class ActivityLogTests(unittest.TestCase):
    def test_every_value_the_crm_actions_log_is_allowed_by_the_activity_log(self):
        # The log's Select fields reject unknown values, so a wrong value fails the whole action.
        source = (APP / "agents" / "crm_actions.py").read_text(encoding="utf-8")
        activity = json.loads((APP / "reckon_sales_agent" / "doctype" / "sales_agent_activity"
                               / "sales_agent_activity.json").read_text(encoding="utf-8"))
        fields = {f["fieldname"]: (f.get("options") or "").split(chr(10)) for f in activity["fields"]}
        self.assertIn('actor_type="user"', source)
        self.assertIn("user", fields["actor_type"])
        self.assertIn('agent="CRM"', source)
        self.assertIn("CRM", fields["agent"])


class PlannerTests(unittest.TestCase):
    def test_pending_changes_are_asked_about(self):
        crm = [s for s in plan({"crm_pending": 2}) if s.key == "crm_pending"]
        self.assertEqual(len(crm), 1)
        self.assertEqual(crm[0].kind, ASK)
        self.assertIn("2 CRM changes to approve", crm[0].title)

    def test_nothing_pending_nothing_asked(self):
        self.assertFalse([s for s in plan({"crm_pending": 0}) if s.key == "crm_pending"])


class EndpointTests(unittest.TestCase):
    def test_decisions_are_for_managers_and_their_company(self):
        api = (APP / "api_crm.py").read_text(encoding="utf-8")
        body = api.split("def decide(")[1].split("\n@")[0]
        self.assertIn("if not _can_manage():", body)
        self.assertIn("belongs to another Company", body)

    def test_proposals_check_the_company_and_the_entitlement(self):
        api = (APP / "api_crm.py").read_text(encoding="utf-8")
        body = api.split("def propose(")[1].split("\n@")[0]
        self.assertIn("assert_entitled(company)", body)


if __name__ == "__main__":
    unittest.main()

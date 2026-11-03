"""CRM copilot wiring: the meeting suggestion, the CRM lane in the planner and Agent Studio (no bench)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from reckon_sales_agent.agents.crm_copilot import suggest_meeting  # noqa: E402
from reckon_sales_agent.agents.orchestrator import ASK, plan  # noqa: E402

APP = Path(__file__).parents[1] / "reckon_sales_agent"


class MeetingSuggestionTests(unittest.TestCase):
    def test_a_deal_in_demo_suggests_a_meeting(self):
        self.assertTrue(suggest_meeting({"deal": {"status": "Demo/Making"}, "timeline": []}))

    def test_a_request_for_a_call_suggests_a_meeting(self):
        timeline = [{"direction": "in", "text": "Can we have a call tomorrow?"}]
        self.assertTrue(suggest_meeting({"deal": None, "timeline": timeline}))

    def test_an_ordinary_message_does_not(self):
        timeline = [{"direction": "in", "text": "Thanks, got the price list."}]
        self.assertFalse(suggest_meeting({"deal": {"status": "Qualification"}, "timeline": timeline}))


class CrmLaneTests(unittest.TestCase):
    def test_deals_needing_a_next_step_are_asked_about(self):
        steps = plan({"crm_stalled": 3})
        crm = [s for s in steps if s.agent == "CRM"]
        self.assertEqual(len(crm), 1)
        self.assertEqual(crm[0].kind, ASK)
        self.assertIn("3 deals need a next step", crm[0].title)

    def test_no_stalled_deals_no_crm_step(self):
        self.assertFalse([s for s in plan({"crm_stalled": 0}) if s.agent == "CRM"])

    def test_agent_studio_has_the_crm_lane(self):
        api = (APP / "api_agent_studio.py").read_text(encoding="utf-8")
        self.assertIn('"Analytics", "CRM")', api)
        self.assertIn('"CRM": "Keeps CRM deals moving', api)


if __name__ == "__main__":
    unittest.main()

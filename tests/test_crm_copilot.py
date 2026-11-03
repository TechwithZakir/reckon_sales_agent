"""CRM copilot, Phase A: read-only, and the rules summary is right on the facts (no bench)."""
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from reckon_sales_agent.agents.crm_copilot import rules_summary  # noqa: E402

MODULE = Path(__file__).parents[1] / "reckon_sales_agent" / "agents" / "crm_copilot.py"


class RulesSummaryTests(unittest.TestCase):
    def test_a_deal_with_an_open_task_reports_the_task(self):
        out = rules_summary({"deal": {"status": "Proposal/Quotation", "probability": 50, "deal_value": 100000,
                                      "expected_closure_date": None, "next_step": None},
                             "lead": None, "open_tasks": [{"title": "Send the quote"}], "timeline": []})
        self.assertIn("Proposal/Quotation (50%)", out["summary"])
        self.assertEqual(out["next_step"], "Finish the open task: Send the quote.")
        self.assertEqual(out["source"], "rules")

    def test_a_passed_close_date_is_a_risk(self):
        past = (date.today() - timedelta(days=3)).isoformat()
        out = rules_summary({"deal": {"status": "Negotiation", "probability": 70, "expected_closure_date": past},
                             "lead": None, "open_tasks": [], "timeline": []})
        self.assertIn("The expected close date has passed.", out["risks"])

    def test_a_won_deal_with_a_past_date_is_not_a_risk(self):
        past = (date.today() - timedelta(days=3)).isoformat()
        out = rules_summary({"deal": {"status": "Won", "probability": 100, "expected_closure_date": past},
                             "lead": None, "open_tasks": [{"title": "Onboard"}], "timeline": []})
        self.assertNotIn("The expected close date has passed.", out["risks"])

    def test_they_wrote_last_means_reply_now(self):
        out = rules_summary({"deal": None, "lead": {"status": "Contacted"}, "open_tasks": [],
                             "timeline": [{"direction": "in"}]})
        self.assertEqual(out["next_step"], "They wrote last: reply now.")

    def test_no_crm_record_yet(self):
        out = rules_summary({"deal": None, "lead": None, "open_tasks": [], "timeline": []})
        self.assertEqual(out["summary"], "This lead is not in CRM yet.")


class ReadOnlyTests(unittest.TestCase):
    def test_the_copilot_writes_nothing(self):
        source = MODULE.read_text(encoding="utf-8")
        for write in (".insert(", ".save(", "set_value(", "db_set(", "delete(", "new_doc("):
            self.assertNotIn(write, source, write)

    def test_the_endpoint_checks_read_access_first(self):
        api = (Path(__file__).parents[1] / "reckon_sales_agent" / "api_conversations.py").read_text(encoding="utf-8")
        body = api.split("def copilot_summary(")[1]
        self.assertIn('get_tenant_doc("Sales Prospect", prospect, "read")', body)


if __name__ == "__main__":
    unittest.main()

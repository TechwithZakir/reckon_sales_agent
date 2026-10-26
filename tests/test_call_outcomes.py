"""Call outcomes and call analytics for phone-first pilots (no bench needed)."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from reckon_sales_agent.agents.analytics import call_summary  # noqa: E402
from reckon_sales_agent.campaigns.calls import EVENT, MAX_RETRIES, OUTCOMES, REACHED, plan_outcome  # noqa: E402
from reckon_sales_agent.campaigns.replies import POSITIVE  # noqa: E402

APP = Path(__file__).parents[1] / "reckon_sales_agent"


class PlanTests(unittest.TestCase):
    def test_each_outcome_has_its_next_step(self):
        interested = plan_outcome("interested")
        self.assertTrue(interested["stop"] and interested["crm_lead"] and interested["positive"])
        self.assertIn(interested["classification"], POSITIVE)  # counts as positive in attribution
        callback = plan_outcome("callback")
        self.assertTrue(callback["callback"])
        self.assertFalse(callback["stop"])
        not_interested = plan_outcome("not_interested")
        self.assertTrue(not_interested["stop"])
        self.assertNotIn(not_interested["classification"], POSITIVE)
        self.assertTrue(plan_outcome("wrong_number")["drop_phone"])
        self.assertFalse(plan_outcome("wrong_number")["stop"])  # email steps may still reach the business

    def test_no_answer_retries_twice_then_moves_on(self):
        self.assertEqual(plan_outcome("no_answer", 0)["new_call_in_days"], 1)
        self.assertEqual(plan_outcome("no_answer", MAX_RETRIES - 1)["new_call_in_days"], 1)
        self.assertIsNone(plan_outcome("no_answer", MAX_RETRIES)["new_call_in_days"])

    def test_unknown_outcome(self):
        with self.assertRaises(ValueError):
            plan_outcome("maybe")

    def test_events_exist_on_the_doctype(self):
        doc = json.loads((APP / "reckon_sales_agent" / "doctype" / "sales_communication_event"
                          / "sales_communication_event.json").read_text(encoding="utf-8"))
        options = next(f for f in doc["fields"] if f["fieldname"] == "event_type")["options"].split("\n")
        for outcome in OUTCOMES:
            self.assertIn(EVENT[outcome], options)
        self.assertEqual(set(REACHED), {"interested", "callback", "not_interested"})


class AnalyticsTests(unittest.TestCase):
    def test_call_summary(self):
        data = call_summary(10, {"call_interested": 2, "call_callback": 1, "call_not_interested": 3,
                                 "call_no_answer": 3, "call_wrong_number": 1})
        self.assertEqual((data["calls"], data["logged"], data["reached"], data["interested"]), (10, 10, 6, 2))
        self.assertEqual((data["reach_rate"], data["interest_rate"]), (60.0, 33.3))
        self.assertEqual(call_summary(5, {})["reach_rate"], 0.0)


class WiringTests(unittest.TestCase):
    def read(self, *parts):
        return APP.joinpath(*parts).read_text(encoding="utf-8")

    def test_recording_is_idempotent_and_closes_the_task(self):
        calls = self.read("campaigns", "calls.py").split("def record_call_outcome(")[1]
        self.assertLess(calls.index('if frappe.db.exists("Sales Communication Event", {"idempotency_key": key})'),
                        calls.index("record_event(message, EVENT[outcome], key"))
        self.assertIn("_close_task(task_doctype, task_name)", calls)
        self.assertIn("_confirm_and_sync(prospect)", calls)  # interest on a call confirms the business

    def test_the_call_confirms_identity_for_the_crm(self):
        confirm = self.read("campaigns", "calls.py").split("def _confirm_and_sync(")[1]
        self.assertIn('"source": "phone_call"', confirm)
        self.assertIn('"retention_days": None', confirm)
        self.assertIn('prospect.review_status != "Approved"', confirm)

    def test_studio_records_outcomes_for_the_users_company_only(self):
        api = self.read("api_agent_studio.py")
        act = api.split('if action == "call_outcome":')[1].split('if action == "task_done":')[0]
        self.assertIn('get_tenant_doc("Sales Outreach Message", message, "read")', act)
        self.assertIn('frappe.get_doc(doctype, task).check_permission("write")', act)
        self.assertIn('"call_interested"', api.split("funnel = [")[1].split("]\n")[0])
        script = self.read("reckon_sales_agent", "page", "sales_agent", "sales_agent.js")
        self.assertIn('this.act("call_outcome"', script)
        self.assertIn('fieldname: "callback_on", fieldtype: "Date"', script)

    def test_pilot_report_counts_calls_without_sql_functions(self):
        report = self.read("agents", "analytics_agent.py").split("def pilot_report(")[1]
        self.assertIn("call_summary(", report)
        self.assertNotIn("count(name)", report)
        self.assertIn('"calls": calls', report)


if __name__ == "__main__":
    unittest.main()

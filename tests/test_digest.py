"""Daily digest for managers and salespeople (no bench needed)."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from reckon_sales_agent.agents.digest import caller_digest, manager_digest, work_lines  # noqa: E402

APP = Path(__file__).parents[1] / "reckon_sales_agent"
URL = "https://distribution.reckon.tech/desk/sales-agent"


class BuilderTests(unittest.TestCase):
    def test_work_lines_sum_related_actions_and_skip_zeros(self):
        lines = work_lines({"research_done": 3, "research_partial": 1, "prospect_triaged": 20, "call_interested": 1,
                            "call_no_answer": 2, "autopilot_run": 24}, new_leads=25)
        self.assertEqual(lines, ["25 new leads found", "4 websites researched", "20 leads judged by AI",
                                 "3 calls logged", "1 interested on a call"])
        self.assertEqual(work_lines({}), [])

    def test_manager_digest(self):
        subject, html = manager_digest(
            "Reckon Technologies Ltd.", ["25 new leads found"],
            [{"title": "Review leads", "detail": "21 lead(s) need your decision."},
             {"title": "Approve campaign: Pilot <Pharma>", "detail": ""}],
            [{"name": "Pilot · Pharma", "summary": "Contacted 5 vs hold-out 0."}], URL)
        self.assertEqual(subject, "Sales agents: 2 decision(s) waiting")
        self.assertIn("Pilot &lt;Pharma&gt;", html)  # names are escaped
        self.assertIn(f'href="{URL}"', html)
        self.assertIn("Contacted 5 vs hold-out 0.", html)
        quiet_subject, quiet = manager_digest("X", [], [], [], URL)
        self.assertEqual(quiet_subject, "Sales agents: nothing needs you today")
        self.assertIn("A quiet day", quiet)

    def test_caller_digest(self):
        calls = [{"business": "Biorex Healthcare Ltd.", "phone": "+8801716865535", "due": "2026-10-27",
                  "title": "Call: Introduce Reckon DMS"},
                 {"business": "Drug Mart", "phone": "+8801706579966", "due": "2026-10-26"}]
        subject, html = caller_digest("Rahim", calls, URL, "2026-10-27")
        self.assertEqual(subject, "Today's calls: 2 (1 overdue)")
        self.assertIn('href="tel:+8801716865535"', html)
        self.assertEqual(html.count("<i>overdue</i>"), 1)
        self.assertEqual(caller_digest("R", calls[:1], URL, "2026-10-27")[0], "Today's calls: 1")


class WiringTests(unittest.TestCase):
    def read(self, *parts):
        return APP.joinpath(*parts).read_text(encoding="utf-8")

    def test_scheduled_once_a_day_per_person(self):
        self.assertIn('"0 8 * * *": ["reckon_sales_agent.agents.digest.send_all"]', self.read("hooks.py"))
        digest = self.read("agents", "digest.py")
        send = digest.split("def send_company(")[1].split("\ndef ")[0]
        self.assertIn("if force or not _already_sent(company, user, \"manager\")", send)
        self.assertIn("if force or not _already_sent(company, user, \"caller\")", send)
        self.assertIn('"daily_digest": 1', digest.split("def send_all(")[1])
        self.assertIn("call_message(", digest.split("def _calls_by_person(")[1])  # calls only, not reply tasks

    def test_preview_from_the_studio(self):
        act = self.read("api_agent_studio.py").split('if action == "send_digest":')[1].split("if action ==")[0]
        self.assertIn("only_user=frappe.session.user", act)
        self.assertIn("as_manager=_can_manage()", act)  # a salesperson never gets the manager digest
        script = self.read("reckon_sales_agent", "page", "sales_agent", "sales_agent.js")
        self.assertIn('action: "send_digest"', script)
        self.assertIn("ags-daily", script)

    def test_settings(self):
        doc = json.loads(self.read("reckon_sales_agent", "doctype", "sales_agent_settings",
                                   "sales_agent_settings.json"))
        fields = {f["fieldname"]: f for f in doc["fields"]}
        self.assertEqual(fields["daily_digest"]["default"], "1")
        self.assertIn("digest_recipients", fields)
        self.assertEqual([f["fieldname"] for f in doc["fields"]], doc["field_order"])


if __name__ == "__main__":
    unittest.main()

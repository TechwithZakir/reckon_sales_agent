"""Phone-first pilots with AI call scripts, and one-click acceptance of the AI's lead suggestions (no bench needed)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from reckon_sales_agent.agents.content import check_step, clean_steps, default_plan  # noqa: E402
from reckon_sales_agent.agents.orchestrator import DO, pilot_channels, plan  # noqa: E402

APP = Path(__file__).parents[1] / "reckon_sales_agent"
READY = {"has_profile": True, "brief_status": "Approved", "brief": "B1", "sources_ready": True, "ai": True}


class ChannelTests(unittest.TestCase):
    def test_phone_only_segments_lead_with_a_call(self):
        # Seen live: most approved distributors list a phone and no email.
        self.assertEqual(pilot_channels(1, 6), ["Call Task", "Email"])
        self.assertEqual(pilot_channels(3, 6), ["Email", "Call Task"])
        self.assertEqual(pilot_channels(0, 0), ["Call Task", "Email"])
        self.assertEqual(pilot_channels(5, 6, whatsapp=True), ["Email", "Call Task", "WhatsApp"])
        self.assertEqual([p["channel"] for p in default_plan(3, ["Call Task", "Email"])],
                         ["Call Task", "Email", "Call Task"])

    def test_call_scripts_keep_a_subject_and_get_checked(self):
        plan_rows = default_plan(2, ["Call Task", "Email"])
        rows = clean_steps({"steps": [
            {"step_no": 1, "subject": "introduce our DMS to {{business_name}}",
             "body": "Opening: ...\nবাংলা: ...\n{{personal_line}}\nQuestions: how do you take orders?"},
            {"step_no": 2, "subject": "Following up", "body": "Hi {{business_name}} team"}]}, plan_rows)
        self.assertEqual(rows[0]["subject_template"], "introduce our DMS to {{business_name}}")  # the CRM task title
        self.assertEqual(rows[0]["use_ai_personalisation"], 1)
        long_script = {"step_no": 1, "channel": "Call Task", "subject_template": "x", "body_template": "word " * 600}
        self.assertTrue(any("Call Task under 2500" in i for i in check_step(long_script, "", "", [])))
        self.assertTrue(any("guarantee" in i for i in check_step(
            {**long_script, "body_template": "We guarantee growth."}, "", "", [])))

    def test_steps_never_refer_to_steps_a_lead_may_skip(self):
        # Live test: a follow-up call script said "I emailed a few days ago" to leads that have no email.
        from reckon_sales_agent.agents.content import SEQUENCE_SYSTEM

        self.assertIn("never refer to an earlier message, email or call", SEQUENCE_SYSTEM)

    def test_campaign_is_drafted_for_phone_only_leads_too(self):
        segment = {"discovery": "DISC-1", "label": "FMCG", "count": 6, "with_email": 1}
        step = next(s for s in plan({**READY, "autopilot": True, "segments_ready": [segment]})
                    if s.key == "draft_campaign")
        self.assertEqual(step.kind, DO)
        self.assertEqual((step.ref["count"], step.ref["with_email"]), (6, 1))
        self.assertIn("1 with email", step.detail)


class WiringTests(unittest.TestCase):
    def read(self, *parts):
        return APP.joinpath(*parts).read_text(encoding="utf-8")

    def test_a_call_needs_a_phone_not_a_crm_lead(self):
        # Live test: 9 of 12 approved leads had a phone but could not enter the CRM (source retention).
        reach = self.read("providers", "channels.py").split("def reachability(")[1].split("\ndef ")[0]
        call = reach.split('if channel == "Call Task":')[1].split("if channel in TASK_CHANNELS")[0]
        self.assertIn("if not normalize_phone(prospect.phone):", call)
        self.assertIn("prospect.crm_lead or prospect.name", call)
        self.assertNotIn("Not in the CRM yet", call)
        task = self.read("providers", "channels.py").split("def create_task(")[1].split("\ndef ")[0]
        self.assertIn("return _todo(prospect_name", task)  # no CRM lead: a ToDo on the prospect
        ready = self.read("agents", "orchestrator.py").split("def _segments_ready(")[1].split("\ndef ")[0]
        self.assertIn("(r.email or r.phone)", ready)

    def test_call_scripts_name_the_caller_and_always_have_a_talking_point(self):
        draft = self.read("campaigns", "engine.py").split("def draft_message(")[1].split("\ndef ")[0]
        task = draft.split("if channel in TASK_CHANNELS:")[1].split("_ok, _reason")[0]
        # The named salesperson's first name (set in setup), else a placeholder they fill in themselves.
        self.assertIn('settings.get("task_assignee")', task)
        self.assertIn('or "[your name]"', task)
        self.assertIn('prospect.get("ai_triage_reason")', task)

    def test_call_tasks_carry_the_number_and_go_to_the_named_salesperson(self):
        # Live test: the first five call ToDos had no phone number, all went to Administrator and the inbox
        # did not list them.
        channels = self.read("providers", "channels.py")
        task = channels.split("def create_task(")[1].split("\ndef ")[0]
        self.assertLess(task.index("_contact_line(prospect_name)"), task.index("return _todo("))
        self.assertIn("_assignee(prospect_name, settings)", task)
        self.assertIn("_assignee(prospect_name, settings)", channels.split("def _todo(")[1])
        self.assertIn("owner_for(prospect_name, settings)", channels.split("def _assignee(")[1].split("\ndef ")[0])
        # The named salesperson still owns a lead when no team routing or earlier owner applies.
        self.assertIn('settings.get("task_assignee")', self.read("agents", "ownership.py").split("def owner_for(")[1])
        api = self.read("api_agent_studio.py")
        self.assertIn('item["todos"]', api)
        done = api.split('if action == "task_done":')[1].split("if action ==")[0]
        self.assertIn('todo.get("rsa_company") != company', done)  # only the Company's own tasks
        self.assertIn('todo.check_permission("write")', done)
        script = self.read("reckon_sales_agent", "page", "sales_agent", "sales_agent.js")
        self.assertIn('href="tel:', script)
        self.assertIn('this.act("task_done"', script)

    def test_approved_leads_join_campaigns_whatever_their_score_label(self):
        members = self.read("campaigns", "engine.py").split("def build_members(")[1].split("\ndef ")[0]
        self.assertNotIn('"qualification_status": "Qualified"', members)
        self.assertIn('"review_status": "Approved"', members)
        self.assertIn('"fit_score": [">=", campaign.minimum_fit_score or 0]', members)

    def test_accepting_the_ai_is_a_persons_decision_on_the_normal_path(self):
        api = self.read("api_agent_studio.py")
        accept = api.split("def _accept_ai(")[1].split("\ndef ")[0]
        self.assertIn("api._require_approver()", accept)
        self.assertIn("api.review_prospects(", accept)
        self.assertIn("names[start:start + 200]", accept)  # the review API's batch limit
        suggestions = api.split("def ai_suggestions(")[1].split("\ndef ")[0]
        self.assertIn('["in", ["approve", "reject"]]', suggestions)  # unsure leads stay with the person
        script = self.read("reckon_sales_agent", "page", "sales_agent", "sales_agent.js")
        self.assertIn('this.act("accept_ai"', script)
        self.assertIn("frappe.confirm(", script.split("ags-accept")[2])


if __name__ == "__main__":
    unittest.main()

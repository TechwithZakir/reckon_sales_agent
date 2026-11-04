"""Content agent: sequence plans, AI output cleaning, and fact / claim checks (no bench needed)."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from reckon_sales_agent.agents.content import (  # noqa: E402
    CLAIM_SCHEMA,
    SEQUENCE_SCHEMA,
    check_step,
    check_steps,
    clean_steps,
    default_plan,
)

APP = Path(__file__).parents[1] / "reckon_sales_agent"
KNOWLEDGE = [
    {"category": "Product", "title": "Reckon DMS",
     "content": "Reckon DMS handles orders, van sales, collections and stock for distributors. Used by 40 distributors."},
    {"category": "Pricing", "title": "Standard plan", "content": "BDT 2500 per user per month. Free trial for 14 days."},
]


def step(body, subject="A quick idea for {{business_name}}", channel="Email", no=1):
    return {"step_no": no, "channel": channel, "subject_template": subject, "body_template": body}


class CheckTests(unittest.TestCase):
    def issues(self, body, knowledge=KNOWLEDGE, banned=(), **kw):
        return check_steps([step(body, **kw)], knowledge, list(banned))["issues"]

    def test_clean_message_passes(self):
        result = check_steps([step("Dear {{business_name}} team,\n{{personal_line}}\nReckon DMS handles orders and "
                                   "collections for distributors like you. Used by 40 distributors.\n{{sender_name}}")],
                             KNOWLEDGE, [])
        self.assertEqual(result, {"status": "Passed", "issues": []})

    def test_absolute_and_banned_claims(self):
        self.assertTrue(any("guaranteed" in i for i in self.issues("Guaranteed growth for {{business_name}}.")))
        self.assertTrue(any("best in bangladesh" in i for i in self.issues("The best in Bangladesh DMS.")))
        self.assertTrue(any("magic" in i for i in self.issues("A magic tool.", banned=["magic"])))
        self.assertTrue(self.issues("100% গ্যারান্টি সহ।"))  # Bangla absolute claim

    def test_figures_must_come_from_approved_knowledge(self):
        self.assertTrue(any("Tk 1,999" in i for i in self.issues("Only Tk 1,999 per user.")))
        self.assertTrue(any("500 clients" in i for i in self.issues("Trusted by 500 clients.")))
        self.assertFalse(self.issues("BDT 2,500 per user per month."))  # same number as the Pricing item

    def test_commercial_terms_need_an_approved_pricing_or_offer_item(self):
        product_only = [k for k in KNOWLEDGE if k["category"] == "Product"]
        found = self.issues("Start a free trial today.", knowledge=product_only)
        self.assertTrue(any("commercial terms" in i for i in found))
        self.assertFalse(self.issues("Start a free trial today."))  # the Pricing item offers one
        self.assertTrue(any("20% off" in i for i in self.issues("Get 20% off this month.")))  # not approved

    def test_placeholders_and_channel_limits(self):
        self.assertTrue(any("nickname" in i for i in self.issues("Hi {{nickname}}")))
        self.assertTrue(any("WhatsApp under 1000" in i for i in self.issues("x" * 1200, channel="WhatsApp", subject="")))
        self.assertTrue(any("subject" in i for i in self.issues("Hello", subject="S" * 90)))
        self.assertTrue(any("empty" in i for i in self.issues("   ")))


class PlanAndCleanTests(unittest.TestCase):
    def test_default_plan_alternates_channels(self):
        plan = default_plan(3, ["Email", "WhatsApp"])
        self.assertEqual([(p["channel"], p["delay_days"]) for p in plan], [("Email", 0), ("WhatsApp", 3), ("Email", 4)])
        self.assertEqual(len(default_plan(9, ["Email"])), 5)
        self.assertEqual(default_plan(1, ["Fax"])[0]["channel"], "Email")

    def test_ai_output_is_fitted_to_the_plan(self):
        plan = default_plan(3, ["Email", "WhatsApp"])
        data = {"notes": "", "steps": [
            {"step_no": 1, "subject": "Idea for {{business_name}}", "body": "{{personal_line}}\nHi {{nickname}}"},
            {"step_no": 2, "subject": "ignored on WhatsApp", "body": "আসসালামু আলাইকুম, {{business_name}}"},
            {"step_no": 9, "subject": "x", "body": "not planned"},
        ]}
        rows = clean_steps(data, plan)
        self.assertEqual([r["step_no"] for r in rows], [1, 2])  # step 3 missing, step 9 not planned
        self.assertEqual(rows[0]["body_template"], "{{personal_line}}\nHi ")  # unknown placeholder removed
        self.assertEqual(rows[0]["use_ai_personalisation"], 1)
        self.assertEqual(rows[1]["subject_template"], "")  # WhatsApp has no subject
        self.assertEqual(rows[1]["channel"], "WhatsApp")

    def test_schemas_are_strict(self):
        for schema in (SEQUENCE_SCHEMA, CLAIM_SCHEMA):
            self.assertFalse(schema["additionalProperties"])
            self.assertEqual(set(schema["required"]), set(schema["properties"]))
        item = SEQUENCE_SCHEMA["properties"]["steps"]["items"]
        self.assertEqual(set(item["required"]), set(item["properties"]))

    def test_step_check_labels_the_step(self):
        issues = check_step(step("Guaranteed!", channel="SMS", no=2, subject=""), "", "", [])
        self.assertTrue(issues[0].startswith("Step 2 (SMS)"))


class WiringTests(unittest.TestCase):
    def read(self, *parts):
        return APP.joinpath(*parts).read_text(encoding="utf-8")

    def test_checks_run_on_save_and_gate_approval(self):
        controller = self.read("reckon_sales_agent", "doctype", "sales_campaign", "sales_campaign.py")
        self.assertIn("apply_rule_check(self)", controller)
        api = self.read("api.py")
        approve = api.split("def approve_campaign(")[1].split("\ndef ")[0]
        self.assertIn('content_status") == "Needs review" and not int(acknowledge_issues', approve)
        for method in ("write_campaign_with_ai", "check_campaign_content", "approve_knowledge"):
            self.assertIn(f"@frappe.whitelist()\ndef {method}(", api)
        form = self.read("reckon_sales_agent", "doctype", "sales_campaign", "sales_campaign.js")
        self.assertIn("acknowledge_issues", form)
        self.assertIn('"write_campaign_with_ai"', form)

    def test_only_approved_unexpired_knowledge_is_used(self):
        agent = self.read("agents", "content_agent.py")
        knowledge = agent.split("def approved_knowledge(")[1].split("\ndef ")[0]
        self.assertIn('"status": "Approved"', knowledge)
        self.assertIn("valid_until", knowledge)
        item = self.read("reckon_sales_agent", "doctype", "sales_knowledge_item", "sales_knowledge_item.py")
        self.assertIn('self.status = "Draft"', item)  # edited after approval: approve again

    def test_whatsapp_steps_need_no_subject(self):
        # Live test: an AI-written Email + WhatsApp sequence failed to save because every step needed a subject.
        step = json.loads(self.read("reckon_sales_agent", "doctype", "sales_campaign_step", "sales_campaign_step.json"))
        subject = next(f for f in step["fields"] if f["fieldname"] == "subject_template")
        self.assertFalse(subject.get("reqd"))
        self.assertEqual(subject["mandatory_depends_on"], "eval:doc.channel=='Email'")
        self.assertIn("an email needs a subject", self.read("reckon_sales_agent", "doctype", "sales_campaign",
                                                            "sales_campaign.py"))

    def test_registration(self):
        from reckon_sales_agent.constants import COMPANY_DOCTYPES

        self.assertIn("Sales Knowledge Item", COMPANY_DOCTYPES)
        sidebar = json.loads(self.read("workspace_sidebar", "sales_agent.json"))
        self.assertIn("Sales Knowledge Item", [i.get("link_to") for i in sidebar["items"]])
        profile = json.loads(self.read("reckon_sales_agent", "doctype", "sales_business_profile",
                                       "sales_business_profile.json"))
        self.assertTrue({"brand_voice", "banned_phrases"} <= {f["fieldname"] for f in profile["fields"]})


if __name__ == "__main__":
    unittest.main()

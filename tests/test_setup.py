"""Guided setup ("Get started") for managers and salespeople (no bench needed)."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from reckon_sales_agent.agents.setup import (  # noqa: E402
    FACTS_SCHEMA,
    clean_facts,
    progress,
    rule_facts,
    steps,
)

APP = Path(__file__).parents[1] / "reckon_sales_agent"


class StepTests(unittest.TestCase):
    def test_a_step_is_done_when_the_system_says_so(self):
        rows = steps({})
        self.assertEqual([r["key"] for r in rows], ["business", "market", "facts", "team", "sources", "autopilot"])
        self.assertEqual(progress(rows), 0)
        state = {"has_profile": True, "brief_status": "Approved", "facts_approved": 2, "sender_name": "Rahim",
                 "physical_address": "Dhaka", "sources_ready": True, "connector_ready": True, "autopilot": True}
        self.assertEqual(progress(steps(state)), 100)
        self.assertFalse(steps({**state, "brief_status": "Ready"})[1]["done"])  # researched is not chosen
        self.assertFalse(steps({**state, "physical_address": ""})[3]["done"])  # emails need an address
        self.assertFalse(steps({**state, "connector_ready": False})[4]["done"])  # the Company must confirm

    def test_salesperson_track(self):
        rows = steps({"my_name": "Rahim", "my_phone": ""}, seller=True)
        self.assertEqual([r["key"] for r in rows], ["me", "day"])
        self.assertFalse(rows[0]["done"])
        self.assertEqual(progress(steps({"my_name": "Rahim", "my_phone": "+880171", "seen_day": True}, seller=True)), 100)


class FactsTests(unittest.TestCase):
    def test_drafts_are_bounded_and_cite_only_pages_read(self):
        data = {"facts": [
            {"category": "Product", "title": "Reckon DMS", "content": "Order taking, stock and collections.",
             "source_url": "https://reckon.tech/dms"},
            {"category": "Proof", "title": "reckon dms", "content": "duplicate title", "source_url": ""},
            {"category": "Magic", "title": "Van sales app", "content": "For field reps.", "source_url": "https://evil.example"},
            {"category": "Offer", "title": "", "content": "no title", "source_url": ""},
        ]}
        rows = clean_facts(data, {"https://reckon.tech/dms"})
        self.assertEqual([r["title"] for r in rows], ["Reckon DMS", "Van sales app"])
        self.assertEqual(rows[1]["category"], "Product")  # unknown category
        self.assertEqual(rows[1]["source_url"], "")  # not a page the agent read
        self.assertEqual(rows[0]["source_url"], "https://reckon.tech/dms")

    def test_schema_is_strict_and_rules_need_something_to_say(self):
        item = FACTS_SCHEMA["properties"]["facts"]["items"]
        self.assertFalse(item["additionalProperties"])
        self.assertEqual(set(item["required"]), set(item["properties"]))
        self.assertEqual(rule_facts({}), [])
        fact = rule_facts({"business_name": "Reckon", "what_we_sell": "DMS software.", "products": "DMS\nVan sales"})[0]
        self.assertEqual(fact["content"], "DMS software. Products: DMS, Van sales.")


class WiringTests(unittest.TestCase):
    def read(self, *parts):
        return APP.joinpath(*parts).read_text(encoding="utf-8")

    def test_api(self):
        api = self.read("api_setup.py")
        for method in ("status", "draft_facts", "approve_facts", "choose_segments", "save_team", "use_smart_sources",
                       "save_me", "seen_day"):
            self.assertIn(f"@frappe.whitelist()\ndef {method}(", api)
        for method in ("draft_facts", "choose_segments", "save_team", "use_smart_sources"):
            self.assertIn("_require_manager()", api.split(f"def {method}(")[1].split("\ndef ")[0], method)
        self.assertIn("api.approve_knowledge(names)", api)  # approval keeps its approver check
        me = api.split("def save_me(")[1].split("\ndef ")[0]
        self.assertIn("user = frappe.session.user", me)  # only your own details
        drafts = self.read("agents", "setup.py").split("def draft_facts(")[1]
        self.assertIn('"status": "Draft"', drafts)  # a person approves every fact

    def test_page_and_registration(self):
        from reckon_sales_agent.constants import ALLOWED_PAGES, SETUP_PAGE

        self.assertIn(SETUP_PAGE, ALLOWED_PAGES)
        folder = APP / "reckon_sales_agent" / "page" / "sales_setup"
        page = json.loads((folder / "sales_setup.json").read_text(encoding="utf-8"))
        self.assertEqual(page["name"], "sales-setup")
        script = (folder / "sales_setup.js").read_text(encoding="utf-8")
        self.assertIn("(() => {", script)
        self.assertIn("sus-consent", script)  # sources and autopilot need a person's confirmation
        self.assertIn('"reckon_sales_agent.api_agent_studio.set_autopilot"', script)
        self.assertTrue((folder / "sales_setup.css").exists())
        studio = self.read("reckon_sales_agent", "page", "sales_agent", "sales_agent.js")
        self.assertIn('frappe.set_route("sales-setup")', studio)

    def test_call_scripts_use_the_callers_name(self):
        draft = self.read("campaigns", "engine.py").split("def draft_message(")[1].split("\ndef ")[0]
        self.assertIn('frappe.db.get_value("User", caller, "first_name")', draft)


if __name__ == "__main__":
    unittest.main()

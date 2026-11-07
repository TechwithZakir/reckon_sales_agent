"""The interface for people who are not technical: plain words, the everyday tasks first, help on every page."""

import json
import re
import unittest
from pathlib import Path

from reckon_sales_agent import constants
from reckon_sales_agent.providers.llm import LLMError, plain_message

ROOT = Path(__file__).resolve().parents[1] / "reckon_sales_agent"


def read(*parts):
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


class PlainErrorTests(unittest.TestCase):
    def test_a_low_balance_is_explained_not_quoted(self):
        text = plain_message(400, "Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing to upgrade")
        self.assertIn("no credit left", text)
        self.assertNotRegex(text, r"\b400\b|Anthropic|API")

    def test_each_kind_of_failure_says_what_to_do(self):
        self.assertIn("key", plain_message(401, "invalid x-api-key"))
        self.assertIn("busy", plain_message(429, "Rate limit reached"))
        self.assertIn("busy", plain_message(529, "Overloaded"))
        self.assertIn("problem", plain_message(500, "internal error"))
        self.assertIn("could not handle", plain_message(400, "unsupported parameter"))
        self.assertIn("did not answer", plain_message(None, ""))

    def test_no_message_shows_a_status_code_or_a_provider_name(self):
        for status, reason in ((400, "x"), (401, "x"), (403, "x"), (429, "x"), (500, "x"), (503, "x"), (404, "x"), (None, "")):
            text = plain_message(status, reason)
            self.assertNotRegex(text, r"\d{3}", (status, text))
            self.assertTrue(text.endswith("."))

    def test_the_providers_own_words_are_kept_for_administrators(self):
        error = LLMError("plain", detail="AI request failed (400): raw")
        self.assertEqual(str(error), "plain")
        self.assertEqual(error.detail, "AI request failed (400): raw")

    def test_a_lead_the_ai_could_not_review_says_so_plainly(self):
        self.assertIn("The AI could not review this lead.", read("agents", "triage.py"))
        self.assertNotIn("AI triage failed", read("agents", "triage.py"))


class SidebarTests(unittest.TestCase):
    ITEMS = json.loads(read("workspace_sidebar", "sales_agent.json"))["items"]
    LABELS = [i["label"] for i in ITEMS]

    def test_every_page_and_list_is_still_reachable(self):
        links = {i["link_to"] for i in self.ITEMS if i["type"] == "Link"}
        for page in constants.ALLOWED_PAGES - {"print", "user-profile", "home"}:
            if page in ("sales-setup", "sales-agent", "sales-inbox", "sales-meetings", "sales-channels", "lead-finder", "sales-review",
                        "sales-templates", "sales-analytics", "campaign-studio", "capture-studio", "automation-studio"):
                self.assertIn(page, links, page)
        for doctype in ("Sales Prospect", "Sales Outreach Message", "Sales Campaign Member", "Sales Agent Settings", "Sales Agent Activity",
                        "Sales Usage Ledger", "Sales Provider Usage", "Sales Agent Platform Settings", "Sales Source Connector"):
            self.assertIn(doctype, links, doctype)

    def test_the_everyday_groups_come_before_advanced_and_use_everyday_words(self):
        for label in ("Find customers", "Reach out", "Results", "Connect and settings", "Advanced"):
            self.assertIn(label, self.LABELS)
        self.assertLess(self.LABELS.index("Reach out"), self.LABELS.index("Advanced"))
        self.assertEqual(self.LABELS[:2], ["Get started", "Home"])

    def test_technical_names_are_not_in_the_everyday_part(self):
        advanced = self.LABELS.index("Advanced")
        everyday = " ".join(self.LABELS[:advanced])
        for jargon in ("Qualification", "Connector", "Suppression", "Ledger", "Provider", "Targeting", "Discovery", "Insight", "Members", "Events"):
            self.assertNotIn(jargon, everyday, jargon)

    def test_vendor_only_items_are_marked_and_tucked_away(self):
        advanced = self.LABELS.index("Advanced")
        for label in ("Provider usage (vendor)", "Platform settings (vendor)"):
            self.assertGreater(self.LABELS.index(label), advanced)

    def test_the_technical_group_starts_closed(self):
        self.assertEqual(self.ITEMS[self.LABELS.index("Advanced")]["keep_closed"], 1)


class HelpTests(unittest.TestCase):
    SCRIPT = read("public", "js", "rsa_help.js")
    PAGES = ("sales-setup", "sales-agent", "sales-inbox", "sales-meetings", "lead-finder", "sales-review", "campaign-studio", "capture-studio",
             "automation-studio", "sales-templates", "sales-analytics", "sales-channels")

    def test_a_guide_exists_for_every_everyday_page(self):
        for page in self.PAGES:
            self.assertIn(f'"{page}": {{ title:', self.SCRIPT, page)
            self.assertIn(page, constants.ALLOWED_PAGES)

    def test_every_guide_has_a_purpose_and_steps(self):
        for page in self.PAGES:
            block = self.SCRIPT.split(f'"{page}": {{ title:')[1][:900]
            self.assertIn("purpose:", block, page)
            self.assertIn("steps:", block, page)

    def test_the_words_are_plain(self):
        text = " ".join(re.findall(r'__\("([^"]+)"\)', self.SCRIPT)).lower()
        for jargon in ("webhook", "hmac", "dns", "json", "doctype", "endpoint", "queue", "scheduler", "cron", "oauth", "payload"):
            self.assertNotIn(jargon, text, jargon)

    def test_it_is_loaded_everywhere_and_never_breaks_a_page(self):
        self.assertIn("rsa_help.js", read("hooks.py"))
        self.assertIn("catch (err)", self.SCRIPT)
        self.assertIn("page.__rsa_help === key", self.SCRIPT)  # one button per page, however often the page is shown
        self.assertNotIn("frappe.xcall", self.SCRIPT)  # it never calls the server
        self.assertIn("localStorage.getItem", self.SCRIPT)  # the first-visit hint shows once

    def test_the_glossary_explains_the_words_a_new_person_meets(self):
        for word in ("Lead", "Audience", "Segment", "Campaign", "Template", "Automation", "Autopilot", "Pilot", "Opt-out", "Double opt-in"):
            self.assertIn(f'[__("{word}"),', self.SCRIPT, word)


class ScreenTests(unittest.TestCase):
    def test_home_shows_what_needs_you_before_the_agents(self):
        script = read("reckon_sales_agent", "page", "sales_agent", "sales_agent.js")
        layout = script.split("this.$root.html(`")[1].split("`);")[0]
        self.assertLess(layout.index("ags-needs"), layout.index("ags-lanes"))
        self.assertIn("<details class=\"ags-agents\">", layout)
        self.assertIn('title: __("Home")', script)
        meta = json.loads(read("reckon_sales_agent", "page", "sales_agent", "sales_agent.json"))
        self.assertEqual(meta["title"], "Home")

    def test_the_three_scores_on_a_lead_are_named(self):
        script = read("reckon_sales_agent", "page", "sales_agent", "sales_agent.js")
        self.assertIn('<b>${__("Fit")}</b>', script)
        self.assertIn('<b>${__("Chance")}</b>', script)
        self.assertIn('<b>${__("Match")}</b>', script)

    def test_lead_finder_offers_the_easy_source_first_and_the_rest_on_request(self):
        script = read("reckon_sales_agent", "page", "lead_finder", "lead_finder.js")
        self.assertIn('["recommended", "your data"]', script)
        self.assertIn("Show all lead sources (advanced)", script)
        self.assertIn("if (!show_all && !SIMPLE(group)) return;", script)
        # a person who already picked a provider source still sees it
        self.assertIn("(picked && !SIMPLE(picked.group))", script)

    def test_icon_only_buttons_have_a_name_for_screen_readers(self):
        script = read("reckon_sales_agent", "page", "automation_studio", "automation_studio.js")
        self.assertEqual(script.count('aria-label="${__("Insert a step here")}"'), 1)
        self.assertEqual(script.count('aria-label="${__("Add a step")}"'), 1)


if __name__ == "__main__":
    unittest.main()

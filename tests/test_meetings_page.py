"""The Meetings page: calendar file and links, the API it uses, and what the page offers (no bench needed)."""
import re
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from reckon_sales_agent.agents.meetings import build_ics, calendar_links  # noqa: E402

APP = Path(__file__).parents[1] / "reckon_sales_agent"
API = (APP / "api_meetings.py").read_text(encoding="utf-8")
SCRIPT = (APP / "reckon_sales_agent" / "page" / "sales_meetings" / "sales_meetings.js").read_text(encoding="utf-8")
START = datetime(2026, 11, 20, 4, 0, tzinfo=timezone.utc)
END = datetime(2026, 11, 20, 4, 30, tzinfo=timezone.utc)


class CalendarFileTests(unittest.TestCase):
    def test_the_file_is_a_valid_event_in_utc(self):
        ics = build_ics("m1@x", "Demo: Acme", START, END, "https://meet.example/abc", "Video call", now_utc=START)
        lines = ics.split("\r\n")
        for needle in ("BEGIN:VCALENDAR", "VERSION:2.0", "BEGIN:VEVENT", "UID:m1@x", "DTSTART:20261120T040000Z",
                       "DTEND:20261120T043000Z", "SUMMARY:Demo: Acme", "END:VEVENT", "END:VCALENDAR"):
            self.assertIn(needle, lines)
        self.assertTrue(ics.endswith("\r\n"))

    def test_special_characters_are_escaped_and_long_lines_are_folded(self):
        ics = build_ics("m1@x", "Acme, Ltd; \"North\"", START, END, "", "line one\nline two " + "x" * 200, now_utc=START)
        self.assertIn("SUMMARY:Acme\\, Ltd\\; \"North\"", ics)
        self.assertIn("DESCRIPTION:line one\\nline two", ics)
        self.assertTrue(all(len(line) <= 75 for line in ics.split("\r\n")))
        self.assertIn("\r\n x", ics)  # a folded continuation starts with a space

    def test_links_open_google_calendar_office_365_and_outlook(self):
        links = calendar_links("Demo & more", START, END, "Zoom", "Acme")
        self.assertTrue(links["google"].startswith("https://calendar.google.com/calendar/render?action=TEMPLATE"))
        self.assertIn("dates=20261120T040000Z/20261120T043000Z", links["google"])
        self.assertTrue(links["office365"].startswith("https://outlook.office.com/calendar/0/deeplink/compose"))
        self.assertTrue(links["outlook"].startswith("https://outlook.live.com/calendar/0/deeplink/compose"))
        self.assertIn("Demo%20%26%20more", links["office365"])  # nothing is left unescaped in the address
        self.assertIn("startdt=2026-11-20T04%3A00%3A00Z", links["office365"])


class MeetingsApiTests(unittest.TestCase):
    def whitelisted(self):
        return set(re.findall(r"@frappe\.whitelist\([^)]*\)\n(?:@[^\n]+\n)*def (\w+)\(", API))

    def test_the_page_only_calls_endpoints_that_exist(self):
        calls = set(re.findall(r'API \+ "(\w+)"', SCRIPT))
        self.assertTrue(calls)
        self.assertEqual(calls - self.whitelisted(), set())

    def test_writers_are_post_only_and_load_records_with_a_permission_check(self):
        for name in ("schedule", "cancel", "save_notes"):
            decorator = API.split(f"def {name}(")[0].rsplit("@frappe.whitelist", 1)[1].split("\n")[0]
            self.assertIn('methods=["POST"]', decorator, name)
        for needle in ('get_tenant_doc("Sales Meeting", meeting, "write")', 'get_tenant_doc("Sales Meeting", meeting, "read")',
                       'get_tenant_doc("Sales Prospect", prospect, "write")'):
            self.assertIn(needle, API)

    def test_the_lead_search_and_the_calendar_file_stay_inside_the_company(self):
        self.assertIn('"company": company', API.split("def find_leads(")[1].split("@frappe.whitelist")[0])
        ics = API.split("def ics(")[1].split("@frappe.whitelist")[0]
        self.assertIn('get_tenant_doc("Sales Meeting", meeting, "read")', ics)
        self.assertIn('frappe.response["type"] = "download"', ics)

    def test_a_connected_google_calendar_receives_the_event(self):
        agent = (APP / "agents" / "meetings.py").read_text(encoding="utf-8")
        self.assertIn('"sync_with_google_calendar": 1, "google_calendar": google', agent)
        self.assertIn('"push_to_google_calendar": 1', agent)


class MeetingsPageTests(unittest.TestCase):
    def test_it_offers_the_views_and_actions(self):
        for needle in ("Agenda", "Week", "All meetings", "New meeting", "Add to a calendar", "Office 365", "Download .ics",
                       "rsa_tables.enhance", "smt-owner", "smt-q", "API + \"timeline\"", "API + \"calendar\""):
            self.assertIn(needle, SCRIPT)

    def test_it_keeps_the_closure_and_never_uses_eval(self):
        self.assertIn("(() => {", SCRIPT)
        self.assertNotIn("eval(", SCRIPT.replace('"eval:!doc.agent"', ""))


if __name__ == "__main__":
    unittest.main()

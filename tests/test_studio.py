"""Lead Finder Studio: schedule timing and page/API wiring (no bench needed)."""
import json
import sys
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from reckon_sales_agent.discovery.schedule import first_run, is_due, next_run, parse_time  # noqa: E402

APP = Path(__file__).parents[1] / "reckon_sales_agent"


class ScheduleTests(unittest.TestCase):
    NOW = datetime(2026, 10, 26, 10, 30)

    def test_due_today_only_after_run_time(self):
        self.assertFalse(is_due("Weekly", "2026-10-26", "11:00", self.NOW))
        self.assertTrue(is_due("Weekly", "2026-10-26", "09:00", self.NOW))
        self.assertTrue(is_due("Weekly", "2026-10-26", None, self.NOW))

    def test_past_and_future_dates(self):
        self.assertTrue(is_due("Daily", "2026-10-20", "23:00", self.NOW))  # overdue runs right away
        self.assertFalse(is_due("Daily", "2026-10-27", "00:00", self.NOW))
        self.assertTrue(is_due("Monthly", None, None, self.NOW))
        self.assertFalse(is_due(None, None, None, self.NOW))  # manual campaigns never auto-run

    def test_frappe_time_values(self):
        self.assertEqual(parse_time(timedelta(hours=9, minutes=5)), time(9, 5))
        self.assertEqual(parse_time("17:45:00"), time(17, 45))
        self.assertIsNone(parse_time(""))

    def test_first_and_next_runs(self):
        self.assertEqual(first_run("11:00", self.NOW), date(2026, 10, 26))
        self.assertEqual(first_run("09:00", self.NOW), date(2026, 10, 27))
        self.assertEqual(first_run(None, self.NOW), date(2026, 10, 26))
        self.assertEqual(next_run("Daily", date(2026, 10, 26)), date(2026, 10, 27))
        self.assertEqual(next_run("Weekly", date(2026, 10, 26)), date(2026, 11, 2))
        self.assertEqual(next_run("Monthly", date(2026, 12, 31)), date(2027, 1, 28))


class StudioWiringTests(unittest.TestCase):
    def test_page_files_and_access(self):
        folder = APP / "reckon_sales_agent" / "page" / "lead_finder"
        meta = json.loads((folder / "lead_finder.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["name"], "lead-finder")
        self.assertTrue((folder / "lead_finder.css").exists())
        script = (folder / "lead_finder.js").read_text(encoding="utf-8")
        self.assertIn("(() => {", script)  # nothing leaks into Desk's global scope
        for method in ("bootstrap", "setup_connector", "save_targeting", "launch", "progress"):
            self.assertIn(f'"{method}"', script)
        from reckon_sales_agent.constants import ALLOWED_PAGES

        self.assertIn("lead-finder", ALLOWED_PAGES)
        sidebar = json.loads((APP / "workspace_sidebar" / "sales_agent.json").read_text(encoding="utf-8"))
        self.assertEqual(sidebar["items"][1]["link_to"], "lead-finder")

    def test_api_methods_are_whitelisted_and_never_return_keys(self):
        source = (APP / "api_studio.py").read_text(encoding="utf-8")
        for method in ("bootstrap", "profile_locations", "setup_connector", "save_targeting", "launch", "progress"):
            self.assertIn(f"@frappe.whitelist()\ndef {method}(", source)
        self.assertNotIn("get_password", source)

    def test_catalog_covers_every_connector_type(self):
        source = (APP / "api_studio.py").read_text(encoding="utf-8")
        doc = json.loads((APP / "reckon_sales_agent" / "doctype" / "sales_source_connector"
                          / "sales_source_connector.json").read_text(encoding="utf-8"))
        types = next(f["options"] for f in doc["fields"] if f["fieldname"] == "connector_type").split("\n")
        for connector_type in types:
            self.assertIn(f'"type": "{connector_type}"', source, connector_type)

    def test_scheduler_runs_discovery_hourly(self):
        hooks = (APP / "hooks.py").read_text(encoding="utf-8")
        hourly = hooks.split('"hourly": [')[1].split("]")[0]
        self.assertIn("run_scheduled_discovery", hourly)


if __name__ == "__main__":
    unittest.main()

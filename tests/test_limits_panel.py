"""The limits panel: the arithmetic, the endpoint, and where the panel is shown (no bench needed)."""
import pathlib
import re
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))

from reckon_sales_agent.limits_math import eta_minutes  # noqa: E402

APP = pathlib.Path(__file__).parents[1] / "reckon_sales_agent"
PAGES = APP / "reckon_sales_agent" / "page"


def read(*parts):
    return APP.joinpath(*parts).read_text(encoding="utf-8")


class EtaTests(unittest.TestCase):
    def test_minutes_follow_the_recent_pace(self):
        self.assertEqual(eta_minutes(30, 20, 20), 30)  # one a minute, thirty waiting
        self.assertEqual(eta_minutes(31, 5, 20), 124)  # a lead every four minutes
        self.assertEqual(eta_minutes(1, 1000, 20), 1)  # never below one minute while work waits

    def test_nothing_waiting_is_zero_and_no_pace_is_unknown(self):
        self.assertEqual(eta_minutes(0, 0), 0)
        self.assertIsNone(eta_minutes(10, 0))


class EndpointTests(unittest.TestCase):
    api = read("api_limits.py")

    def test_it_is_read_only_and_limited_to_the_company(self):
        self.assertIn("@frappe.whitelist()\ndef overview(", self.api)
        self.assertIn("company = current_company()", self.api)
        self.assertIn("assert_entitled(company)", self.api)
        for needle in ('"company": company', "company, settings", "meter(company"):
            self.assertIn(needle, self.api)
        self.assertNotIn("password", self.api.lower())  # never a key
        self.assertNotIn(".insert(", self.api)

    def test_it_covers_capture_ai_and_sending(self):
        for needle in ('"capture"', '"ai"', '"sending"', "max_concurrent_jobs", "max_results_per_job", "today_email_limit",
                       "worker_status", "ai_blocked", "research_waiting", "eta_minutes"):
            self.assertIn(needle, self.api)


class PanelTests(unittest.TestCase):
    helper = read("public", "js", "rsa_limits.js")

    def test_the_helper_is_loaded_everywhere(self):
        self.assertIn("rsa_limits.js", read("hooks.py"))

    def test_it_only_calls_the_endpoint_that_exists(self):
        called = re.search(r'const API = "reckon_sales_agent\.api_limits\.(\w+)"', self.helper).group(1)
        self.assertRegex(read("api_limits.py"), rf"def {called}\(")

    def test_it_warns_before_and_at_the_limit(self):
        self.assertIn('pct >= 80 ? "warn"', self.helper)
        self.assertIn('used >= limit ? "full"', self.helper)

    def test_it_is_shown_on_lead_finder_agent_studio_and_integrations(self):
        self.assertIn('["capture", "ai"]', (PAGES / "lead_finder" / "lead_finder.js").read_text(encoding="utf-8"))
        self.assertIn('["capture", "ai", "sending"]', (PAGES / "sales_agent" / "sales_agent.js").read_text(encoding="utf-8"))
        self.assertIn('["sending", "ai"]', (PAGES / "sales_channels" / "sales_channels.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

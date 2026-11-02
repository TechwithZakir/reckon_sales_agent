"""A Page another Company already runs is skipped and reported; the other Pages still connect (no bench)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

APP = Path(__file__).parents[1] / "reckon_sales_agent"


def read(*parts):
    return APP.joinpath(*parts).read_text(encoding="utf-8")


class PartialConnectTests(unittest.TestCase):
    def test_each_page_saves_on_its_own(self):
        finish = read("agents", "social_connect.py").split("def finish(")[1].split("\ndef ")[0]
        self.assertIn("for account in accounts:", finish)
        self.assertIn("except frappe.ValidationError:", finish)
        self.assertIn("return company, saved, skipped", finish)

    def test_callback_reports_what_was_skipped(self):
        callback = read("api_channels.py").split("def social_callback(")[1].split("\ndef ")[0]
        self.assertIn("_company, saved, skipped = finish(", callback)
        self.assertIn("&skipped=", callback)
        self.assertIn("if not saved and skipped:", callback)

    def test_page_shows_the_skipped_pages(self):
        js = read("reckon_sales_agent", "page", "sales_channels", "sales_channels.js")
        self.assertIn('params.get("skipped")', js)


if __name__ == "__main__":
    unittest.main()

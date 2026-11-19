"""Lead Finder source step: Recommended and Your data share a row, and Smart Sources shows the sources it searches as icons."""

import pathlib
import unittest

APP = pathlib.Path(__file__).resolve().parents[1] / "reckon_sales_agent"
API = (APP / "api_studio.py").read_text(encoding="utf-8")
SCRIPT = (APP / "reckon_sales_agent" / "page" / "lead_finder" / "lead_finder.js").read_text(encoding="utf-8")


class SourceStepTests(unittest.TestCase):
    def test_smart_sources_lists_the_active_providers_that_find_businesses(self):
        body = API.split("def _smart_includes(")[1].split("\ndef ")[0]
        self.assertIn('active("places")', body)
        self.assertIn('active("page_context")', body)
        self.assertIn("CATALOG_TYPES", body)
        self.assertIn('"includes": _smart_includes() if item["type"] == "multi_source" else []', API)

    def test_the_page_shows_them_as_icons_when_smart_sources_is_chosen(self):
        for needle in ('this.state.connectorType === "multi_source"', "lfs-inc-list", "Smart Sources searches these for you", "lfs_icon(s.icon, 18)"):
            self.assertIn(needle, SCRIPT)

    def test_the_two_simple_groups_share_one_row(self):
        for needle in ("lfs-grouprow", "SIMPLE(group) ? $row : panel"):
            self.assertIn(needle, SCRIPT)


if __name__ == "__main__":
    unittest.main()

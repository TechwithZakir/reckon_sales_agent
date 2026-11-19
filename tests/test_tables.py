"""Every custom list on the Sales Agent pages is searchable, sortable and paged ten at a time."""

import pathlib
import unittest

APP = pathlib.Path(__file__).resolve().parents[1] / "reckon_sales_agent"
PAGES = APP / "reckon_sales_agent" / "page"


def read(*parts):
    return pathlib.Path(APP, *parts).read_text(encoding="utf-8")


class TableHelperTests(unittest.TestCase):
    helper = read("public", "js", "rsa_tables.js")

    def test_the_helper_is_loaded_on_every_desk_page(self):
        self.assertIn("rsa_tables.js", read("hooks.py"))

    def test_ten_rows_by_default_with_search_sort_and_pages(self):
        for needle in ("size: 10", "rsa-q", "rsa-size", "rsa-tpg", "rsa-sortable", "window.rsa_tables"):
            self.assertIn(needle, self.helper)

    def test_the_helper_only_shows_and_hides_rows(self):
        self.assertIn('r.style.display = visible.has(r) ? "" : "none"', self.helper)
        self.assertNotIn("$.ajax", self.helper)
        self.assertNotIn("frappe.call", self.helper)


class PagesUseTheHelperTests(unittest.TestCase):
    def test_prospect_review_pages_its_table_and_selects_only_visible_rows(self):
        script = read("reckon_sales_agent", "page", "sales_review", "sales_review.js")
        self.assertIn("rsa_tables.enhance(this.$body.find(\"table\")", script)
        self.assertIn(".review-select:visible", script)

    def test_campaign_studio_lists_are_paged(self):
        script = read("reckon_sales_agent", "page", "campaign_studio", "campaign_studio.js")
        self.assertIn("paged(this.$body.find(\".cst-card:has(.cst-row.head)\"))", script)
        self.assertIn("this.paged(list, false)", script)
        self.assertIn(".cst-aud-list", script)

    def test_every_analytics_table_is_enhanced(self):
        script = read("reckon_sales_agent", "page", "sales_analytics", "sales_analytics.js")
        self.assertIn('find("table.t")', script)


if __name__ == "__main__":
    unittest.main()

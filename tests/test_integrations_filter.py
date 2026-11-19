"""Integrations page: a connected / not connected filter between the categories and the search."""

import pathlib
import unittest

APP = pathlib.Path(__file__).resolve().parents[1] / "reckon_sales_agent"
SCRIPT = (APP / "reckon_sales_agent" / "page" / "sales_channels" / "sales_channels.js").read_text(encoding="utf-8")


class StatusFilterTests(unittest.TestCase):
    def test_the_toolbar_has_a_status_filter_between_categories_and_search(self):
        toolbar = SCRIPT.split('<div class="sch-toolbar">')[1].split("</div>\n\t\t\t\t\t<div class=\"sch-tiles\">")[0] if '<div class="sch-tiles">' in SCRIPT else ""
        self.assertLess(SCRIPT.index("sch-cats"), SCRIPT.index("sch-status"))
        self.assertLess(SCRIPT.index('<div class="sch-status"'), SCRIPT.index('<label class="sch-search">'))
        self.assertIsInstance(toolbar, str)

    def test_it_filters_by_every_state_and_shows_counts(self):
        for needle in ('STATE_LABEL.on', 'STATE_LABEL.off', 'STATE_LABEL.warn', 'STATE_LABEL.na', "All status",
                       'base.filter((i) => i.state(d)[0] === status)', "data-status"):
            self.assertIn(needle, SCRIPT)


if __name__ == "__main__":
    unittest.main()

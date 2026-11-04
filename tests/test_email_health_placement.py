"""Email health lives in Integrations' Email tile, not Message Templates (no bench needed)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

PAGES = Path(__file__).parents[1] / "reckon_sales_agent" / "reckon_sales_agent" / "page"


class EmailHealthPlacementTests(unittest.TestCase):
    def test_message_templates_no_longer_shows_email_health(self):
        source = (PAGES / "sales_templates" / "sales_templates.js").read_text(encoding="utf-8")
        self.assertNotIn("email_health", source)
        self.assertNotIn("render_health", source)
        self.assertNotIn("stp-side", source)

    def test_integrations_email_tile_offers_the_health_check_on_click(self):
        source = (PAGES / "sales_channels" / "sales_channels.js").read_text(encoding="utf-8")
        self.assertIn("sch-health-btn", source)
        self.assertIn("reckon_sales_agent.api_deliverability.email_health", source)
        self.assertIn("email_health_html(h)", source)
        self.assertNotIn('href="/desk/sales-templates"', source)

    def test_health_panel_has_its_styles_on_integrations(self):
        css = (PAGES / "sales_channels" / "sales_channels.css").read_text(encoding="utf-8")
        for cls in (".sch-health-out", ".sch-check", ".sch-dot.ok", ".sch-dot.bad"):
            self.assertIn(cls, css)


if __name__ == "__main__":
    unittest.main()

"""Demo Data (fictional businesses) is never offered or seeded on a live site."""

import pathlib
import unittest

APP = pathlib.Path(__file__).resolve().parents[1] / "reckon_sales_agent"


def read(name):
    return (APP / name).read_text(encoding="utf-8")


class DemoSourceTests(unittest.TestCase):
    def test_the_catalog_hides_it_unless_the_site_allows_it(self):
        api = read("api_studio.py")
        self.assertIn('frappe.conf.get("rsa_allow_demo_source")', api)
        self.assertIn('if item["type"] == DEMO_SOURCE and not demo_source_allowed():', api)

    def test_it_cannot_be_switched_on_by_hand_on_a_live_site(self):
        body = read("api_studio.py").split("def setup_connector(")[1].split("@frappe.whitelist")[0]
        self.assertIn("connector_type == DEMO_SOURCE and not demo_source_allowed()", body)

    def test_a_new_company_is_not_given_the_demo_connector(self):
        seed = read("seed.py")
        self.assertIn('if frappe.conf.get("rsa_allow_demo_source")', seed)
        self.assertNotIn('("Demo data", "fixture", 1), ("CSV import"', seed)


if __name__ == "__main__":
    unittest.main()

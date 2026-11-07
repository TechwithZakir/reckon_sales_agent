"""Wiring checks for the IT-person notes, the plain list intros and the first-login tour."""

import json
import re
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "reckon_sales_agent"
CHANNELS = (APP / "reckon_sales_agent" / "page" / "sales_channels" / "sales_channels.js").read_text(encoding="utf-8")
LISTS = (APP / "public" / "js" / "rsa_lists.js").read_text(encoding="utf-8")
HELP = (APP / "public" / "js" / "rsa_help.js").read_text(encoding="utf-8")
HOOKS = (APP / "hooks.py").read_text(encoding="utf-8")
SIDEBAR = json.loads((APP / "workspace_sidebar" / "sales_agent.json").read_text(encoding="utf-8"))


class GuidedUiTests(unittest.TestCase):
    def test_every_integration_has_an_it_note(self):
        keys = re.findall(r'\{ key: "([a-z_]+)", cat: "(?!platform)', CHANNELS)
        notes = CHANNELS.split("const IT_NOTES = {")[1].split("};")[0]
        for key in keys:
            if key in ("platform_ai",):
                continue
            self.assertIn(f"{key}:", notes, key)

    def test_it_message_and_button_are_wired(self):
        self.assertIn("sch-it-copy", CHANNELS)
        self.assertIn("function it_message", CHANNELS)
        self.assertIn('.join("\\n")', CHANNELS)

    def test_lists_script_is_loaded_everywhere(self):
        self.assertIn("rsa_lists.js", HOOKS)

    def test_every_advanced_list_has_an_intro(self):
        advanced = False
        for item in SIDEBAR["items"]:
            if item.get("type") == "Section Break":
                advanced = item["label"] == "Advanced"
                continue
            dt = item.get("link_to")
            if advanced and item.get("link_type", "DocType") == "DocType" and dt and "(vendor)" not in item["label"]:
                self.assertIn(f'"{dt}":', LISTS, dt)

    def test_vendor_items_are_hidden_from_tenants(self):
        self.assertIn("(vendor)", LISTS)
        self.assertIn("Reckon Vendor Superuser", LISTS)

    def test_tour_runs_once_and_can_be_replayed(self):
        self.assertIn("rsa_tour_done", LISTS)
        self.assertIn("window.rsa_run_tour", LISTS)
        self.assertIn("rsa_run_tour", HELP)


if __name__ == "__main__":
    unittest.main()

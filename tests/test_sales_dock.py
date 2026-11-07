"""The Conversation dock: loaded on every Desk page, uses the conversation API, stays out of the way (no bench)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

APP = Path(__file__).parents[1] / "reckon_sales_agent"
DOCK = APP / "public" / "js" / "sales_dock.js"


class SolidSurfaceTests(unittest.TestCase):
    def test_the_dock_has_no_see_through_surfaces(self):
        # The theme's card colour is 4-5% white: a panel using it shows the page through it.
        js = DOCK.read_text(encoding="utf-8")
        self.assertNotIn("var(--card-bg", js)
        self.assertIn(':root[data-theme="dark"] #rsa-dock .rd-menu-pop', js)


class DockTests(unittest.TestCase):
    def test_loaded_on_every_desk_page(self):
        hooks = (APP / "hooks.py").read_text(encoding="utf-8")
        self.assertIn('"/assets/reckon_sales_agent/js/sales_dock.js"', hooks)
        self.assertIn('"/assets/reckon_sales_agent/js/rsa_help.js"', hooks)
        self.assertTrue(DOCK.is_file())

    def test_uses_the_conversation_api_and_live_updates(self):
        js = DOCK.read_text(encoding="utf-8")
        self.assertIn('const API = "reckon_sales_agent.api_conversations."', js)
        for method in ("threads", "thread", "send"):
            self.assertIn(f'call("{method}"', js, method)
        self.assertIn('frappe.realtime.on(EVENT,', js)
        self.assertIn('const EVENT = "rsa_inbox"', js)

    def test_stays_open_between_pages_and_survives_reloads(self):
        js = DOCK.read_text(encoding="utf-8")
        self.assertIn('$(document).on("page-change", sync_visibility)', js)
        self.assertIn("localStorage.getItem(KEY)", js)
        self.assertIn("try {", js)  # private browsing must not break the dock

    def test_sits_above_the_ask_ai_bar_and_offers_the_ai_reply_modes(self):
        js = DOCK.read_text(encoding="utf-8")
        self.assertIn("left: 16px; bottom: 64px;", js)
        self.assertIn("function place()", js)  # to the right of the sidebar
        for mode in ("Company default", "Autopilot", "Suggest only", "Human only"):
            self.assertIn(f'["{mode}"', js, mode)
        self.assertIn('call("set_mode", { prospect: state.prospect, mode: btn.dataset.mode })', js)
        self.assertIn('call("set_status", { prospect: state.prospect', js)

    def test_hidden_on_the_full_conversations_page(self):
        self.assertIn('frappe.get_route() || [])[0] === "sales-inbox"', DOCK.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

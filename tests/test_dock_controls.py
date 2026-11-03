"""Dock controls (mute, block, delete, minimize, close) and the phone layout (no bench)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

APP = Path(__file__).parents[1] / "reckon_sales_agent"
DOCK = (APP / "public" / "js" / "sales_dock.js").read_text(encoding="utf-8")
INBOX = (APP / "reckon_sales_agent" / "page" / "sales_inbox" / "sales_inbox.js").read_text(encoding="utf-8")
INBOX_CSS = (APP / "reckon_sales_agent" / "page" / "sales_inbox" / "sales_inbox.css").read_text(encoding="utf-8")
API = (APP / "api_conversations.py").read_text(encoding="utf-8")


class DockControlTests(unittest.TestCase):
    def test_block_is_reversible_and_asks_first(self):
        self.assertIn('frappe.confirm(__("Block this lead?', DOCK)
        block = API.split("def block(")[1].split("\n@")[0]
        self.assertIn('"do_not_contact"', block)
        self.assertNotIn("delete", block)

    def test_delete_only_removes_chat_messages_and_asks_first(self):
        self.assertIn('frappe.confirm(\n\t\t\t__("Delete this chat?', DOCK)
        delete = API.split("def delete_chat(")[1].split("\n@")[0] if "def delete_chat(" in API else API.split("def delete_chat(")[1]
        self.assertIn('frappe.db.delete("Sales Chat Message"', delete)
        self.assertNotIn("Sales Prospect", delete.split("frappe.db.delete")[1])  # the lead itself stays

    def test_mute_silences_the_bell_for_that_chat_only(self):
        self.assertIn("!muted(r.prospect) &&", DOCK)
        self.assertIn('class="rd-mute"', DOCK)

    def test_minimize_keeps_the_chat_and_close_forgets_it(self):
        self.assertIn('function minimize() { root().classList.remove("open"); }', DOCK)
        self.assertIn('panel.querySelector(".rd-close").addEventListener("click", close_all);', DOCK)
        self.assertIn("store.set({});", DOCK)


class PhoneLayoutTests(unittest.TestCase):
    def test_one_column_with_back_to_the_list(self):
        self.assertIn("@media (max-width: 768px)", INBOX_CSS)
        self.assertIn(".sin.m-thread .sin-left", INBOX_CSS)
        self.assertIn('this.$root.addClass("m-thread")', INBOX)
        self.assertIn('sin-m-back', INBOX)

    def test_panels_are_solid_not_see_through(self):
        self.assertIn("opacity: 1", DOCK)
        self.assertIn("opacity: 1", INBOX_CSS)


if __name__ == "__main__":
    unittest.main()

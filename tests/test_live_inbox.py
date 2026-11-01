"""Conversations: live updates, dock layout, and Meta chat and WhatsApp labels (no bench)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from reckon_sales_agent.agents.inbox_events import EVENT  # noqa: E402

APP = Path(__file__).parents[1] / "reckon_sales_agent"
PAGE = APP / "reckon_sales_agent" / "page" / "sales_inbox"


def read(*parts):
    return APP.joinpath(*parts).read_text(encoding="utf-8")


class LiveUpdateTests(unittest.TestCase):
    def test_every_change_point_notifies_the_team(self):
        self.assertEqual(EVENT, "rsa_inbox")
        self.assertIn("notify_inbox(company, prospect.name)", read("agents", "chat.py"))
        self.assertIn("notify_inbox(message.company, message.prospect)", read("campaigns", "engine.py"))
        self.assertIn("notify_inbox(prospect.company, prospect.name)", read("campaigns", "engine.py"))
        omni = read("agents", "omni.py")
        self.assertGreaterEqual(omni.count("notify_inbox(company, prospect.name)"), 3)
        api = read("api_conversations.py")
        self.assertIn("return _changed(prospect)", api)
        self.assertIn("notify_inbox(doc.company, doc.name)", api)

    def test_notifications_never_fail_the_change(self):
        source = read("agents", "inbox_events.py")
        self.assertIn("publish_realtime(EVENT", source)
        self.assertIn("except Exception:", source)
        self.assertIn("after_commit=True", source)

    def test_team_only(self):
        source = read("agents", "inbox_events.py")
        self.assertIn('"Tenant User Assignment", filters={"company": company, "active": 1}', source)

    def test_page_subscribes_and_keeps_a_fallback(self):
        js = (PAGE / "sales_inbox.js").read_text(encoding="utf-8")
        self.assertIn("frappe.realtime.on(EVENT, this.onRealtime)", js)
        self.assertIn("frappe.realtime.off(EVENT, this.onRealtime)", js)
        self.assertIn("setInterval", js)
        self.assertIn("const busy = this.$root.find(\".sin-text\").val()", js)  # never redraws a reply being typed


class DockLayoutTests(unittest.TestCase):
    def test_three_docks_and_full_width(self):
        js = (PAGE / "sales_inbox.js").read_text(encoding="utf-8")
        for cls in ("sin-left", "sin-main", "sin-right", "sin-ctx"):
            self.assertIn(cls, js)
        self.assertIn('toggleClass("max", !!p.max)', js)
        css = (PAGE / "sales_inbox.css").read_text(encoding="utf-8")
        self.assertIn(".sin.max", css)
        self.assertIn(".sin.no-left .sin-left", css)

    def test_bottom_left_dock_is_the_default(self):
        js = (PAGE / "sales_inbox.js").read_text(encoding="utf-8")
        self.assertIn("bl: true, folded: false", js)
        self.assertIn('toggleClass("dock-bl", !!p.bl)', js)
        css = (PAGE / "sales_inbox.css").read_text(encoding="utf-8")
        self.assertIn("position: fixed; left: 16px; bottom: 16px;", css)

    def test_layout_is_remembered_safely(self):
        js = (PAGE / "sales_inbox.js").read_text(encoding="utf-8")
        self.assertIn("localStorage.getItem(PREFS)", js)
        self.assertIn("try {", js)  # private browsing must not break the page


class ChannelLabelTests(unittest.TestCase):
    def test_conversations_show_meta_and_whatsapp(self):
        js = (PAGE / "sales_inbox.js").read_text(encoding="utf-8")
        for name in ('Messenger: "Messenger"', 'Instagram: "Instagram"', 'WhatsApp: "WhatsApp"'):
            self.assertIn(name, js)
        self.assertIn("c.last_channel", js)
        self.assertIn('"last_channel", "_user_tags"', read("agents", "conversations.py"))


if __name__ == "__main__":
    unittest.main()

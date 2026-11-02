"""A bell rings when a lead writes in, and it can be turned off or on (no bench)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

APP = Path(__file__).parents[1] / "reckon_sales_agent"
DOCK = (APP / "public" / "js" / "sales_dock.js").read_text(encoding="utf-8")
INBOX = (APP / "reckon_sales_agent" / "page" / "sales_inbox" / "sales_inbox.js").read_text(encoding="utf-8")


class BellTests(unittest.TestCase):
    def test_rings_only_for_a_new_incoming_message(self):
        announce = DOCK.split("function announce(rows) {")[1].split("\n\t}")[0]
        self.assertIn("r.needs_reply", announce)
        self.assertIn("String(r.last) > String(seen[r.prospect])", announce)
        self.assertIn("if (state.primed && fresh.length && sound_on()) ring();", announce)  # never on the first load

    def test_uses_frappes_notification_sound(self):
        self.assertIn('frappe.utils.play_sound("notification")', DOCK)

    def test_can_be_turned_off_and_on_from_both_places(self):
        self.assertIn('localStorage.getItem(SOUND_KEY) !== "off"', DOCK)
        self.assertIn('class="rd-sound"', DOCK)
        self.assertIn('class="btn btn-default btn-xs sin-sound"', INBOX)
        self.assertIn('"rsa_sound"', INBOX)  # the same setting as the dock


if __name__ == "__main__":
    unittest.main()

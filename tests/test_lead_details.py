"""New contacts are asked for their details, and the details they send back are read (no bench)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from reckon_sales_agent.agents.lead_details import extract  # noqa: E402

APP = Path(__file__).parents[1] / "reckon_sales_agent"


class ExtractTests(unittest.TestCase):
    def test_labelled_lines(self):
        found = extract("Name: Rahim Uddin\nPhone: 01711234567\nWhatsApp: +8801811223344\nEmail: rahim@example.com")
        self.assertEqual(found["name"], "Rahim Uddin")
        self.assertEqual(found["phone"], "01711234567")
        self.assertEqual(found["whatsapp"], "+8801811223344")
        self.assertEqual(found["email"], "rahim@example.com")

    def test_bare_email_and_number(self):
        self.assertEqual(extract("my mail is shop@example.com")["email"], "shop@example.com")
        self.assertEqual(extract("call me on 01711234567")["phone"], "01711234567")

    def test_email_is_not_read_as_a_number(self):
        self.assertNotIn("phone", extract("reach me at 1234@example.com"))

    def test_nothing_to_read(self):
        self.assertEqual(extract("Hello there"), {})
        self.assertEqual(extract(""), {})

    def test_whatsapp_number_is_not_also_a_phone(self):
        self.assertNotIn("phone", extract("WhatsApp: 01711234567"))


class WiringTests(unittest.TestCase):
    def test_every_inbound_chat_message_runs_the_details_step(self):
        chat = (APP / "agents" / "chat.py").read_text(encoding="utf-8")
        receive = chat.split("def receive_chat(")[1].split("\ndef ")[0]
        self.assertIn('first = not frappe.db.exists("Sales Chat Message", {"prospect": prospect.name})', receive)
        self.assertIn("after_inbound(prospect.name, text, first)", receive)

    def test_details_are_never_sent_without_approval(self):
        source = (APP / "agents" / "lead_details.py").read_text(encoding="utf-8")
        self.assertIn("allow_auto=False", source)
        self.assertIn("draft_reply(", source)

    def test_messenger_and_instagram_names_come_from_meta_on_first_contact(self):
        api = (APP / "api_channels.py").read_text(encoding="utf-8")
        self.assertIn("meta_profile_name(event[\"channel\"], owner[1], event[\"contact_id\"])", api)
        self.assertIn("if not named and not event.get(\"contact_name\")", api)


if __name__ == "__main__":
    unittest.main()

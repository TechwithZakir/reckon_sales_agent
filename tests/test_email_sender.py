"""The email sender is the chosen account's address, and only an account set up for outgoing mail can be chosen (no bench)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

APP = Path(__file__).parents[1] / "reckon_sales_agent"


def read(*parts):
    return APP.joinpath(*parts).read_text(encoding="utf-8")


class EmailSenderTests(unittest.TestCase):
    def test_sender_is_the_address_not_the_account_name(self):
        send = read("providers", "channels.py").split("def _email(")[1].split("\ndef ")[0]
        self.assertIn('frappe.db.get_value("Email Account", {"name": settings.get("email_account"), "enable_outgoing": 1}, "email_id")', send)

    def test_only_an_outgoing_account_can_be_chosen(self):
        api = read("api_channels.py")
        self.assertIn('if field == "email_account" and value and not frappe.db.get_value("Email Account", str(value).strip(), "enable_outgoing"):', api)

    def test_every_account_with_an_address_is_offered(self):
        api = read("api_channels.py")
        self.assertIn('filters={"email_id": ["is", "set"]}', api)


if __name__ == "__main__":
    unittest.main()

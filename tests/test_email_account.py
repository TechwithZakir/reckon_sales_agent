"""Email: a Company picks its sending Email Account from the Email Account list (no bench)."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

APP = Path(__file__).parents[1] / "reckon_sales_agent"


def read(*parts):
    return APP.joinpath(*parts).read_text(encoding="utf-8")


class EmailAccountTests(unittest.TestCase):
    def test_settings_link_to_the_email_account_list(self):
        doc = json.loads(read("reckon_sales_agent", "doctype", "sales_agent_settings", "sales_agent_settings.json"))
        field = next(f for f in doc["fields"] if f["fieldname"] == "email_account")
        self.assertEqual((field["fieldtype"], field["options"]), ("Link", "Email Account"))
        self.assertIn("email_account", doc["field_order"])

    def test_sender_is_the_chosen_account_else_the_default(self):
        send = read("providers", "channels.py").split("def _email(")[1].split("\ndef ")[0]
        self.assertIn('settings.get("email_account")', send)
        self.assertIn("sender=account", send)

    def test_panel_offers_the_list_with_a_new_link(self):
        js = read("reckon_sales_agent", "page", "sales_channels", "sales_channels.js")
        self.assertIn('f: "email_account", type: "link"', js)
        self.assertIn('create: "/desk/email-account/new"', js)


if __name__ == "__main__":
    unittest.main()

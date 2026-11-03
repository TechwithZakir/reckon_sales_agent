"""WhatsApp Embedded Signup: one-click connection of a customer's number, kept to its own Company (no bench).

Meta's approval and a live signup are needed to test the whole flow; these checks cover the code paths we own."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from reckon_sales_agent.agents.whatsapp_signup import ID  # noqa: E402

APP = Path(__file__).parents[1] / "reckon_sales_agent"


def read(*parts):
    return APP.joinpath(*parts).read_text(encoding="utf-8")


class SignupModuleTests(unittest.TestCase):
    def test_ids_from_meta_must_look_like_ids(self):
        self.assertTrue(ID.match("123456789012345"))
        self.assertFalse(ID.match("abc"))
        self.assertFalse(ID.match(""))

    def test_a_number_of_another_company_is_refused(self):
        finish = read("agents", "whatsapp_signup.py").split("def finish(")[1]
        self.assertIn('frappe.db.get_value("WhatsApp Account", {"phone_id": phone_number_id}, "name")', finish)
        self.assertIn("already connected to another Company", finish)

    def test_the_customers_waba_is_subscribed_to_our_app(self):
        finish = read("agents", "whatsapp_signup.py").split("def finish(")[1]
        self.assertIn('API + f"{waba_id}/subscribed_apps"', finish)
        self.assertIn('settings.whatsapp_account = account', finish)
        self.assertIn('settings.whatsapp_enabled = 1', finish)

    def test_code_is_exchanged_for_a_business_token(self):
        exchange = read("agents", "whatsapp_signup.py").split("def exchange_code(")[1].split("\ndef ")[0]
        self.assertIn('API + "oauth/access_token"', exchange)
        self.assertIn('"code": code', exchange)


class SignupEndpointTests(unittest.TestCase):
    def test_both_endpoints_are_for_managers_only(self):
        api = read("api_channels.py")
        for name in ("whatsapp_signup_setup", "whatsapp_signup_finish"):
            body = api.split(f"def {name}(")[1].split("\n@")[0]
            self.assertIn("_require_manager()", body, name)

    def test_the_configuration_id_is_a_vendor_setting(self):
        self.assertIn('"whatsapp_signup_config_id": "text"', read("api_channels.py"))
        doc = json.loads(read("reckon_sales_agent", "doctype", "sales_agent_platform_settings",
                              "sales_agent_platform_settings.json"))
        self.assertIn("whatsapp_signup_config_id", [f["fieldname"] for f in doc["fields"]])


class SignupPanelTests(unittest.TestCase):
    def test_panel_starts_the_signup_and_waits_for_both_parts(self):
        js = read("reckon_sales_agent", "page", "sales_channels", "sales_channels.js")
        self.assertIn("Connect WhatsApp with Facebook", js)
        self.assertIn("config_id: cfg.config_id", js)
        self.assertIn('data.type !== "WA_EMBEDDED_SIGNUP" || data.event !== "FINISH"', js)
        self.assertIn(r'/(^|\.)facebook\.com$/', js)  # only messages from Facebook are trusted


if __name__ == "__main__":
    unittest.main()

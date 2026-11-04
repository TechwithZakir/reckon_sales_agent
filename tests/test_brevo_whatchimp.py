"""Brevo email and WhatChimp WhatsApp: request shapes, routing and settings (no network, no bench)."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from reckon_sales_agent.providers.brevo import TAG, email_payload  # noqa: E402
from reckon_sales_agent.providers.whatchimp import text_payload  # noqa: E402

APP = Path(__file__).parents[1] / "reckon_sales_agent"
PAGES = APP / "reckon_sales_agent" / "page"
SETTINGS = APP / "reckon_sales_agent" / "doctype" / "sales_agent_settings" / "sales_agent_settings.json"


class BrevoPayloadTests(unittest.TestCase):
    def setUp(self):
        self.body = email_payload("lead@example.com", "sales@reckon.tech", "Reckon", "Hello", "<p>Hi</p>", "PROSP-1")

    def test_sender_and_recipient_are_objects_and_a_list(self):
        self.assertEqual(self.body["sender"], {"name": "Reckon", "email": "sales@reckon.tech"})
        self.assertEqual(self.body["to"], [{"email": "lead@example.com"}])

    def test_one_body_type_only(self):
        # Brevo accepts one of htmlContent, textContent or templateId per request.
        self.assertEqual(self.body["htmlContent"], "<p>Hi</p>")
        self.assertNotIn("textContent", self.body)
        self.assertNotIn("templateId", self.body)

    def test_tags_trace_the_outreach_message(self):
        self.assertEqual(self.body["tags"], [TAG, "PROSP-1"])
        self.assertEqual(self.body["subject"], "Hello")


class WhatChimpPayloadTests(unittest.TestCase):
    def test_text_message_body_follows_the_console_example(self):
        self.assertEqual(text_payload("tok", "12345", "8801712345678", "Hello"),
                         {"apiToken": "tok", "phone_number_id": "12345", "phone": "8801712345678", "message": "Hello"})


class RoutingTests(unittest.TestCase):
    def test_email_routes_brevo_when_selected(self):
        source = (APP / "providers" / "channels.py").read_text(encoding="utf-8")
        self.assertIn('settings.get("email_provider") == "Brevo"', source)
        self.assertIn("from reckon_sales_agent.providers.brevo import send_email as send_brevo", source)

    def test_whatsapp_routes_whatchimp_and_keeps_frappe_whatsapp_as_default(self):
        source = (APP / "providers" / "channels.py").read_text(encoding="utf-8")
        self.assertIn("return _whatsapp(message, settings)", source)
        self.assertIn('settings.get("whatsapp_provider") == "WhatChimp"', source)
        self.assertIn('if "frappe_whatsapp" not in frappe.get_installed_apps():', source)

    def test_whatchimp_refuses_templates_rather_than_guessing_their_fields(self):
        source = (APP / "providers" / "whatchimp.py").read_text(encoding="utf-8")
        self.assertIn('if message.get("whatsapp_template"):', source)
        self.assertIn("WhatChimp template messages are not connected yet", source)


class SettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(SETTINGS.read_text(encoding="utf-8"))
        cls.fields = {f["fieldname"]: f for f in cls.doc["fields"] if f.get("fieldname")}

    def test_new_fields_are_in_the_field_order(self):
        for name in ("brevo_api_key", "brevo_sender_email", "whatsapp_provider",
                     "whatchimp_api_token", "whatchimp_phone_number_id"):
            self.assertIn(name, self.doc["field_order"], name)
            self.assertIn(name, self.fields, name)

    def test_secrets_are_password_fields(self):
        self.assertEqual(self.fields["brevo_api_key"]["fieldtype"], "Password")
        self.assertEqual(self.fields["whatchimp_api_token"]["fieldtype"], "Password")

    def test_provider_choices(self):
        self.assertIn("Brevo", self.fields["email_provider"]["options"].split("\n"))
        self.assertEqual(self.fields["whatsapp_provider"]["options"].split("\n"), ["frappe_whatsapp", "WhatChimp"])
        self.assertEqual(self.fields["whatsapp_provider"]["default"], "frappe_whatsapp")

    def test_system_email_account_only_for_system_email(self):
        self.assertEqual(self.fields["email_account"]["depends_on"], "eval:doc.email_provider == 'System Email'")


class IntegrationsPageTests(unittest.TestCase):
    def test_the_save_whitelist_allows_the_new_fields(self):
        source = (APP / "api_channels.py").read_text(encoding="utf-8")
        for field in ('"brevo_api_key": "secret"', '"brevo_sender_email": "text"', '"whatchimp_api_token": "secret"',
                      '"whatchimp_phone_number_id": "text"', '"whatsapp_provider": "text"'):
            self.assertIn(field, source)

    def test_the_panels_and_tile_state_exist(self):
        source = (PAGES / "sales_channels" / "sales_channels.js").read_text(encoding="utf-8")
        self.assertIn('options: ["System Email", "Twilio SendGrid", "Brevo"]', source)
        self.assertIn("whatchimp_section()", source)
        self.assertIn('d.email.provider === "Brevo"', source)
        self.assertIn("brevo_sender_email", source)


if __name__ == "__main__":
    unittest.main()

"""The system provider's settings on the Integrations page: vendor-only, server-enforced (no bench)."""
import ast
import unittest
from pathlib import Path

APP = Path(__file__).parents[1] / "reckon_sales_agent"
PAGE = APP / "reckon_sales_agent" / "page" / "sales_channels" / "sales_channels.js"


def read(*parts):
    return APP.joinpath(*parts).read_text(encoding="utf-8")


def platform_editable():
    """PLATFORM_EDITABLE read from api_channels.py without importing Frappe."""
    tree = ast.parse(read("api_channels.py"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "PLATFORM_EDITABLE" for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("PLATFORM_EDITABLE not found")


PLATFORM_EDITABLE = platform_editable()


class PlatformServerTests(unittest.TestCase):
    def test_only_secrets_are_write_only(self):
        for field in ("anthropic_api_key", "openai_api_key", "local_ai_api_key", "meta_app_secret",
                      "meta_verify_token", "linkedin_client_secret"):
            self.assertEqual(PLATFORM_EDITABLE[field], "secret", field)
        for field in ("meta_app_id", "linkedin_client_id", "ai_model"):
            self.assertEqual(PLATFORM_EDITABLE[field], "text", field)

    def test_values_go_to_vendors_only(self):
        overview = read("api_channels.py").split("def overview(")[1].split("\ndef ")[0]
        self.assertIn('"platform": _platform_values(platform) if vendor else None', overview)
        self.assertIn('if vendor else []', overview)  # the Company list too
        self.assertIn("vendor = _is_vendor()", overview)

    def test_save_is_checked_on_the_server(self):
        save = read("api_channels.py").split("def save_platform_settings(")[1].split("\n@frappe")[0]
        self.assertIn("if not _is_vendor():", save)
        self.assertIn("frappe.PermissionError", save)
        self.assertIn('frappe.get_doc("Sales Agent Platform Settings")', save)

    def test_vendor_roles_are_the_only_ones_checked(self):
        constants = read("constants.py")
        self.assertIn('VENDOR_ROLES = ("System Manager", "Reckon Vendor Superuser")', constants)
        self.assertIn("VENDOR_ROLES", read("api_channels.py").split("def _is_vendor(")[1].split("\ndef ")[0])

    def test_tenant_company_settings_are_untouched(self):
        # The company save still uses the tenant's own Company only.
        save = read("api_channels.py").split("def save_settings(")[1].split("\n@frappe")[0]
        self.assertIn('get_tenant_doc("Sales Agent Settings", current_company(), "write")', save)


class PlatformPageTests(unittest.TestCase):
    def test_platform_tiles_and_category_only_for_vendors(self):
        js = PAGE.read_text(encoding="utf-8")
        self.assertIn("...(d.is_vendor ? PLATFORM_TILES : [])", js)
        self.assertIn('(d.is_vendor ? [...CATEGORIES, ["platform", __("System provider")]] : CATEGORIES)', js)
        self.assertIn("if (!item || (item.platform && !this.data.is_vendor)) return;", js)

    def test_platform_panels_save_to_the_vendor_endpoint(self):
        js = PAGE.read_text(encoding="utf-8")
        self.assertIn('"save_platform_settings" : "save_settings"', js)
        self.assertIn('data-scope="${scope}"', js)
        for key in ("platform_ai", "platform_meta", "platform_linkedin", "platform_transcription"):
            self.assertIn(f'"{key}"', js)

    def test_every_platform_field_is_a_real_setting(self):
        import json
        import re

        doctype = json.loads(read("reckon_sales_agent", "doctype", "sales_agent_platform_settings",
                                  "sales_agent_platform_settings.json"))
        real = {f["fieldname"]: f["fieldtype"] for f in doctype["fields"]}
        for field, kind in PLATFORM_EDITABLE.items():
            self.assertIn(field, real, field)
            expected = {"check": "Check", "secret": "Password"}.get(kind, None)
            if expected:
                self.assertEqual(real[field], expected, field)
        js = PAGE.read_text(encoding="utf-8")
        used = set(re.findall(r'f: "([a-z_]+)"', js))
        platform_used = {f for f in used if f in real and f not in ("ari_url", "ari_username", "ari_password",
                                                                  "calling_hours", "sip_caller_id", "sip_context",
                                                                  "telephony_webhook_secret", "sms_account",
                                                                  "sms_api_key", "sms_enabled", "sms_provider",
                                                                  "sms_sender_id", "twilio_account_sid",
                                                                  "twilio_auth_token", "twilio_messaging_service_sid",
                                                                  "twilio_phone_number", "twilio_record_calls",
                                                                  "voice_ai_enabled", "voice_ai_greeting",
                                                                  "voice_ai_language", "voice_forward_to",
                                                                  "whatsapp_enabled", "email_provider",
                                                                  "sendgrid_api_key", "sendgrid_from_email",
                                                                  "sendgrid_webhook_key", "telephony_provider")}
        self.assertTrue(platform_used <= set(PLATFORM_EDITABLE), platform_used - set(PLATFORM_EDITABLE))

    def test_keyboard_handler_never_cancels_typing(self):
        # A handler that returns false cancels the key in jQuery: every letter typed on the page was blocked.
        js = PAGE.read_text(encoding="utf-8")
        self.assertIn('if (ev.key === "Escape") this.close();', js)
        self.assertNotIn('ev.key === "Escape" && this.close()', js)

    def test_company_switcher_sends_the_chosen_company(self):
        js = PAGE.read_text(encoding="utf-8")
        self.assertIn("company: this.company", js)
        self.assertIn('this.$root.find(".sch-co").on("change"', js)


if __name__ == "__main__":
    unittest.main()

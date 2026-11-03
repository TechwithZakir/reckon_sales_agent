"""WhatsApp through the frappe_whatsapp app: one account per Company, inbound conversations, templates (no bench)."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

APP = Path(__file__).parents[1] / "reckon_sales_agent"


def read(*parts):
    return APP.joinpath(*parts).read_text(encoding="utf-8")


class TenantAccountTests(unittest.TestCase):
    def test_inbound_is_filed_under_the_accounts_company(self):
        engine = read("campaigns", "engine.py")
        handler = engine.split("def handle_whatsapp(")[1].split("\ndef ")[0]
        self.assertIn('company = _account_company(doc.get("whatsapp_account"))', handler)
        self.assertIn('if not company or not phone:', handler)
        self.assertNotIn('"normalized_phone": normalized}', engine.split("def handle_whatsapp(")[0][-10:])
        helper = engine.split("def _account_company(")[1].split("\ndef ")[0]
        self.assertIn('{"whatsapp_account": account}', helper)

    def test_window_update_is_per_company(self):
        source = read("agents", "engagement_agent.py").split("def record_whatsapp_inbound(")[1].split("\ndef ")[0]
        self.assertIn('{"company": company} if company else {}', source)

    def test_one_account_per_company(self):
        settings = read("reckon_sales_agent", "doctype", "sales_agent_settings", "sales_agent_settings.py")
        self.assertIn('{"whatsapp_account": account, "name": ["!=", self.name]}', settings)

    def test_outbound_uses_the_companys_account(self):
        channels = read("providers", "channels.py").split("def _whatsapp(")[1].split("\ndef ")[0]
        self.assertIn('values["whatsapp_account"] = account', channels)


class ConversationTests(unittest.TestCase):
    def test_whatsapp_joins_the_shared_chat_path(self):
        engine = read("campaigns", "engine.py")
        conversation = engine.split("def _whatsapp_conversation(")[1].split("\ndef ")[0]
        self.assertIn('receive_chat(company, "WhatsApp"', conversation)
        self.assertIn('"whatsapp_consent", 1', conversation)  # they wrote first: opted in, window open
        self.assertIn('"WhatsApp": "whatsapp"', read("agents", "chat.py"))

    def test_timeline_has_no_duplicate_incoming(self):
        timeline = read("agents", "omni.py").split("def timeline(")[1].split("\ndef ")[0]
        self.assertIn('"type": "Outgoing"', timeline)
        self.assertIn('"reference_doctype": ["is", "not set"]', timeline)
        self.assertNotIn('"type": "Incoming"', timeline)

    def test_window_closed_offers_templates_only(self):
        omni = read("agents", "omni.py").split("def reply_channels(")[1].split("\ndef compose(")[0]
        self.assertIn('"window_closed": closed', omni)
        compose = read("agents", "omni.py").split("def compose(")[1]
        self.assertIn("template_ok = bool(template) and channel == \"WhatsApp\"", compose)
        self.assertIn('"whatsapp_template": template if channel == "WhatsApp" else None', compose)


class TemplateTests(unittest.TestCase):
    def test_submission_sets_the_fields_the_app_requires(self):
        templates = read("agents", "templates.py").split("def _publish_whatsapp(")[1].split("\ndef ")[0]
        self.assertIn('values["language"] = lang', templates)
        self.assertIn('"whatsapp_account": get_settings(doc.company)', templates)

    def test_company_templates_are_listed_for_the_thread(self):
        api = read("api_conversations.py").split("def _wa_templates(")[1]
        self.assertIn('"status": ["in", ["APPROVED", "Approved"]]', api)
        self.assertIn('filters["whatsapp_account"] = account', api)


class IntegrationsPageTests(unittest.TestCase):
    def test_webhook_and_accounts_are_shown(self):
        js = read("reckon_sales_agent", "page", "sales_channels", "sales_channels.js")
        self.assertIn("frappe_whatsapp.utils.webhook.webhook", read("api_channels.py"))
        self.assertIn("d.whatsapp.accounts.map", js)
        self.assertIn('{ f: "whatsapp_account", type: "link"', js)

    def test_setup_guide_links_the_app_docs(self):
        self.assertIn("shridarpatil.github.io/frappe_whatsapp/#configuration", read("agents", "channel_guide.py"))
        js = read("reckon_sales_agent", "page", "sales_channels", "sales_channels.js")
        self.assertIn("message_template_status_update", js)

    def test_every_integration_panel_links_its_reference(self):
        js = read("reckon_sales_agent", "page", "sales_channels", "sales_channels.js")
        self.assertIn('"references": _references(),', read("api_channels.py"))
        self.assertIn("(this.data.references || {})[key]", js)
        self.assertIn("${this.guides(key)}", js)
        self.assertNotIn("const GUIDES = {", js)

    def test_settings_field_exists(self):
        doc = json.loads(read("reckon_sales_agent", "doctype", "sales_agent_settings", "sales_agent_settings.json"))
        self.assertIn("whatsapp_account", [f["fieldname"] for f in doc["fields"]])
        self.assertIn("whatsapp_account", doc["field_order"])


if __name__ == "__main__":
    unittest.main()

"""Meeting agent, Meta lead bridge, data quality, telephony, deliverability, templates, conversations (no bench)."""
import json
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from reckon_sales_agent.agents.data_quality import plan_fixes  # noqa: E402
from reckon_sales_agent.agents.deliverability import allowed, evaluate_dns, warmup_limit  # noqa: E402
from reckon_sales_agent.agents.meetings import parse_days, parse_hours, propose_slots  # noqa: E402
from reckon_sales_agent.agents.omni import choose_channel, needs_reply  # noqa: E402
from reckon_sales_agent.agents.orchestrator import ASK, DO, plan  # noqa: E402
from reckon_sales_agent.agents.templates import meta_body, template_issues  # noqa: E402
from reckon_sales_agent.leads_bridge import prospect_fields  # noqa: E402
from reckon_sales_agent.telephony import call_status, normalize_event, originate_params  # noqa: E402

APP = Path(__file__).parents[1] / "reckon_sales_agent"
READY = {"has_profile": True, "brief_status": "Approved", "brief": "B1", "sources_ready": True, "ai": True}


def read(*parts):
    return APP.joinpath(*parts).read_text(encoding="utf-8")


class MeetingTests(unittest.TestCase):
    def test_bangladesh_week_and_hours(self):
        self.assertEqual(parse_days("Sun,Mon,Tue,Wed,Thu"), {6, 0, 1, 2, 3})
        self.assertEqual(parse_days(""), {6, 0, 1, 2, 3})  # default working week
        self.assertEqual(parse_hours("10:00-17:00"), (600, 1020))
        self.assertEqual(parse_hours("9-18"), (540, 1080))
        self.assertEqual(parse_hours("nonsense"), (600, 1020))

    def test_slots_avoid_weekends_busy_time_and_spread_over_days(self):
        now = datetime(2026, 10, 29, 15, 10)  # Thursday afternoon
        busy = [(datetime(2026, 11, 1, 10, 0), datetime(2026, 11, 1, 11, 0))]  # Sunday 10-11 taken
        slots = propose_slots(now, busy, parse_days(None), (600, 1020), 30, 3)
        self.assertEqual(len(slots), 3)
        self.assertTrue(all(s.weekday() not in (4, 5) for s in slots))  # never Friday or Saturday
        self.assertEqual(slots[0], datetime(2026, 11, 1, 11, 0))  # Thursday too late (2h lead), Sunday 10:00 busy
        self.assertEqual(len({s.date() for s in slots}), 3)  # one per day
        self.assertTrue(all(600 <= s.hour * 60 + s.minute <= 1020 - 30 for s in slots))

    def test_interested_starts_a_meeting(self):
        self.assertIn("start_meeting(prospect.name", read("campaigns", "calls.py"))
        engine = read("campaigns", "engine.py").split("def classify_and_follow_up(")[1].split("\ndef ")[0]
        self.assertIn('if final in ("interested", "meeting_request"):', engine)
        self.assertIn('"reckon_sales_agent.agents.meetings.send_reminders"', read("hooks.py"))
        draft = read("agents", "meetings.py").split("def _draft_invitation(")[1].split("\ndef ")[0]
        self.assertIn('"status": "Draft"', draft)  # the invitation waits for a person


class MetaBridgeTests(unittest.TestCase):
    def test_lead_to_prospect(self):
        fields = prospect_fields({"first_name": "Rahim", "last_name": "Uddin", "organization": "Rahim Pharma",
                                  "email": "rahim@pharma.com.bd", "mobile_no": "+8801711000000", "creation": "x"})
        self.assertEqual(fields["business_name"], "Rahim Pharma")
        self.assertEqual(fields["phone"], "+8801711000000")
        provenance = json.loads(fields["provenance_json"])
        self.assertEqual(provenance["email"]["source"], "lead_form")
        self.assertIsNone(provenance["email"]["retention_days"])  # given by the person: no source retention
        self.assertEqual(prospect_fields({"first_name": "Rina"})["business_name"], "Rina")

    def test_tenancy_and_wiring(self):
        source = read("crm_tenancy.py")
        data = source.split("DATA_DOCTYPES = {")[1].split("}")[0]
        masters = source.split("MASTER_DOCTYPES = {")[1].split("}")[0]
        for doctype in ("Lead Sync Source", "Facebook Page", "Facebook Lead Form", "Failed Lead Sync Log"):
            self.assertIn(f'"{doctype}"', data)  # the source holds the Company's Meta token
        self.assertIn('"Email Template"', masters)
        tenancy = read("crm_tenancy.py").split("def inherited_company(")[1].split("\ndef ")[0]
        self.assertIn("lead_form_company(doc.facebook_form_id)", tenancy)
        self.assertIn('doc_events["CRM Lead"]["after_insert"] = "reckon_sales_agent.leads_bridge.on_crm_lead_insert"',
                      read("hooks.py"))
        bridge = read("leads_bridge.py").split("def speed_to_lead(")[1]
        self.assertIn('"review_status": "Approved"', bridge)
        self.assertIn('"consent_source": CONSENT', bridge)
        self.assertIn('"task_due_days": 0', bridge)  # call today


class DataQualityTests(unittest.TestCase):
    def test_fixes(self):
        rows = [
            {"name": "P1", "phone": "01711-000000", "email": "info@a.com", "website": "https://a.com", "review_status": "Approved"},
            {"name": "P2", "phone": "+8801711000000", "email": None, "website": None, "review_status": "Pending"},
            {"name": "P3", "phone": None, "email": "sales@b.com", "website": "https://www.a.com/x", "review_status": "Pending"},
            {"name": "P4", "phone": None, "email": "bad@c.com", "website": None, "review_status": "Pending"},
            {"name": "P5", "phone": "+8801711000000", "email": None, "website": None, "review_status": "Rejected"},
        ]
        found = plan_fixes(rows, {"bad@c.com"})
        self.assertEqual(found["phones"], [("P1", "+8801711000000")])
        self.assertEqual([(d[0], d[1]) for d in found["duplicates"]], [("P2", "P1"), ("P3", "P1")])
        self.assertEqual(found["bounced"], ["P4"])
        again = plan_fixes([{**rows[0]}, {**rows[1], "possible_duplicate_of": "P1"}])
        self.assertEqual(again["duplicates"], [])  # already marked

    def test_runs_before_approval_and_only_in_agent_runs(self):
        steps = [s.key for s in plan({**READY, "autopilot": True, "data_issues": 3, "auto_approve": True,
                                      "pending_qualified": 2})]
        self.assertLess(steps.index("data_quality"), steps.index("auto_review"))
        orchestrator = read("agents", "orchestrator.py")
        self.assertIn("plan(collect_state(company, deep=True))", orchestrator)


class TelephonyTests(unittest.TestCase):
    def test_originate(self):
        query, body = originate_params("201", "01711-123456", "from-internal", "09612345678", "rsa-1", "CRM-LEAD-1")
        self.assertIn("endpoint=PJSIP%2F201", query)
        self.assertIn("extension=8801711123456", query)  # E.164 digits: the dial plan picks the trunk
        self.assertIn("callerId=09612345678", query)
        self.assertEqual(body["variables"]["RECKON_REFERENCE"], "CRM-LEAD-1")

    def test_events(self):
        self.assertEqual(call_status("ANSWER"), "Completed")
        self.assertEqual(call_status("NOANSWER"), "No Answer")
        self.assertEqual(call_status("CHANUNAVAIL"), "Failed")
        event = normalize_event({"uniqueid": "171.1", "dialstatus": "BUSY", "direction": "inbound", "src": "+8801711",
                                 "billsec": "42.6"})
        self.assertEqual((event["id"], event["status"], event["type"], event["duration"]), ("171.1", "Busy", "Incoming", 42))

    def test_signed_webhook_and_https(self):
        api = read("api_telephony.py").split("def call_event(")[1]
        self.assertLess(api.index("verify_signature("), api.index("apply_event("))
        self.assertIn('allow_guest=True, methods=["POST"]', read("api_telephony.py"))
        self.assertIn('url.startswith("https://")', read("telephony.py"))


class DeliverabilityTests(unittest.TestCase):
    def test_allowlist(self):
        lines = "boss@reckon.tech\n@reckon.tech\n+8801711000000"
        self.assertTrue(allowed("someone@reckon.tech", "Email", lines))
        self.assertTrue(allowed("BOSS@reckon.tech", "Email", "boss@reckon.tech"))
        self.assertFalse(allowed("info@naharagro.com", "Email", lines))
        self.assertTrue(allowed("01711-000000", "WhatsApp", lines))
        self.assertFalse(allowed("+8801999000000", "WhatsApp", lines))
        self.assertFalse(allowed(None, "Email", lines))

    def test_warmup(self):
        self.assertEqual(warmup_limit(20, 20, 0, 200), 20)
        self.assertEqual(warmup_limit(20, 20, 5, 200), 50)
        self.assertEqual(warmup_limit(20, 20, 30, 200), 200)  # capped at the Company's limit

    def test_dns(self):
        good = evaluate_dns(["v=spf1 include:_spf.google.com ~all"], ["v=DMARC1; p=quarantine"], "google")
        self.assertTrue(all(c["ok"] for c in good))
        bad = evaluate_dns(["v=spf1 a", "v=spf1 mx"], [], None)
        self.assertEqual([c["ok"] for c in bad], [False, False, False])
        self.assertIn("Merge", bad[0]["advice"])
        self.assertIn("monitoring", evaluate_dns(["v=spf1 a ~all"], ["v=DMARC1; p=none"], "k1")[1]["advice"])

    def test_spf_syntax(self):
        from reckon_sales_agent.agents.deliverability import spf_syntax

        # Live: reckon.tech's SPF had a Facebook verification string glued to "~all".
        broken = ("v=spf1 ip4:209.74.67.151 include:spf.web-hosting.com a mx include:_spf.google.com "
                  "~allfacebook-domain-verification=3d7b01v7619vgxxtfe3ta0m2pfvq55")
        self.assertIn("invalid part", spf_syntax(broken))
        self.assertFalse(evaluate_dns([broken], ["v=DMARC1; p=quarantine"], "default")[0]["ok"])
        self.assertEqual(spf_syntax("v=spf1 ip4:1.2.3.4 include:_spf.google.com -all"), "")
        self.assertEqual(spf_syntax("v=spf1 redirect=_spf.example.com"), "")
        self.assertIn("end with", spf_syntax("v=spf1 a mx"))
        many = "v=spf1 " + " ".join(f"include:s{i}.example.com" for i in range(11)) + " ~all"
        self.assertIn("lookups", spf_syntax(many))

    def test_ai_errors_say_why(self):
        from reckon_sales_agent.providers.llm import provider_reason

        class Exc(Exception):
            body = {"type": "error", "error": {"type": "invalid_request_error",
                                               "message": "Your credit balance is too low to access the API."}}

        self.assertEqual(provider_reason(Exc()), "Your credit balance is too low to access the API.")
        self.assertEqual(provider_reason(ValueError("boom")), "boom")

    def test_account_problems_pause_ai(self):
        from reckon_sales_agent.providers.llm import blocks_account

        # Live: "Your credit balance is too low…" on every call, every hour.
        self.assertTrue(blocks_account(400, "Your credit balance is too low to access the Anthropic API."))
        self.assertTrue(blocks_account(401, "invalid x-api-key"))
        self.assertFalse(blocks_account(400, "max_tokens: too large"))  # one bad request, not the account
        steps = plan({**READY, "ai_blocked": "Your credit balance is too low."})
        self.assertEqual((steps[0].key, steps[0].kind), ("ai_blocked", ASK))
        self.assertIn("if ai_blocked():", read("providers", "factory.py").split("def get_llm(")[1])

    def test_send_path(self):
        send = read("campaigns", "engine.py").split("def send_message(")[1].split("\ndef ")[0]
        self.assertIn('settings.get("allowlist_only") and not allowed(', send)
        self.assertIn("today_email_limit(settings)", send)
        self.assertLess(send.index("allowlist_only"), send.index("if not settings.outbound_enabled:"))


class TemplateTests(unittest.TestCase):
    def test_meta_numbering(self):
        body, order = meta_body("Hi {{business_name}}, {{offer}} for {{business_name}}")
        self.assertEqual(body, "Hi {{1}}, {{2}} for {{1}}")
        self.assertEqual(order, ["business_name", "offer"])
        self.assertEqual(template_issues("WhatsApp", body, "business_name,offer"), [])
        self.assertTrue(template_issues("WhatsApp", "Hi {{1}} {{3}}", "a,b"))  # gap in numbering
        self.assertTrue(template_issues("WhatsApp", "Hi {{1}}", ""))  # not mapped
        self.assertEqual(template_issues("Email", "Hi {{1}}", ""), [])

    def test_governance(self):
        templates = read("agents", "templates.py")
        self.assertIn('"status": "Draft"', templates.split("def write_template(")[1].split("\ndef ")[0])
        self.assertIn('template.status != "Approved"', templates.split("def apply_to_step(")[1].split("\ndef ")[0])
        broadcast = templates.split("def start_broadcast(")[1]
        self.assertIn('db_set("status", "Pending Approval")', broadcast)  # a person launches it
        controller = read("reckon_sales_agent", "doctype", "sales_message_template", "sales_message_template.py")
        self.assertIn('self.status, self.approved_by, self.approved_on = "Draft", None, None', controller)


class ConversationTests(unittest.TestCase):
    def test_channel_choice(self):
        now = datetime(2026, 10, 27, 12, 0)
        lead = {"email": "a@b.com", "phone": "+8801711", "whatsapp_consent": 1}
        self.assertEqual(choose_channel(lead, now - timedelta(hours=2), now)[0], "WhatsApp")
        self.assertEqual(choose_channel(lead, now - timedelta(hours=30), now)[0], "Email")  # window closed
        self.assertEqual(choose_channel({**lead, "whatsapp_consent": 0}, now, now)[0], "Email")
        self.assertIsNone(choose_channel({"phone": "+880"}, None, now)[0])  # call instead
        self.assertTrue(needs_reply(now, now - timedelta(hours=1)))
        self.assertFalse(needs_reply(now - timedelta(hours=2), now))
        self.assertFalse(needs_reply(None, None))

    def test_only_written_messages_ask_for_a_reply(self):
        from reckon_sales_agent.agents.omni import INBOUND

        self.assertEqual(INBOUND, ("received",))  # a "not interested" call never triggers an AI message

    def test_plan_and_governance(self):
        auto = {**READY, "autopilot": True, "replies_to_draft": 2, "conversations_waiting": 3,
                "meetings_to_book": 1}
        keys = [(s.key, s.kind) for s in plan(auto)]
        self.assertIn(("draft_replies", DO), keys)
        self.assertIn(("conversations", ASK), keys)
        self.assertIn(("meetings", ASK), keys)
        omni = read("agents", "omni.py").split("def draft_reply(")[1]
        self.assertIn('"status": "Draft"', omni)
        self.assertIn("check_step(", omni)
        api = read("api_conversations.py").split("def approve_and_send(")[1].split("\ndef ")[0]
        self.assertIn("api.approve_messages(", api)  # the approver check stays


class RegistrationTests(unittest.TestCase):
    def test_pages_doctypes_and_fields(self):
        from reckon_sales_agent.constants import ALLOWED_PAGES, COMPANY_DOCTYPES

        for page in ("sales-inbox", "sales-meetings", "sales-templates"):
            self.assertIn(page, ALLOWED_PAGES)
            folder = page.replace("-", "_")
            script = read("reckon_sales_agent", "page", folder, f"{folder}.js")
            self.assertIn("(() => {", script)
        for doctype in ("Sales Meeting", "Sales Message Template"):
            self.assertIn(doctype, COMPANY_DOCTYPES)
        settings = json.loads(read("reckon_sales_agent", "doctype", "sales_agent_settings", "sales_agent_settings.json"))
        names = [f["fieldname"] for f in settings["fields"]]
        self.assertEqual(names, settings["field_order"])
        for field in ("meeting_days", "telephony_provider", "ari_password", "telephony_webhook_secret",
                      "allowlist_only", "warmup_enabled", "first_send_on"):
            self.assertIn(field, names)
        password = {f["fieldname"]: f["fieldtype"] for f in settings["fields"]}
        self.assertEqual(password["ari_password"], "Password")
        self.assertIn("ensure_telephony_fields()", read("install.py").split("def after_migrate(")[1].split("\ndef ")[0])


if __name__ == "__main__":
    unittest.main()

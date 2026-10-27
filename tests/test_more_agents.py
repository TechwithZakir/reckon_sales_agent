"""Deal coach, forecast, compliance, signals, competitor, customer, voice, dialer, channel analytics, inbound ad
leads (no bench)."""
import json
import sys
import unittest
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from reckon_sales_agent.agents.analytics import AGENT_FAMILY, channel_table  # noqa: E402
from reckon_sales_agent.agents.competitors import on_page, parse_competitors, pick_pages  # noqa: E402
from reckon_sales_agent.agents.compliance import calling_allowed, parse_hours, unapproved  # noqa: E402
from reckon_sales_agent.agents.customers import growing, lapsed  # noqa: E402
from reckon_sales_agent.agents.deals import calibration, deal_health, forecast, loss_summary  # noqa: E402
from reckon_sales_agent.agents.orchestrator import ASK, DO, plan  # noqa: E402
from reckon_sales_agent.agents.signals import signal_raised  # noqa: E402
from reckon_sales_agent.agents.social_connect import (  # noqa: E402
    LINKEDIN_LEAD_SCOPES,
    META_SCOPES,
    authorize_url,
)
from reckon_sales_agent.agents.voice import same_host  # noqa: E402
from reckon_sales_agent.leads_bridge import (  # noqa: E402
    form_questions,
    leadgen_events,
    linkedin_lead_values,
    meta_lead_values,
)

APP = Path(__file__).parents[1] / "reckon_sales_agent"
TODAY = date(2026, 10, 28)
READY = {"has_profile": True, "brief_status": "Approved", "brief": "B1", "sources_ready": True, "ai": True}


def read(*parts):
    return APP.joinpath(*parts).read_text(encoding="utf-8")


class DealCoachTests(unittest.TestCase):
    def deal(self, **kw):
        return {"status_type": "Ongoing", "last_activity": datetime(2026, 10, 1), "next_step": "Send price list",
                "probability": 30, "expected_closure_date": None, **kw}

    def test_stuck_overdue_and_healthy(self):
        stuck = deal_health(self.deal(), TODAY)
        self.assertEqual((stuck["problem"], stuck["days"]), ("stuck", 27))
        self.assertIn("Send price list", stuck["action"])
        self.assertIn("No next step", deal_health(self.deal(next_step=None), TODAY)["action"])
        self.assertIn("proposal", deal_health(self.deal(probability=70), TODAY)["action"])
        overdue = deal_health(self.deal(expected_closure_date="2026-10-20", last_activity=datetime(2026, 10, 27)), TODAY)
        self.assertEqual((overdue["problem"], overdue["days"]), ("overdue", 8))
        self.assertIsNone(deal_health(self.deal(last_activity=datetime(2026, 10, 25)), TODAY))
        self.assertIsNone(deal_health(self.deal(status_type="Won"), TODAY))
        self.assertIsNone(deal_health(self.deal(status_type="On Hold", last_activity=datetime(2026, 10, 10)), TODAY))

    def test_loss_reasons(self):
        self.assertEqual(loss_summary(["Price", None, "Price", "Timing"]),
                         [("Price", 2), ("No reason given", 1), ("Timing", 1)])

    def test_coach_only_creates_internal_tasks(self):
        coach = read("agents", "deals.py").split("def coach(")[1].split("\ndef ")[0]
        self.assertIn('"CRM Task"', coach)
        self.assertIn("-7", coach)  # at most weekly per deal
        proposal = read("agents", "deals.py").split("def draft_proposal(")[1].split("\ndef ")[0]
        self.assertIn('"FCRM Note"', proposal)  # a private note, never a message
        self.assertNotIn("send_message", proposal)


class ForecastTests(unittest.TestCase):
    def test_expected_value_and_range(self):
        deals = [{"value": 100000, "probability": 50, "expected_closure_date": "2026-11-10"},
                 {"value": 50000, "probability": 100, "expected_closure_date": "2026-11-20"},
                 {"value": 999999, "probability": 90, "expected_closure_date": "2027-06-01"},  # beyond 90 days
                 {"value": 10000, "probability": 80, "status_type": "Lost"}]
        result = forecast(deals, TODAY, horizon_days=90)
        self.assertEqual((result["deals"], result["expected"]), (2, 100000.0))
        self.assertLess(result["low"], result["expected"])
        self.assertGreater(result["high"], result["expected"])
        self.assertEqual(forecast(deals, TODAY, horizon_days=10)["deals"], 0)

    def test_calibration_against_the_companys_own_win_rate(self):
        self.assertEqual(calibration([0.5] * 5, [True] * 5), 1.0)  # too few closed deals
        self.assertEqual(calibration([0.8] * 10, [True] * 2 + [False] * 8), 0.5)  # over-optimistic: halved, floor
        self.assertAlmostEqual(calibration([0.4] * 10, [True] * 5 + [False] * 5), 1.25)


class ComplianceTests(unittest.TestCase):
    def test_calling_hours(self):
        self.assertEqual(parse_hours("9-20"), (datetime(1, 1, 1, 9).time(), datetime(1, 1, 1, 20).time()))
        self.assertEqual(parse_hours("nonsense")[0].hour, 9)
        self.assertTrue(calling_allowed(datetime(2026, 10, 28, 10, 30)))
        self.assertFalse(calling_allowed(datetime(2026, 10, 28, 21, 0)))
        self.assertFalse(calling_allowed(datetime(2026, 10, 28, 8, 59)))
        self.assertTrue(calling_allowed(datetime(2026, 10, 28, 8, 30), "08:00-18:00"))
        self.assertIn("check_call(company)", read("telephony.py").split("def click_to_call(")[1])

    def test_audit_finds_unapproved_messages(self):
        rows = [{"status": "Sent", "channel": "Email", "approved_by": None, "auto_approved_by_policy": 0},
                {"status": "Sent", "channel": "Email", "approved_by": "a@b.com"},
                {"status": "Sent", "channel": "Messenger", "auto_approved_by_policy": 1},
                {"status": "Sent", "channel": "Call Task"},
                {"status": "Dry Run", "channel": "Email"}]
        self.assertEqual(len(unapproved(rows)), 1)

    def test_only_ever_stricter(self):
        source = read("agents", "compliance.py").split("def _run(")[1]
        self.assertIn('"do_not_contact", 1', source)
        self.assertNotIn('"do_not_contact", 0', source)
        self.assertNotIn("active\": 0", source)  # never removes a suppression


class SignalsCompetitorCustomerTests(unittest.TestCase):
    def test_signals(self):
        self.assertTrue(signal_raised(20, 40))
        self.assertFalse(signal_raised(20, 30))
        self.assertFalse(signal_raised(None, 90))

    def test_competitors(self):
        self.assertEqual(parse_competitors("Sokrio | sokrio.com\nbad line\nDATABIZ|https://databiz.com.bd"),
                         [("Sokrio", "https://sokrio.com"), ("DATABIZ", "https://databiz.com.bd")])
        self.assertEqual(pick_pages(["https://x.com/careers", "https://x.com/pricing", "https://x.com/clients"]),
                         ["https://x.com/pricing", "https://x.com/clients"])
        pages = {"https://x.com/pricing": "Plans start at   Tk 2,500 per user\nper month."}
        self.assertEqual(on_page("plans start at Tk 2,500 per user per month", pages), "https://x.com/pricing")
        self.assertIsNone(on_page("Plans start at Tk 1,000 per user per month", pages))  # not what the page says

    def test_competitor_facts_stay_out_of_outreach(self):
        loader = read("agents", "content_agent.py").split("def approved_knowledge(")[1].split("\ndef ")[0]
        self.assertIn('include_competitors or r.category != "Competitor"', loader)
        self.assertIn("include_competitors=True", read("agents", "deals.py"))
        items = json.loads(read("reckon_sales_agent", "doctype", "sales_knowledge_item", "sales_knowledge_item.json"))
        category = next(f for f in items["fields"] if f["fieldname"] == "category")
        self.assertIn("Competitor", category["options"].split("\n"))

    def test_customers(self):
        regular = [date(2026, 5, 1), date(2026, 6, 1), date(2026, 7, 1), date(2026, 8, 1)]
        self.assertEqual(lapsed(regular, TODAY), {"days": 88, "usual": 31})
        self.assertIsNone(lapsed(regular + [date(2026, 10, 1)], TODAY))
        self.assertIsNone(lapsed(regular[:2], TODAY))  # not regular yet
        self.assertTrue(growing(130000, 100000))
        self.assertFalse(growing(120000, 100000))
        self.assertFalse(growing(50000, 0))


class PlanTests(unittest.TestCase):
    def test_periodic_agents_run_only_on_autopilot_and_when_due(self):
        state = {**READY, "autopilot": True, "deals_stuck": 2, "coach_due": True, "forecast_due": True,
                 "open_deals": 5, "compliance_fixes": 3, "signals_due": True, "competitors_due": True,
                 "customers_due": True, "new_signals": 2, "competitor_drafts": 4, "compliance_audit": 1}
        kinds = {(s.key, s.kind) for s in plan(state)}
        for key in ("coach_deals", "forecast", "compliance", "recheck_signals", "watch_competitors", "customer_checkins"):
            self.assertIn((key, DO), kinds)
        for key in ("deals", "signals", "approve_competitor", "compliance_review"):
            self.assertIn((key, ASK), kinds)
        manual = {(s.key, s.kind) for s in plan({**state, "autopilot": False})}
        self.assertIn(("compliance", ASK), manual)
        self.assertFalse({k for k, kind in manual if kind == DO})
        later = {s.key for s in plan({**state, "coach_due": False, "forecast_due": False})}
        self.assertNotIn("coach_deals", later)
        self.assertNotIn("forecast", later)

    def test_new_lanes(self):
        studio = read("api_agent_studio.py").split("AGENTS = (")[1].split(")")[0]
        for agent in ("Deals", "Customers", "Compliance"):
            self.assertIn(f'"{agent}"', studio)
            self.assertIn(agent, AGENT_FAMILY)


class VoiceAndDialerTests(unittest.TestCase):
    def test_recordings_from_the_companys_own_pbx(self):
        self.assertTrue(same_host("https://pbx.acme.bd/rec/1.wav", "https://pbx.acme.bd:8089"))
        self.assertFalse(same_host("https://evil.example/rec.wav", "https://pbx.acme.bd"))
        self.assertFalse(same_host("https://pbx.acme.bd/rec.wav", None))
        voice = read("agents", "voice.py")
        self.assertIn("validate_url(url)", voice)  # anything else must be a public address
        self.assertIn("MAX_BYTES", voice.split("def _recording(")[1])
        self.assertIn("queue(name)", read("telephony.py").split("def apply_event(")[1])

    def test_dialer_respects_rules(self):
        dialer = read("telephony.py").split("def next_call(")[1]
        self.assertIn("do_not_contact", dialer)
        self.assertIn("already called today", dialer)
        self.assertIn("click_to_call(", dialer)  # which checks calling hours


class ChannelAnalyticsTests(unittest.TestCase):
    def test_channel_rows(self):
        rows = channel_table(["Email", "Messenger", "Messenger", "Call"], ["Messenger"], {"Messenger": [4.0, 10.0]},
                             ["Messenger", "LinkedIn"], ["Messenger"])
        by = {r["channel"]: r for r in rows}
        self.assertEqual([r["channel"] for r in rows][:3], ["Email", "Messenger", "Call"])
        self.assertEqual((by["Messenger"]["inbound"], by["Messenger"]["answered"], by["Messenger"]["median_minutes"],
                          by["Messenger"]["deals"]), (2, 1, 7.0, 1))
        self.assertEqual(by["LinkedIn"]["leads"], 1)
        self.assertIn('"channels": channel_report(company', read("agents", "analytics_agent.py"))


class InboundAdLeadTests(unittest.TestCase):
    def test_meta_real_time(self):
        payload = {"object": "page", "entry": [{"id": "P1", "changes": [
            {"field": "leadgen", "value": {"leadgen_id": "L9", "page_id": "P1", "form_id": "F1"}},
            {"field": "feed", "value": {"item": "comment"}}]}]}
        self.assertEqual(leadgen_events(payload), [{"page_id": "P1", "leadgen_id": "L9", "form_id": "F1"}])
        values = meta_lead_values([{"name": "full_name", "values": ["Karim Uddin"]},
                                   {"name": "phone_number", "values": ["+8801711000000"]},
                                   {"name": "company_name", "values": ["Karim Traders"]}])
        self.assertEqual((values["business_name"], values["phone"]), ("Karim Traders", "+8801711000000"))
        self.assertIn("leads_retrieval", META_SCOPES)
        self.assertIn("leadgen", read("agents", "social_connect.py").split("subscribed_fields")[1][:80])
        bridge = read("leads_bridge.py").split("def speed_to_lead(")[1].split("\ndef ")[0]
        self.assertIn("Already received in real time", bridge)  # the CRM's later sync only links the lead

    def test_linkedin_lead_forms(self):
        form = {"content": {"questions": [{"questionId": 1, "predefinedField": "FIRST_NAME"},
                                          {"questionId": 2, "predefinedField": "EMAIL"},
                                          {"questionId": 3, "predefinedField": "COMPANY_NAME"}]}}
        questions = form_questions(form)
        response = {"formResponse": {"answers": [
            {"questionId": 1, "answerDetails": {"textQuestionAnswer": {"answer": "Rahim"}}},
            {"questionId": 2, "answerDetails": {"textQuestionAnswer": {"answer": "rahim@x.com"}}},
            {"questionId": 3, "answerDetails": {"textQuestionAnswer": {"answer": "Rahim Pharma"}}}]}}
        values = linkedin_lead_values(response, questions)
        self.assertEqual((values["business_name"], values["email"]), ("Rahim Pharma", "rahim@x.com"))
        self.assertIn("LinkedIn lead form", values["provenance_json"])
        self.assertIn("r_marketing_leadgen_automation", LINKEDIN_LEAD_SCOPES)
        self.assertIn("r_marketing_leadgen_automation", authorize_url("linkedin_leads", "c", "https://x/cb", "s"))
        self.assertIn('"reckon_sales_agent.leads_bridge.sync_linkedin_leads"', read("hooks.py"))


if __name__ == "__main__":
    unittest.main()

"""Analytics agent: attribution funnels, pilot hold-outs and lift, recommendations (no bench needed)."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from reckon_sales_agent.agents.analytics import funnel, in_holdout, pilot_result, recommendations  # noqa: E402
from reckon_sales_agent.agents.approvals import campaign_payload, fingerprint  # noqa: E402
from reckon_sales_agent.campaigns.metrics import summarize  # noqa: E402

APP = Path(__file__).parents[1] / "reckon_sales_agent"


def row(segment, source, **stages):
    return {"segment": segment, "source": source, "campaign": "C1", "won_value": stages.pop("value", 0), **stages}


class DashboardTests(unittest.TestCase):
    def test_daily_buckets(self):
        from reckon_sales_agent.agents.analytics import daily_buckets

        stamps = ["2026-10-25 09:00:00", "2026-10-27 10:00:00", "2026-10-27 23:59:59", "2026-10-20 08:00:00"]
        self.assertEqual(daily_buckets(stamps, "2026-10-25", 3), [1, 0, 2])  # the day outside is ignored

    def test_reply_rate_is_a_share_of_contacted_leads(self):
        from reckon_sales_agent.agents.analytics import CONTACT_EVENTS, REPLY_EVENTS, reply_rate

        # Live: two replies to one contacted lead showed "200%".
        events = [("dry_run", "M1"), ("received", "M1"), ("received", "M1"), ("received", "M9")]
        self.assertEqual(reply_rate(events, CONTACT_EVENTS, REPLY_EVENTS), 100.0)  # M9 was not contacted here
        self.assertEqual(reply_rate([("sent", "M1"), ("sent", "M2")], CONTACT_EVENTS, REPLY_EVENTS), 0.0)
        self.assertEqual(reply_rate([], CONTACT_EVENTS, REPLY_EVENTS), 0.0)

    def test_old_activity_rows_are_attributed_by_action(self):
        dash = (APP / "agents" / "analytics_agent.py").read_text(encoding="utf-8").split("def dashboard(")[1]
        self.assertIn("row.agent or agent_for(row.action)", dash)

    def test_change_against_the_previous_period(self):
        from reckon_sales_agent.agents.analytics import change

        self.assertEqual(change(15, 10)["delta_pct"], 50.0)
        self.assertEqual(change(5, 10)["delta_pct"], -50.0)
        self.assertIsNone(change(7, 0)["delta_pct"])  # no base: "no earlier data", never infinity

    def test_contact_counts_answered_calls(self):
        from reckon_sales_agent.agents.analytics import (
            CONTACT_EVENTS,
            POSITIVE_EVENTS,
            REPLY_EVENTS,
        )

        self.assertIn("call_interested", CONTACT_EVENTS)
        self.assertNotIn("call_no_answer", CONTACT_EVENTS)
        self.assertIn("call_interested", POSITIVE_EVENTS)
        self.assertNotIn("call_wrong_number", REPLY_EVENTS)

    def test_dashboard_api_checks_the_campaign(self):
        api = (APP / "api.py").read_text(encoding="utf-8").split("def analytics_dashboard(")[1].split("\ndef ")[0]
        self.assertIn('get_tenant_doc("Sales Campaign", campaign, "read")', api)
        self.assertIn("max(7, min(int(days or 30), 365))", api)
        dash = (APP / "agents" / "analytics_agent.py").read_text(encoding="utf-8").split("def dashboard(")[1]
        self.assertNotIn("count(name)", dash.split("\ndef ")[0])  # Frappe 16: no SQL functions in fields


class FunnelTests(unittest.TestCase):
    ROWS = [
        row("Pharma distributors", "brave_place_search", approved=True, in_crm=True, contacted=True, replied=True,
            positive=True, meetings=True, deals=True, won=True, value=120000),
        row("Pharma distributors", "brave_place_search", approved=True, contacted=True, replied=True),
        row("Pharma distributors", "scrapingdog_google_maps", approved=True, contacted=True),
        row("FMCG dealers", "brave_llm_context", approved=True, contacted=True),
        row("FMCG dealers", "brave_llm_context"),
    ]

    def test_groups_rates_and_order(self):
        segments = funnel(self.ROWS, "segment")
        self.assertEqual([g["label"] for g in segments], ["Pharma distributors", "FMCG dealers"])  # revenue first
        pharma = segments[0]
        self.assertEqual((pharma["prospects"], pharma["contacted"], pharma["replied"], pharma["won"]), (3, 3, 2, 1))
        self.assertEqual(pharma["reply_rate"], 66.7)
        self.assertEqual(pharma["deal_rate"], 33.3)
        self.assertEqual(pharma["won_value"], 120000)
        self.assertEqual(funnel(self.ROWS, "source")[0]["label"], "brave_place_search")
        self.assertEqual(funnel([], "segment"), [])


class HoldoutTests(unittest.TestCase):
    def test_assignment_is_stable_and_close_to_the_share(self):
        seeds = [f"CAMP-1:PROS-{i}" for i in range(2000)]
        self.assertEqual([in_holdout(s, 20) for s in seeds[:50]], [in_holdout(s, 20) for s in seeds[:50]])
        share = sum(in_holdout(s, 20) for s in seeds) / len(seeds)
        self.assertGreater(share, 0.16)
        self.assertLess(share, 0.24)
        self.assertFalse(any(in_holdout(s, 0) for s in seeds[:100]))
        self.assertLess(sum(in_holdout(s, 90) for s in seeds) / len(seeds), 0.55)  # capped at 50%


class PilotTests(unittest.TestCase):
    def test_verdicts(self):
        self.assertEqual(pilot_result(12, 3, 4, 0)["verdict"], "too_early")
        scale = pilot_result(200, 30, 50, 1)
        self.assertEqual(scale["verdict"], "scale")
        self.assertTrue(scale["significant"])
        self.assertEqual((scale["treated_rate"], scale["holdout_rate"], scale["lift_points"]), (15.0, 2.0, 13.0))
        self.assertEqual(pilot_result(200, 2, 50, 10)["verdict"], "stop")
        self.assertEqual(pilot_result(100, 6, 25, 1)["verdict"], "iterate")
        self.assertIsNone(pilot_result(100, 5, 30, 0)["relative_lift"])  # no baseline conversions


class RecommendationTests(unittest.TestCase):
    def test_rules(self):
        metrics = {"totals": {"outreach": 120, "bounced": 9}, "unsubscribe_rate": 3.5,
                   "by_channel": {"SMS": {"outreach": 40, "positive": 0}, "Email": {"outreach": 80, "positive": 4}},
                   "by_step": {"1": {"outreach": 60, "replies": 6}, "2": {"outreach": 40, "replies": 2},
                               "3": {"outreach": 30, "replies": 0}}}
        segments = [{"label": "Pharma", "contacted": 40, "deal_rate": 10.0, "positive": 6},
                    {"label": "FMCG", "contacted": 30, "deal_rate": 2.0, "positive": 1}]
        tips = " ".join(recommendations(metrics, segments))
        for expected in ("SMS: 40 messages and no positive reply", "Unsubscribe rate is 3.5%", "emails bounce",
                         "Step 3 gets no replies", "Best segment: Pharma"):
            self.assertIn(expected, tips)
        self.assertIn("Not enough data", recommendations()[0])

    def test_holdout_members_are_not_counted_as_reached(self):
        metrics = summarize([], [{"status": "Active"}, {"status": "Holdout"}, {"status": "Holdout"}],
                            [{"deal_value": 0}])
        self.assertEqual(metrics["conversion_rate"], 100.0)  # one deal over one contacted member


class PilotApprovalTests(unittest.TestCase):
    BASE = {"steps": [], "offer": "DMS", "discovery_campaign": "D1", "minimum_fit_score": 40}

    def test_pilot_settings_are_part_of_the_approval(self):
        plain = campaign_payload(self.BASE)
        self.assertNotIn("pilot", plain["audience"])  # unchanged fingerprint for ordinary campaigns
        pilot = {**self.BASE, "pilot_mode": 1, "holdout_percent": 20, "pilot_max_members": 100}
        self.assertNotEqual(fingerprint(campaign_payload(pilot)), fingerprint(plain))
        bigger = {**pilot, "pilot_max_members": 500}  # expanding the audience needs approval again
        self.assertNotEqual(fingerprint(campaign_payload(pilot)), fingerprint(campaign_payload(bigger)))


class WiringTests(unittest.TestCase):
    def read(self, *parts):
        return APP.joinpath(*parts).read_text(encoding="utf-8")

    def test_engine_and_api(self):
        engine = self.read("campaigns", "engine.py")
        build = engine.split("def build_members(")[1].split("\ndef ")[0]
        self.assertIn("in_holdout(key, campaign.get(\"holdout_percent\") or 20)", build)
        self.assertIn('"Pilot audience limit%"', build)  # waiting members start once a person scales the pilot
        deal = engine.split("def handle_deal(")[1].split("\ndef ")[0]
        self.assertIn('"Holdout"', deal)
        self.assertIn("converted_on", deal)
        api = self.read("api.py")
        for method in ("analytics_overview", "pilot_report"):
            self.assertIn(f"@frappe.whitelist()\ndef {method}(", api)
        self.assertIn("pilot_report(campaign)", self.read("campaigns", "analytics.py"))
        page = self.read("reckon_sales_agent", "page", "sales_analytics", "sales_analytics.js")
        self.assertIn("api.analytics_dashboard", page)
        self.assertIn("(() => {", page)  # nothing leaks into Desk's global scope
        self.assertIn("Show as a table", page)  # every chart has a table view

    def test_fields(self):
        campaign = json.loads(self.read("reckon_sales_agent", "doctype", "sales_campaign", "sales_campaign.json"))
        names = {f["fieldname"] for f in campaign["fields"]}
        self.assertTrue({"pilot_mode", "holdout_percent", "pilot_max_members", "pilot_verdict", "pilot_summary"} <= names)
        member = json.loads(self.read("reckon_sales_agent", "doctype", "sales_campaign_member", "sales_campaign_member.json"))
        status = next(f for f in member["fields"] if f["fieldname"] == "status")
        self.assertIn("Holdout", status["options"])
        self.assertIn("converted_on", {f["fieldname"] for f in member["fields"]})


if __name__ == "__main__":
    unittest.main()

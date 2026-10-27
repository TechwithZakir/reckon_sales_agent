"""Orchestrator and Agent Studio: what the agents do alone, and what always waits for a person (no bench needed)."""
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1]))

from reckon_sales_agent.agents.onboarding import (  # noqa: E402
    PROFILE_SCHEMA,
    clean_profile,
    merge_into,
    rule_profile,
)
from reckon_sales_agent.agents.orchestrator import (  # noqa: E402
    ASK,
    DO,
    DOERS,
    WAIT,
    lane_status,
    pick_segments,
    plan,
)

APP = Path(__file__).parents[1] / "reckon_sales_agent"
READY = {"has_profile": True, "brief_status": "Approved", "brief": "B1", "sources_ready": True, "ai": True}


def keys(state, kind=None):
    return [(s.key, s.kind) for s in plan(state) if kind is None or s.kind == kind]


class PlanTests(unittest.TestCase):
    def test_a_new_company_is_asked_for_one_line_only(self):
        self.assertEqual(keys({}), [("onboard", ASK)])
        self.assertEqual(keys({"has_profile": True, "onboarding": True}), [("onboard", WAIT)])

    def test_market_research_starts_by_itself_the_first_time(self):
        self.assertIn(("research_market", DO), keys({"has_profile": True}))
        self.assertIn(("research_market", WAIT), keys({"has_profile": True, "brief_status": "Researching"}))
        # A failed or stale brief is retried by autopilot, offered to a person otherwise.
        self.assertIn(("research_market", ASK), keys({"has_profile": True, "brief_status": "Failed"}))
        self.assertIn(("research_market", DO), keys({"has_profile": True, "brief_status": "Failed", "autopilot": True}))
        stale = {**READY, "brief_age_days": 31, "autopilot": True}
        self.assertIn(("research_market", DO), keys(stale))
        self.assertNotIn("research_market", [k for k, _ in keys({**READY, "brief_age_days": 30})])

    def test_segments_are_chosen_automatically_only_when_allowed(self):
        ready = {"has_profile": True, "brief_status": "Ready", "brief": "B1"}
        self.assertIn(("approve_segments", ASK), keys(ready))
        self.assertIn(("approve_segments", ASK), keys({**ready, "autopilot": True}))
        self.assertIn(("approve_segments", DO), keys({**ready, "autopilot": True, "auto_segments": True}))

    def test_discovery_and_review(self):
        self.assertIn(("sources", ASK), keys({**READY, "sources_ready": False}))
        self.assertIn(("start_discovery", ASK), keys({**READY, "profiles_without_discovery": 2}))
        self.assertIn(("start_discovery", DO), keys({**READY, "profiles_without_discovery": 2, "autopilot": True}))
        self.assertIn(("discovery", WAIT), keys({**READY, "running_jobs": 1}))
        auto = {**READY, "autopilot": True, "auto_approve": True, "pending_qualified": 4, "pending_human": 2}
        self.assertIn(("auto_review", DO), keys(auto))
        review = next(s for s in plan(auto) if s.key == "review")
        self.assertIn("2 lead(s)", review.detail)  # only the borderline ones reach a person
        manual = next(s for s in plan({**READY, "pending_qualified": 4, "pending_human": 2}) if s.key == "review")
        self.assertIn("6 lead(s)", manual.detail)

    def test_leads_outside_the_market_are_set_aside_only_under_autopilot(self):
        # Live test: 73 leads waited for review, among them Indian companies found before the market filter.
        state = {**READY, "pending_human": 10, "pending_foreign": 3}
        self.assertNotIn("auto_triage", [k for k, _ in keys(state)])
        self.assertIn("10 lead(s)", next(s for s in plan(state) if s.key == "review").detail)
        auto = {**state, "autopilot": True}
        self.assertIn(("auto_triage", DO), keys(auto))
        self.assertIn("7 lead(s)", next(s for s in plan(auto) if s.key == "review").detail)
        order = [k for k, _ in keys({**auto, "auto_approve": True, "pending_qualified": 2})]
        self.assertLess(order.index("auto_triage"), order.index("auto_review"))  # never approve one first

    def test_the_pipeline_keeps_moving_without_a_person(self):
        # Live test: autopilot on, but the segment searches never repeated and 48 weak leads sat in review.
        state = {**READY, "unscheduled_searches": 2, "pending_human": 50, "pending_weak": 48}
        self.assertNotIn("keep_finding", [k for k, _ in keys(state)])  # autopilot off: nothing changes alone
        auto = {**state, "autopilot": True}
        self.assertIn(("keep_finding", DO), keys(auto))
        self.assertIn(("auto_triage", DO), keys(auto))
        self.assertIn("2 lead(s)", next(s for s in plan(auto) if s.key == "review").detail)
        self.assertNotIn("keep_finding", [k for k, _ in keys({**auto, "profiles_without_discovery": 1})])

    def test_qualified_leads_the_rules_decline_reach_a_person(self):
        # Live test: a qualified lead (fit 69, bar 75) was retried hourly and never shown for review.
        auto = {**READY, "autopilot": True, "auto_approve": True, "pending_qualified": 0, "pending_held": 1}
        self.assertNotIn("auto_review", [k for k, _ in keys(auto)])
        self.assertIn("1 lead(s)", next(s for s in plan(auto) if s.key == "review").detail)
        both = {**auto, "pending_qualified": 2, "pending_human": 3}
        self.assertIn(("auto_review", DO), keys(both))
        self.assertIn("4 lead(s)", next(s for s in plan(both) if s.key == "review").detail)
        source = (APP / "agents" / "orchestrator.py").read_text(encoding="utf-8")
        self.assertIn("auto_approval_decision(p, rules, approved_today)",
                      source.split("def _split_qualified(")[1].split("\ndef ")[0])

    def test_set_aside_step_names_each_reason(self):
        step = next(s for s in plan({**READY, "autopilot": True, "pending_demo": 44, "pending_weak": 2})
                    if s.key == "auto_triage")
        self.assertEqual(step.detail, "2 scored below your review threshold, 44 from the demo source.")

    def test_campaigns_are_drafted_with_enough_leads_and_never_launched_alone(self):
        segment = {"discovery": "DISC-1", "label": "Pharma", "count": 6}
        auto = {**READY, "autopilot": True, "segments_ready": [segment], "campaign_min_prospects": 5}
        self.assertIn(("draft_campaign", DO), keys(auto))
        self.assertIn(("draft_campaign", ASK), keys({**auto, "ai": False}))  # no AI: a person writes it
        self.assertEqual(keys({**auto, "segments_ready": [{**segment, "count": 4}]}, DO), [])
        everything = {**auto, "campaigns_pending": [{"name": "C1", "label": "Pilot"}], "drafts_waiting": 3,
                      "open_followups": 1, "pilot_verdicts": [{"name": "C2", "label": "x", "verdict": "scale"},
                                                              {"name": "C3", "label": "y", "verdict": "stop"}]}
        for step in plan(everything):
            if step.key in ("approve_campaign", "approve_drafts", "followups", "scale_campaign", "pause_campaign"):
                self.assertEqual(step.kind, ASK, step.key)

    def test_nothing_that_reaches_a_customer_can_run_automatically(self):
        self.assertEqual(set(DOERS), {"research_market", "approve_segments", "start_discovery", "auto_review",
                                      "auto_triage", "keep_finding", "ai_triage", "learn_targeting", "find_contacts",
                                      "draft_campaign", "pilot_check", "data_quality", "draft_replies",
                                      # periodic agents: internal tasks, notes, research and drafts only
                                      "coach_deals", "forecast", "compliance", "recheck_signals",
                                      "watch_competitors", "customer_checkins"})
        for key in DOERS:
            self.assertNotIn("send", key)
            self.assertNotIn("launch", key)

    def test_pilots_are_measured(self):
        self.assertIn(("pilot_check", DO), keys({**READY, "pilots_to_check": ["C1"]}))

    def test_lane_status(self):
        steps = plan({**READY, "running_jobs": 1, "drafts_waiting": 2})
        self.assertEqual(lane_status(steps, "Research"), "working")
        self.assertEqual(lane_status(steps, "Engagement"), "needs_you")
        self.assertEqual(lane_status(steps, "Analytics"), "idle")

    def test_pick_segments(self):
        rows = [{"name": "a", "priority": 3, "idx": 1}, {"name": "b", "priority": 1, "idx": 2},
                {"name": "c", "priority": 2, "idx": 3}, {"name": "d", "priority": 1, "idx": 4},
                {"name": "e", "priority": 2, "idx": 5}]
        self.assertEqual(pick_segments(rows), ["b", "d", "c"])
        self.assertEqual(pick_segments([{"name": "x", "priority": 4}, {"name": "y", "priority": 3}]), ["y"])
        self.assertEqual(pick_segments([]), [])


class Profile(SimpleNamespace):
    def get(self, key):
        return getattr(self, key, None)

    def set(self, key, value):
        setattr(self, key, value)


class OnboardingTests(unittest.TestCase):
    def test_model_output_is_bounded(self):
        data = clean_profile({"business_name": "  Reckon   Technologies ", "what_we_sell": "x" * 900,
                              "products": ["DMS", "dms", "Van sales app", *[f"p{i}" for i in range(20)]]})
        self.assertEqual(data["business_name"], "Reckon Technologies")
        self.assertEqual(len(data["what_we_sell"]), 500)
        self.assertEqual(data["products"][:2], ["DMS", "Van sales app"])  # case-insensitive duplicates dropped
        self.assertEqual(len(data["products"]), 8)
        self.assertEqual(data["regions"], [])

    def test_schema_is_strict(self):
        self.assertFalse(PROFILE_SCHEMA["additionalProperties"])
        self.assertEqual(set(PROFILE_SCHEMA["required"]), set(PROFILE_SCHEMA["properties"]))

    def test_rules_use_the_home_page(self):
        page = SimpleNamespace(title="Reckon Technologies | Distribution software", description="Cloud DMS for distributors")
        self.assertEqual(rule_profile([page])["business_name"], "Reckon Technologies")
        self.assertEqual(rule_profile([page])["what_we_sell"], "Cloud DMS for distributors")
        self.assertEqual(rule_profile([])["business_name"], "")

    def test_never_overwrites_what_the_manager_wrote(self):
        profile = Profile(company="Reckon Technologies Ltd.", business_name="Reckon Technologies Ltd.",
                          what_we_sell="", products="Our own list", regions="")
        found = clean_profile({"business_name": "Reckon", "what_we_sell": "DMS software", "products": ["DMS"],
                               "regions": ["Dhaka", "Chattogram"]})
        filled = merge_into(profile, found, note="For FMCG and pharma")
        self.assertEqual(profile.products, "Our own list")
        self.assertEqual(profile.regions, "Dhaka\nChattogram")
        self.assertEqual(profile.what_we_sell, "DMS software For FMCG and pharma")
        self.assertEqual(profile.business_name, "Reckon")  # the placeholder (Company name) was replaced
        self.assertEqual(set(filled), {"business_name", "what_we_sell", "regions"})


class WiringTests(unittest.TestCase):
    def read(self, *parts):
        return APP.joinpath(*parts).read_text(encoding="utf-8")

    def test_runs_hourly_and_each_step_is_isolated(self):
        self.assertIn('"reckon_sales_agent.agents.orchestrator.run_all"', self.read("hooks.py"))
        run = self.read("agents", "orchestrator.py").split("\ndef run(")[1].split("\ndef ")[0]
        self.assertIn("frappe.db.rollback()", run)
        self.assertIn("if step.kind != DO", run)

    def test_studio_api(self):
        api = self.read("api_agent_studio.py")
        for method in ("state", "onboard", "set_autopilot", "run_now", "act"):
            self.assertIn(f"@frappe.whitelist()\ndef {method}(", api)
        act = api.split("def act(")[1].split("\ndef ")[0]
        # Approvals go through the same checked API as the forms (approver role, content check, entitlement).
        self.assertIn("api.approve_campaign(", act)
        self.assertIn("api.approve_messages(", act)
        self.assertIn("api.review_prospects(", act)
        autopilot = api.split("def set_autopilot(")[1].split("\ndef ")[0]
        self.assertIn('not data.get("consent")', autopilot)
        self.assertIn("autopilot_consent_by", autopilot)
        self.assertNotIn("get_password", api)

    def test_studio_page(self):
        script = self.read("reckon_sales_agent", "page", "sales_agent", "sales_agent.js")
        self.assertIn("(() => {", script)
        for method in ('"state"', '"onboard"', '"set_autopilot"', '"run_now"', '"act"'):
            self.assertIn(method, script)
        self.assertIn("ags-ack", script)  # content issues must be acknowledged before launch
        self.assertNotIn("comment_when", script)  # returns HTML; the page escapes text (seen live)
        self.assertTrue((APP / "reckon_sales_agent" / "page" / "sales_agent" / "sales_agent.css").exists())

    def test_fields(self):
        def fields(folder):
            doc = json.loads(self.read("reckon_sales_agent", "doctype", folder, f"{folder}.json"))
            self.assertEqual([f["fieldname"] for f in doc["fields"]], doc["field_order"])
            return {f["fieldname"]: f for f in doc["fields"]}

        settings = fields("sales_agent_settings")
        self.assertEqual(settings["autopilot_enabled"]["default"], "0")  # off until a manager agrees
        for name in ("autopilot_auto_segments", "autopilot_weekly_leads", "autopilot_campaign_min_prospects",
                     "autopilot_consent_by", "autopilot_last_run", "autopilot_summary"):
            self.assertIn(name, settings)
        profile = fields("sales_business_profile")
        self.assertIn("website", profile)
        self.assertIn("Reading website", profile["onboarding_status"]["options"])

    def test_set_aside_rules(self):
        source = self.read("agents", "orchestrator.py")
        weak = source.split("def weak_pending(")[1].split("\ndef ")[0]
        # Only a low score backed by the business's own pages; no website or an unreachable one is no evidence.
        self.assertIn('"research_status": "Done"', weak)
        # Live test: 14 of 20 AI triage calls went to made-up demo leads reopened by the patch.
        self.assertIn('"source_type": ["!=", "fixture"]', self.read("agents", "triage.py").split("def untriaged(")[1])
        self.assertIn("demo_pending(company)", source.split("def _auto_triage(")[1].split("\ndef ")[0])
        patch = APP / "patches" / "reopen_unresearched_set_asides.py"
        self.assertIn('"research_status": ["!=", "Done"]', patch.read_text(encoding="utf-8"))
        self.assertIn("reckon_sales_agent.patches.reopen_unresearched_set_asides", self.read("patches.txt"))
        self.assertIn('"qualification_status": "Needs Review"', weak)
        unscheduled = source.split("def _unscheduled(")[1].split("\ndef ")[0]
        self.assertIn('["is", "not set"]', unscheduled)  # "in ['', None]" never matches NULL
        runner = self.read("discovery", "runner.py")
        self.assertIn('campaign.db_set({"last_run_on": now_datetime(),', runner)
        api = self.read("api_agent_studio.py").split("def set_autopilot(")[1].split("\ndef ")[0]
        self.assertIn('"qualify_threshold"', api)

    def test_a_task_always_has_someone(self):
        channels = self.read("providers", "channels.py")
        task = channels.split("def create_task(")[1].split("\ndef ")[0]
        self.assertIn('or _assignee(prospect_name, settings)', task)  # the named salesperson, else the finder


if __name__ == "__main__":
    unittest.main()

"""AI triage, learning from decisions and contact finding (no bench needed)."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from reckon_sales_agent.agents.contacts import contact_urls, pick_email, site_domain  # noqa: E402
from reckon_sales_agent.agents.learning import learn  # noqa: E402
from reckon_sales_agent.agents.orchestrator import ASK, DO, DOERS, plan  # noqa: E402
from reckon_sales_agent.agents.triage import (  # noqa: E402
    TRIAGE_SCHEMA,
    clean_verdict,
    lead_prompt,
    triage_outcome,
)

APP = Path(__file__).parents[1] / "reckon_sales_agent"
READY = {"has_profile": True, "brief_status": "Approved", "brief": "B1", "sources_ready": True, "ai": True}
FMCG = {"keywords": "FMCG distributor\nfood distributor\nপাইকারি বাজার\nডিস্ট্রিবিউটর",
        "b2b_segments": "distributor\ndealer\nwholesaler", "industries": "FMCG\nFood and beverage",
        "exclude_keywords": "supermarket\nrestaurant"}


def keys(state):
    return [(s.key, s.kind) for s in plan(state)]


class TriageTests(unittest.TestCase):
    def test_only_confident_verdicts_act(self):
        self.assertEqual(triage_outcome("approve", 0.9), "approve")
        self.assertEqual(triage_outcome("approve", 0.7), "person")
        self.assertEqual(triage_outcome("reject", 0.85), "reject")
        self.assertEqual(triage_outcome("unsure", 0.99), "person")
        self.assertEqual(triage_outcome("approve", 0.95, duplicate=True), "person")
        self.assertEqual(triage_outcome("approve", 0.95, do_not_contact=True), "person")
        self.assertEqual(triage_outcome("approve", 0.6, min_confidence=0.5), "approve")

    def test_model_output_is_bounded(self):
        data = clean_verdict({"verdict": "reject", "confidence": 1.7, "business_type": "computer shop",
                              "reason": "Sells computers.", "exclude_term": "  Computer "})
        self.assertEqual((data["verdict"], data["confidence"], data["exclude_term"]), ("reject", 1.0, "computer"))
        self.assertEqual(clean_verdict({"verdict": "maybe"})["verdict"], "unsure")
        approve = clean_verdict({"verdict": "approve", "confidence": 0.9, "exclude_term": "distributor"})
        self.assertEqual(approve["exclude_term"], "")  # only rejections teach exclusions
        self.assertEqual(clean_verdict({"verdict": "reject", "exclude_term": "a b c"})["exclude_term"], "")

    def test_schema_and_prompt(self):
        self.assertFalse(TRIAGE_SCHEMA["additionalProperties"])
        self.assertEqual(set(TRIAGE_SCHEMA["required"]), set(TRIAGE_SCHEMA["properties"]))
        text = lead_prompt({"business_name": "Millennium Computer's", "industry": "ডিস্ট্রিবিউটর", "summary": ""},
                           ["Sells laptops"] * 20)
        self.assertIn("business_name: Millennium Computer's", text)
        self.assertEqual(text.count("fact:"), 15)


class LearningTests(unittest.TestCase):
    def decisions(self):
        # Seen live: the FMCG search found computer shops, banks and wholesale markets.
        rows = [{"keyword": "পাইকারি বাজার", "term": "market", "name": f"Market {i}", "approved": False} for i in range(5)]
        rows += [{"keyword": "ডিস্ট্রিবিউটর", "term": "computer", "name": f"{n} Computer", "approved": False}
                 for n in ("A.B.M", "Millennium", "Rabbi")]
        rows += [{"keyword": "ডিস্ট্রিবিউটর", "term": "bank", "name": "Dhaka Bank", "approved": False},
                 {"keyword": "ডিস্ট্রিবিউটর", "term": "", "name": "Nahar Agro Distributor", "approved": True}]
        return rows

    def test_misfit_markers_become_exclusions_and_dead_keywords_retire(self):
        found = learn(self.decisions(), FMCG)
        self.assertEqual(found["exclude"], ["computer", "market"])  # "bank" seen once only
        self.assertEqual(found["retire"], ["পাইকারি বাজার"])  # five leads, none approved

    def test_guards(self):
        rows = [{"keyword": "x", "term": "distributor", "name": "n", "approved": False}] * 4
        self.assertEqual(learn(rows, FMCG)["exclude"], [])  # describes the wanted buyers
        rows = [{"keyword": "", "term": "agro", "name": "p", "approved": False}] * 4 \
            + [{"keyword": "", "term": "", "name": "Nahar Agro", "approved": True}]
        self.assertEqual(learn(rows, FMCG)["exclude"], [])  # an approved lead carries it
        rows = [{"keyword": "", "term": "supermarket", "name": "s", "approved": False}] * 4
        self.assertEqual(learn(rows, FMCG)["exclude"], [])  # already excluded
        two = {**FMCG, "keywords": "food distributor\nডিস্ট্রিবিউটর"}
        dead = [{"keyword": k, "term": "", "name": "z", "approved": False} for k in ("food distributor", "ডিস্ট্রিবিউটর")
                for _ in range(6)]
        self.assertEqual(learn(dead, two)["retire"], [])  # a profile keeps at least two keywords


class ContactTests(unittest.TestCase):
    def test_pick_email(self):
        site = "https://www.naharagro.com/"
        self.assertEqual(pick_email(["owner@gmail.com", "sales@naharagro.com", "info@naharagro.com"], site),
                         "info@naharagro.com")
        self.assertEqual(pick_email(["rahim.k@naharagro.com"], site), "rahim.k@naharagro.com")
        self.assertEqual(pick_email(["hr@mail.naharagro.com"], site), "hr@mail.naharagro.com")
        self.assertEqual(pick_email(["noreply@naharagro.com", "info@gmail.com"], site), "info@gmail.com")
        self.assertEqual(pick_email(["bspfoods@yahoo.com"], "https://bspfoodbd.com"), "bspfoods@yahoo.com")
        self.assertIsNone(pick_email(["a@gmail.com", "b@gmail.com"], "https://x.com"))  # whose is it?
        self.assertIsNone(pick_email(["someone@other.com", "email@example.com"], site))

    def test_urls(self):
        self.assertEqual(site_domain("http://www.Transcombd.com/about"), "transcombd.com")
        urls = contact_urls("https://naharagro.com/products/feed")
        self.assertEqual(urls[0], "https://naharagro.com/")
        self.assertIn("https://naharagro.com/contact-us", urls)


class PlanTests(unittest.TestCase):
    def test_new_agent_steps(self):
        auto = {**READY, "autopilot": True, "ai_triage": True, "pending_untriaged": 6,
                "lessons": ["FMCG: skip computer"], "missing_email": 3}
        self.assertIn(("ai_triage", DO), keys(auto))
        self.assertIn(("learn_targeting", DO), keys(auto))
        self.assertIn(("find_contacts", DO), keys(auto))
        self.assertNotIn("ai_triage", [k for k, _ in keys({**auto, "ai_triage": False})])
        self.assertNotIn("ai_triage", [k for k, _ in keys({**auto, "ai": False})])
        manual = {**auto, "autopilot": False}
        for key in ("ai_triage", "learn_targeting", "find_contacts"):
            self.assertIn((key, ASK), keys(manual), key)
            self.assertIn(key, DOERS)


class WiringTests(unittest.TestCase):
    def read(self, *parts):
        return APP.joinpath(*parts).read_text(encoding="utf-8")

    def test_triage_applies_only_under_autopilot_and_uses_the_review_path(self):
        triage = self.read("agents", "triage.py").split("def triage_prospect(")[1]
        self.assertIn('if apply and outcome in ("approve", "reject"):', triage)
        self.assertIn("review(prospect, outcome,", triage)
        self.assertIn("reserve(prospect.company, USAGE_AI", triage)
        doer = self.read("agents", "orchestrator.py").split("def _ai_triage(")[1].split("\ndef ")[0]
        self.assertIn('settings.get("autopilot_enabled") and settings.get("autopilot_ai_triage")', doer)

    def test_contacts_respect_robots_and_quota(self):
        contacts = self.read("agents", "contacts.py").split("def find_contact(")[1]
        self.assertIn("_robots_allow(", contacts)
        self.assertIn("remaining(prospect.company, USAGE_RESEARCH)", contacts)
        self.assertIn("fill_empty_lead_fields(", contacts)  # never overwrites the CRM

    def test_fields(self):
        prospect = json.loads(self.read("reckon_sales_agent", "doctype", "sales_prospect", "sales_prospect.json"))
        names = [f["fieldname"] for f in prospect["fields"]]
        self.assertEqual(names, prospect["field_order"])
        for name in ("ai_triage_verdict", "ai_triage_confidence", "ai_triage_reason", "ai_business_type",
                     "ai_exclude_term", "ai_triaged_on", "contact_checked_on"):
            self.assertIn(name, names)
        self.assertLess(names.index("merged_into"), names.index("ai_triage_section"))
        settings = json.loads(self.read("reckon_sales_agent", "doctype", "sales_agent_settings",
                                        "sales_agent_settings.json"))
        fields = {f["fieldname"]: f for f in settings["fields"]}
        self.assertEqual(fields["ai_triage_min_confidence"]["default"], "80")

    def test_studio_shows_the_reasoning(self):
        script = self.read("reckon_sales_agent", "page", "sales_agent", "sales_agent.js")
        self.assertIn("ai_triage_reason", script)
        self.assertIn('"learn_targeting"', script)
        self.assertIn("ags-triage", script)


if __name__ == "__main__":
    unittest.main()

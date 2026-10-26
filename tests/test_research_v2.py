"""Research agent v2: corroboration, identity confidence, buying signals, CRM enrichment (no bench needed)."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from reckon_sales_agent.connectors.base import DiscoveryQuery, SourceRecord  # noqa: E402
from reckon_sales_agent.connectors.multi_source import MultiSourceConnector  # noqa: E402
from reckon_sales_agent.research.identity import (  # noqa: E402
    DEFAULT_BUYING_SIGNALS,
    identity_confidence,
    merge_sources,
    origins,
    signal_keywords,
)

APP = Path(__file__).parents[1] / "reckon_sales_agent"


class IdentityTests(unittest.TestCase):
    def test_more_independent_sources_mean_more_confidence(self):
        self.assertEqual(identity_confidence(["brave_place_search"])[0], 40)
        self.assertEqual(identity_confidence(["brave_place_search", "brave_llm_context"])[0], 60)
        self.assertEqual(identity_confidence(["brave_place_search", "brave_llm_context", "scrapingdog_google_maps",
                                              "brave_web_search"])[0], 80)  # capped from sources alone
        self.assertEqual(identity_confidence([])[0], 0)

    def test_one_google_listing_through_three_providers_is_one_origin(self):
        maps = ["scrapingdog_google_maps", "serpapi_google_maps", "google_places_api"]
        self.assertEqual(origins(maps), ["google_maps"])
        self.assertEqual(identity_confidence(maps)[0], 40)

    def test_website_phone_and_search_confirmations(self):
        score, reasons = identity_confidence(["brave_place_search", "scrapingdog_google_maps"], website_confirmed=True,
                                             phone_confirmed=True, search_confirmed=True)
        self.assertEqual(score, 90)
        self.assertEqual(len(reasons), 4)
        self.assertEqual(identity_confidence(["a", "b", "c", "d"], website_confirmed=True, phone_confirmed=True,
                                             search_confirmed=True)[0], 100)

    def test_sources_list_keeps_order_without_duplicates(self):
        self.assertEqual(merge_sources("brave_place_search", "brave_llm_context", "brave_place_search", ""),
                         "brave_place_search\nbrave_llm_context")

    def test_site_confirms_the_name_without_the_listing_descriptor(self):
        from reckon_sales_agent.research.identity import name_on_site

        # Live test: "Nahar Agro Distributor" (Brave Places) could not go to the CRM because the company's own
        # site says "Nahar Agro Limited", so the name stayed under the source's 30-day retention.
        site = "nahar agro group headquartered in south khulshi chattogram"
        self.assertTrue(name_on_site("nahar agro distributor", site))
        self.assertTrue(name_on_site("nahar agro", site))
        self.assertFalse(name_on_site("square traders", "square pharmaceuticals"))  # one word left is too little
        self.assertFalse(name_on_site("nahar agro foods", site))  # "foods" names the business, not a descriptor
        self.assertFalse(name_on_site("nahar agr", site))  # whole words only
        self.assertFalse(name_on_site("", site))

    def test_buying_signal_keywords(self):
        words = signal_keywords("new depot or branch\nexpanding van delivery\nhiring medical/sales reps or delivery staff")
        self.assertIn("নিয়োগ", words)  # Bangla "recruitment"
        self.assertIn("expanding van delivery", words)  # short segment signals are matched as written
        self.assertNotIn("new depot or branch", words)  # four words: too specific to appear verbatim
        self.assertNotIn("hiring medical/sales reps or delivery staff", words)  # too long to match exactly
        self.assertEqual(signal_keywords(None), list(DEFAULT_BUYING_SIGNALS))


def record(name, source, phone=None, website=None):
    return SourceRecord(source, name, None, {"business_name": name, "phone": phone, "website": website,
                                             "city": "Dhaka"}, "2026-10-26T00:00:00Z")


class Source:
    def __init__(self, records):
        self.records = records

    def validate_configuration(self):
        pass

    def default_field_policy(self):
        return {}

    def discover(self, query):
        return iter(self.records)


class CorroborationTests(unittest.TestCase):
    def test_smart_sources_records_who_else_found_the_business(self):
        places = Source([record("Biorex Healthcare Ltd.", "brave_place_search", "01716865535")])
        maps = Source([record("Islamia Drug House", "scrapingdog_google_maps", "01721498574"),
                       record("Biorex Healthcare", "scrapingdog_google_maps", "+8801716865535")])
        context = Source([record("Biorex Healthcare Limited", "brave_llm_context", None, "https://biorex.com.bd")])
        multi = MultiSourceConnector([("brave_place_search", places), ("scrapingdog_google_maps", maps),
                                      ("brave_llm_context", context)])
        records = list(multi.discover(DiscoveryQuery("pharma", "Dhaka", "pharma in Dhaka", 10)))
        biorex = next(r for r in records if r.fields["business_name"].startswith("Biorex"))
        self.assertEqual(biorex.source_key, "brave_place_search")
        # Same phone (Maps) and same normalised name and city ("Ltd." / "Limited"): two more confirmations.
        self.assertEqual(sorted(biorex.corroborated_by), ["brave_llm_context", "scrapingdog_google_maps"])
        self.assertEqual(len(records), 2)  # Biorex once, Islamia Drug House once


class MarketFilterTests(unittest.TestCase):
    def test_foreign_businesses_are_left_out_of_a_bangladesh_campaign(self):
        from reckon_sales_agent.discovery.targeting import foreign_business, market_country

        # Seen live in the FMCG test run: Indian and US companies for "FMCG distributor in Islampur, Dhaka".
        self.assertEqual(foreign_business({"website": "https://bgdpl.in/"}), "website on .in")
        self.assertEqual(foreign_business({"country": "India"}), "listed in India")
        self.assertEqual(foreign_business({"address": "Andheri East, Mumbai 400069"}), "address in Mumbai")
        self.assertEqual(foreign_business({"website": "https://shop.co.uk/"}), "website on .uk")
        for local in ({"website": "https://transcombd.com/"}, {"website": "https://akij.com.bd"},
                      {"website": "https://reckon.io"}, {"address": "Islampur, Dhaka 1100"},
                      {"address": "Road 7, Dhaka (India Bhaban)"}, {}):
            self.assertIsNone(foreign_business(local), local)
        self.assertIsNone(foreign_business({"website": "https://x.in"}, "india"))  # another market: not judged
        self.assertEqual(market_country({"locations": [{"country": "Bangladesh"}, {"country": ""}]}), "bangladesh")
        self.assertEqual(market_country({"locations": [{"country": "India"}]}), "india")
        self.assertEqual(market_country({}), "bangladesh")


class WiringTests(unittest.TestCase):
    def read(self, *parts):
        return (APP.joinpath(*parts)).read_text(encoding="utf-8")

    def test_discovery_and_research_keep_identity_current(self):
        runner = self.read("discovery", "runner.py")
        self.assertIn("record.corroborated_by", runner.split("def upsert_prospect(")[1])
        research = self.read("research", "runner.py")
        start = research.split("def research_prospect(")[1].split("\ndef ")[0]
        self.assertIn("_verify(prospect, platform)", start)
        verify = research.split("def _verify(")[1].split("\ndef ")[0]
        self.assertIn("if prospect.website and corroborated:", verify)  # no paid search when already corroborated
        self.assertIn('active("web_search")', verify)
        self.assertIn("signal_keywords(interests)", research.split("def _profile_for(")[1].split("\ndef ")[0])

    def test_crm_links_existing_leads_and_never_overwrites(self):
        sync = self.read("crm_sync.py")
        self.assertIn("find_existing_lead(data, prospect.company)", sync)
        fill = sync.split("def fill_empty_lead_fields(")[1].split("\ndef ")[0]
        self.assertIn("not current.get(field)", fill)
        scores = sync.split("def update_crm_scores(")[1].split("\ndef ")[0]
        self.assertNotIn('"email"', scores)  # only agent-owned rsa_ fields are written
        self.assertIn("update_crm_scores(prospect)", self.read("qualification", "service.py"))
        install = self.read("install.py")
        self.assertIn("ensure_crm_agent_fields()", install.split("def after_migrate(")[1].split("\ndef ")[0])
        for field in ("rsa_fit_score", "rsa_deal_probability", "rsa_identity_confidence", "rsa_research_summary"):
            self.assertIn(f'"{field}"', install)

    def test_doctype_fields(self):
        prospect = json.loads(self.read("reckon_sales_agent", "doctype", "sales_prospect", "sales_prospect.json"))
        names = {f["fieldname"] for f in prospect["fields"]}
        self.assertTrue({"identity_confidence", "sources_seen", "identity_notes", "search_confirmed"} <= names)
        report = json.loads(self.read("reckon_sales_agent", "doctype", "sales_research_report",
                                      "sales_research_report.json"))
        status = next(f for f in report["fields"] if f["fieldname"] == "status")
        self.assertIn("Skipped", status["options"])


if __name__ == "__main__":
    unittest.main()

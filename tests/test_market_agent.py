"""Phase 1: provider routing and budgets, Smart Sources, and the market research planner (no bench needed)."""
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import requests

sys.path.insert(0, str(Path(__file__).parents[1]))

from reckon_sales_agent.connectors.base import ConnectorError, DiscoveryQuery, SourceRecord  # noqa: E402
from reckon_sales_agent.connectors.brave_search import (  # noqa: E402
    BraveLLMContextConnector,
    BraveSearchConnector,
)
from reckon_sales_agent.connectors.multi_source import MultiSourceConnector, strictest_policy  # noqa: E402
from reckon_sales_agent.providers.routing import (  # noqa: E402
    PROVIDERS,
    BudgetExceeded,
    CountingSession,
    active_providers,
    family_of,
    over_budget,
)
from reckon_sales_agent.research.market_plan import (  # noqa: E402
    MARKET_SCHEMA,
    clean_brief,
    research_queries,
    rule_brief,
    segment_to_targeting,
)

APP = Path(__file__).parents[1] / "reckon_sales_agent"
QUERY = DiscoveryQuery("pharmacy", "Mirpur, Dhaka", "pharmacy in Mirpur, Dhaka", 5)


class RoutingTests(unittest.TestCase):
    def test_brave_is_the_default_and_other_active_providers_follow(self):
        on = {"brave_enabled", "places_enabled", "places_terms_reviewed"}
        self.assertEqual(active_providers("places", lambda f: f in on), ["brave_place_search", "google_places_api"])
        self.assertEqual(active_providers("places", lambda f: f in on, default="google_places_api"),
                         ["google_places_api", "brave_place_search"])
        self.assertEqual(active_providers("web_search", lambda f: f in on), ["brave_web_search"])

    def test_a_provider_needs_all_its_vendor_flags(self):
        on = {"scrapingdog_enabled", "search_scrapingdog_enabled"}  # no Maps / Search responsibility tick
        self.assertEqual(active_providers("places", lambda f: f in on), [])
        self.assertEqual(active_providers("web_search", lambda f: f in on | {"search_terms_ack"}),
                         ["scrapingdog_google_search"])

    def test_browser_bots_are_never_routed_automatically(self):
        self.assertFalse(any("browser" in kind for kind in PROVIDERS))

    def test_families_and_budget_rule(self):
        self.assertEqual(family_of("brave_llm_context"), "brave")
        self.assertEqual(family_of("scrapingdog_google_maps"), family_of("scrapingdog_google_search"))
        self.assertIsNone(family_of("fixture"))
        self.assertFalse(over_budget(999, 0))  # 0 = no cap
        self.assertTrue(over_budget(100, 100))
        self.assertFalse(over_budget(99, 100))

    def test_budget_refusal_is_a_permanent_connector_error(self):
        exc = BudgetExceeded("brave", 1000)
        self.assertIsInstance(exc, ConnectorError)
        self.assertTrue(exc.permanent)
        self.assertEqual(exc.code, "provider_budget")

    def test_counting_session_checks_before_every_request(self):
        class Adapter(requests.adapters.BaseAdapter):
            def send(self, request, **kwargs):
                response = requests.Response()
                response.status_code, response._content, response.url = 200, b"{}", request.url
                return response

            def close(self):
                pass

        calls = []
        session = CountingSession(lambda: calls.append(1))
        session.mount("https://", Adapter())
        session.get("https://api.search.brave.com/res/v1/web/search")
        session.get("https://api.search.brave.com/res/v1/web/search")
        self.assertEqual(len(calls), 2)

        def refuse():
            raise BudgetExceeded("brave", 2)

        blocked = CountingSession(refuse)
        blocked.mount("https://", Adapter())
        with self.assertRaises(BudgetExceeded):
            blocked.get("https://api.search.brave.com/res/v1/web/search")


def record(name, phone=None, website=None, source="x"):
    return SourceRecord(source, name, None, {"business_name": name, "phone": phone, "website": website,
                                             "city": "Dhaka"}, "2026-10-26T00:00:00Z")


class FakeSource:
    def __init__(self, records=None, error=None, policy=None):
        self.records, self.error = records or [], error
        self.policy = policy or {"phone": {"persist": True, "retention_days": 30, "crm_sync": False,
                                           "attribution": "A"}}

    def validate_configuration(self):
        if self.error:
            raise self.error

    def default_field_policy(self):
        return self.policy

    def discover(self, query):
        if self.error:
            raise self.error
        return iter(self.records)


class SmartSourcesTests(unittest.TestCase):
    def test_interleaves_sources_and_keeps_each_business_once(self):
        places = FakeSource([record("Lazz Pharma", "01711-000111"), record("Maa Pharmacy", "01710-415863"),
                             record("Easy Life Pharmacy", "01644-374807")])
        context = FakeSource([record("Lazz Pharma Ltd", "+8801711000111", "https://lazzpharma.com"),
                              record("Aster Pharmacy", None, "https://asterpharmacy.com")])
        multi = MultiSourceConnector([("brave_place_search", places), ("brave_llm_context", context)])
        names = [r.fields["business_name"] for r in multi.discover(QUERY)]
        self.assertEqual(names, ["Lazz Pharma", "Maa Pharmacy", "Aster Pharmacy", "Easy Life Pharmacy"])

    def test_stops_at_the_requested_number(self):
        many = FakeSource([record(f"Shop {i}", f"0171100{i:04d}") for i in range(20)])
        self.assertEqual(len(list(MultiSourceConnector([("a", many)]).discover(QUERY))), 5)

    def test_one_failing_source_does_not_stop_the_others(self):
        broken = FakeSource(error=ConnectorError("HTTP 500", code="http_error"))
        ok = FakeSource([record("Maa Pharmacy", "01710-415863")])
        multi = MultiSourceConnector([("google_places_api", broken), ("brave_place_search", ok)])
        self.assertEqual(len(list(multi.discover(QUERY))), 1)
        self.assertIn("google_places_api", multi.warnings[0])

    def test_all_sources_failing_fails_the_search(self):
        multi = MultiSourceConnector([("a", FakeSource(error=ConnectorError("x", permanent=True, code="auth")))])
        with self.assertRaises(ConnectorError) as ctx:
            list(multi.discover(QUERY))
        self.assertEqual(ctx.exception.code, "auth")

    def test_strictest_policy_wins(self):
        a = {"phone": {"persist": True, "retention_days": 30, "crm_sync": False, "attribution": "Google Maps"}}
        b = {"phone": {"persist": True, "retention_days": None, "crm_sync": True, "attribution": "Brave Places"},
             "email": {"persist": True, "retention_days": None, "crm_sync": True, "attribution": "Brave Places"}}
        merged = strictest_policy([a, b])
        self.assertEqual((merged["phone"]["retention_days"], merged["phone"]["crm_sync"]), (30, False))
        self.assertEqual(merged["phone"]["attribution"], "Google Maps, Brave Places")
        self.assertTrue(merged["email"]["crm_sync"])


PROFILE = {
    "business_name": "Reckon Technologies", "what_we_sell": "Distribution management software",
    "products": "DMS\nVan sales app", "target_industries": "Pharmaceutical\nFMCG",
    "business_types": "distributors\nwholesalers", "regions": "Dhaka\nChattogram",
    "competitors": "Rival Soft", "exclusions": "hospital", "best_customers": "Lazz Pharma | lazzpharma.com | Pharmacy",
    "size_signals": "several branches",
}


class MarketPlanTests(unittest.TestCase):
    def test_research_queries_cover_market_customers_and_competitors(self):
        queries = research_queries(PROFILE, max_queries=20)
        self.assertIn("Pharmaceutical companies in Dhaka", queries)
        self.assertIn("businesses that buy DMS in Bangladesh", queries)
        self.assertIn("companies like Lazz Pharma Bangladesh", queries)
        self.assertIn("Rival Soft customers Bangladesh", queries)
        self.assertEqual(len(queries), len({q.lower() for q in queries}))
        self.assertEqual(len(research_queries(PROFILE, max_queries=3)), 3)

    def test_schema_is_strict_for_structured_output(self):
        segment = MARKET_SCHEMA["properties"]["segments"]["items"]
        self.assertEqual(set(segment["required"]), set(segment["properties"]))
        self.assertFalse(segment["additionalProperties"])
        self.assertEqual(set(MARKET_SCHEMA["required"]), set(MARKET_SCHEMA["properties"]))

    def test_brief_keeps_only_evidence_the_agent_read(self):
        data = {"summary": "Pharma distribution is growing.", "unknowns": ["Market size"], "segments": [
            {"segment_name": "Pharmacy chains", "priority": 9, "fit_reason": "Many branches.",
             "industries": ["Pharmacy"], "business_types": ["pharmacy chain"], "keywords": ["pharmacy", "pharmacy"],
             "bangla_keywords": ["ফার্মেসি"], "locations": ["Mirpur, Dhaka"], "buying_signals": ["new branch"],
             "negative_keywords": ["hospital"],
             "evidence_urls": ["https://read.example/a", "https://invented.example/b"]},
            {"segment_name": "No keywords", "priority": 1, "fit_reason": "", "industries": [], "business_types": [],
             "keywords": [], "bangla_keywords": [], "locations": [], "buying_signals": [], "negative_keywords": [],
             "evidence_urls": []},
            {"segment_name": "Medicine wholesalers", "priority": 2, "fit_reason": "Bulk buyers.", "industries": [],
             "business_types": [], "keywords": ["medicine wholesaler"], "bangla_keywords": [], "locations": [],
             "buying_signals": [], "negative_keywords": [], "evidence_urls": []},
        ]}
        brief = clean_brief(data, {"https://read.example/a"})
        self.assertEqual([s["segment_name"] for s in brief["segments"]], ["Medicine wholesalers", "Pharmacy chains"])
        chains = brief["segments"][1]
        self.assertEqual(chains["priority"], 5)  # clamped
        self.assertEqual(chains["keywords"], ["pharmacy"])  # de-duplicated
        self.assertEqual(chains["evidence_urls"], ["https://read.example/a"])  # invented source dropped

    def test_rule_brief_without_ai(self):
        brief = rule_brief(PROFILE)
        self.assertEqual([s["segment_name"] for s in brief["segments"]], ["Pharmaceutical", "FMCG"])
        self.assertEqual(brief["segments"][0]["keywords"], ["Pharmaceutical distributor", "Pharmaceutical wholesaler"])
        self.assertEqual(brief["segments"][1]["keywords"], ["FMCG distributor", "FMCG wholesaler"])
        self.assertIn("Rival Soft", brief["segments"][0]["negative_keywords"])

    def test_segment_becomes_a_targeting_profile(self):
        segment = {"segment_name": "Pharmacy chains", "keywords": ["pharmacy"], "bangla_keywords": ["ফার্মেসি"],
                   "business_types": ["pharmacy chain"], "industries": ["Pharmacy"], "buying_signals": ["new branch"],
                   "negative_keywords": ["hospital"], "locations": ["Mirpur, Dhaka", "Chattogram"]}
        values = segment_to_targeting(segment, PROFILE)
        self.assertEqual(values["keywords"], "pharmacy\nফার্মেসি")
        self.assertEqual(values["exclude_keywords"], "hospital\nRival Soft")  # profile exclusion already listed
        self.assertEqual(values["locations"][0], {"city": "Dhaka", "area": "Mirpur", "country": "Bangladesh"})
        self.assertEqual(values["locations"][1]["city"], "Chattogram")


def response(payload):
    return SimpleNamespace(status_code=200, json=lambda: payload, text="")


class Session:
    def __init__(self, payload):
        self.payload, self.calls = payload, []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params, headers))
        return response(self.payload)


class ResearchHelperTests(unittest.TestCase):
    def test_web_search_returns_plain_rows(self):
        session = Session({"web": {"results": [{"title": "<b>Pharma</b> market", "url": "https://a.example/x",
                                                "description": "Growing 12%"}]}})
        rows = BraveSearchConnector("k", enabled=True, session=session).search("pharma market bangladesh", 5)
        self.assertEqual(rows, [{"url": "https://a.example/x", "title": "Pharma market", "text": "Growing 12%"}])

    def test_page_context_returns_page_text(self):
        session = Session({"grounding": {"generic": [{"url": "https://b.example/", "title": "Pharma report",
                                                      "snippets": ["Pharmacies grew", "in Dhaka"]}]}})
        rows = BraveLLMContextConnector("k", enabled=True, session=session).context("pharma", "Dhaka", 5)
        self.assertEqual(rows[0]["text"], "Pharmacies grew in Dhaka")
        self.assertEqual(session.calls[0][1]["maximum_number_of_tokens_per_url"], 2048)


class WiringTests(unittest.TestCase):
    def test_studio_api_and_page(self):
        api = (APP / "api_studio.py").read_text(encoding="utf-8")
        for method in ("save_business", "import_customers", "research_market", "market_brief", "approve_market_brief"):
            self.assertIn(f"@frappe.whitelist()\ndef {method}(", api)
            self.assertIn(f'"{method}"', (APP / "reckon_sales_agent" / "page" / "lead_finder" / "lead_finder.js")
                          .read_text(encoding="utf-8"))
        self.assertIn('"type": "multi_source"', api)
        script = (APP / "reckon_sales_agent" / "page" / "lead_finder" / "lead_finder.js").read_text(encoding="utf-8")
        self.assertIn("[null, this.render_business, this.render_source", script)
        self.assertIn('__("Your business")', script)

    def test_routing_settings_exist(self):
        settings = json.loads((APP / "reckon_sales_agent" / "doctype" / "sales_agent_platform_settings"
                               / "sales_agent_platform_settings.json").read_text(encoding="utf-8"))
        fields = {f["fieldname"]: f for f in settings["fields"]}
        for capability in ("places", "page_context", "web_search"):
            field = fields[f"default_{capability}_provider"]
            self.assertTrue(set(field["options"].split("\n")) <= set(PROVIDERS))
        self.assertEqual(fields["provider_budgets"]["options"], "Sales Provider Budget")
        self.assertIn("market_research_max_requests", fields)
        budget = json.loads((APP / "reckon_sales_agent" / "doctype" / "sales_provider_budget"
                             / "sales_provider_budget.json").read_text(encoding="utf-8"))
        families = next(f for f in budget["fields"] if f["fieldname"] == "provider")["options"].split("\n")
        self.assertEqual(set(families), {spec[1] for spec in PROVIDERS.values()})


if __name__ == "__main__":
    unittest.main()

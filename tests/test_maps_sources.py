"""Google Maps lead sources: SerpAPI, Scrapingdog, Apify, experimental browser, AI listing fallback."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1]))

from bs4 import BeautifulSoup  # noqa: E402

from reckon_sales_agent.connectors.apify_maps import ApifyMapsConnector  # noqa: E402
from reckon_sales_agent.connectors.base import ConnectorError, ConnectorNotPermitted, DiscoveryQuery  # noqa: E402
from reckon_sales_agent.connectors.directory_crawler import DirectoryCrawler, verified_ai_listings  # noqa: E402
from reckon_sales_agent.connectors.maps_browser import (  # noqa: E402
    GoogleMapsBrowserConnector,
    clean_label,
    parse_place,
    place_id_from_url,
    unwrap_website,
)
from reckon_sales_agent.connectors.maps_common import (  # noqa: E402
    city_from_address,
    looks_blocked,
    maps_field_policy,
)
from reckon_sales_agent.connectors.scrapingdog_maps import ScrapingdogMapsConnector, coordinates_for  # noqa: E402
from reckon_sales_agent.connectors.serpapi_maps import SerpAPIMapsConnector  # noqa: E402
from reckon_sales_agent.discovery.normalize import apply_field_policy  # noqa: E402
from reckon_sales_agent.qualification.scoring import score  # noqa: E402
from reckon_sales_agent.research.evidence import rule_facts  # noqa: E402
from reckon_sales_agent.research.parser import parse_html  # noqa: E402
from reckon_sales_agent.research.url_safety import FetchResult  # noqa: E402
from reckon_sales_agent.research.website_finder import pick_website  # noqa: E402

QUERY = DiscoveryQuery("pharmacy", "Dhaka", "pharmacy in Dhaka", 3)


def response(status, payload):
    return SimpleNamespace(status_code=status, json=lambda: payload)


class FakeSession:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(("GET", url, params))
        return self.pages.pop(0)

    def post(self, url, json=None, headers=None, params=None, timeout=None):
        self.calls.append(("POST", url, json, headers, params))
        return self.pages.pop(0)


class MapsCommonTests(unittest.TestCase):
    def test_policy_retention_and_crm_sync(self):
        policy = maps_field_policy(30)
        self.assertEqual(policy["business_name"]["retention_days"], 30)
        self.assertFalse(policy["phone"]["crm_sync"])
        self.assertEqual(policy["rating"]["attribution"], "Google Maps")
        kept_forever = maps_field_policy(0)
        self.assertIsNone(kept_forever["phone"]["retention_days"])
        self.assertTrue(kept_forever["phone"]["crm_sync"])

    def test_city_and_block_detection(self):
        self.assertEqual(city_from_address("House 5, Road 2, Gulshan, Dhaka 1212, Bangladesh"), "Dhaka")
        self.assertEqual(city_from_address("", "Sylhet"), "Sylhet")
        self.assertTrue(looks_blocked("https://www.google.com/sorry/index?continue=x"))
        self.assertTrue(looks_blocked("https://consent.google.com/ml?continue=x"))
        self.assertTrue(looks_blocked("https://www.google.com/maps", "Our systems have detected unusual traffic"))
        self.assertFalse(looks_blocked("https://www.google.com/maps/place/x", "Lazz Pharma"))

    def test_rating_and_reviews_flow_through_policy(self):
        from datetime import date

        kept, _, until = apply_field_policy({"business_name": "A", "rating": 4.6, "review_count": 312},
                                            maps_field_policy(30), "t", "serpapi_google_maps", date(2026, 1, 1))
        self.assertEqual(kept["rating"], "4.6")
        self.assertEqual(kept["review_count"], "312")
        self.assertIsNotNone(until)


class SerpAPITests(unittest.TestCase):
    def test_fails_closed(self):
        for kwargs in ({"enabled": False, "terms_ack": True}, {"enabled": True, "terms_ack": False}):
            with self.assertRaises(ConnectorNotPermitted):
                SerpAPIMapsConnector("k", **kwargs).validate_configuration()
        with self.assertRaises(ConnectorNotPermitted):
            SerpAPIMapsConnector("", enabled=True, terms_ack=True).validate_configuration()

    def test_maps_results_and_paging(self):
        page = [{"title": f"Shop {i}", "place_id": f"p{i}", "address": "Mirpur, Dhaka 1216, Bangladesh",
                 "phone": "01711-000000", "website": "https://shop.example", "type": "Pharmacy",
                 "rating": 4.5, "reviews": 120} for i in range(20)]
        session = FakeSession([response(200, {"local_results": page}), response(200, {"local_results": page[:1]})])
        connector = SerpAPIMapsConnector("key", enabled=True, terms_ack=True, session=session)
        records = list(connector.discover(DiscoveryQuery("pharmacy", "Dhaka", "pharmacy in Dhaka", 21)))
        self.assertEqual(len(records), 21)
        self.assertEqual(records[0].fields["city"], "Dhaka")
        self.assertEqual(records[0].fields["review_count"], 120)
        self.assertEqual(session.calls[0][2]["engine"], "google_maps")
        self.assertEqual(session.calls[1][2]["start"], 20)

    def test_auth_error_is_permanent(self):
        connector = SerpAPIMapsConnector("k", enabled=True, terms_ack=True, session=FakeSession([response(401, {})]))
        with self.assertRaises(ConnectorError) as ctx:
            list(connector.discover(QUERY))
        self.assertTrue(ctx.exception.permanent)


class ScrapingdogTests(unittest.TestCase):
    def test_coordinates(self):
        self.assertEqual(coordinates_for("Gulshan, Dhaka"), "@23.8103,90.4125,12z")
        self.assertEqual(coordinates_for("Chattogram"), "@22.3569,91.7832,12z")
        self.assertEqual(coordinates_for("Nowhere"), "@23.6850,90.3563,7z")

    def test_search_results(self):
        results = [{"title": "Lazz Pharma", "data_id": "0x1:0x2", "address": "Kalabagan, Dhaka", "phone": "0171",
                    "rating": 4.4, "reviews": 900, "type": "Pharmacy"}]
        session = FakeSession([response(200, {"search_results": results})])
        connector = ScrapingdogMapsConnector("k", enabled=True, terms_ack=True, session=session)
        records = list(connector.discover(QUERY))
        self.assertEqual(records[0].external_id, "0x1:0x2")
        self.assertEqual(records[0].fields["review_count"], 900)
        self.assertEqual(session.calls[0][2]["query"], "pharmacy")  # city goes in ll, not the query
        self.assertEqual(session.calls[0][2]["ll"], "@23.8103,90.4125,12z")


class ApifyTests(unittest.TestCase):
    def test_actor_run_and_token_in_header(self):
        items = [{"title": "Padma Drugs", "placeId": "ChIJ1", "address": "Uttara, Dhaka", "city": "Dhaka",
                  "countryCode": "BD", "phoneUnformatted": "+8801711000000", "website": "https://padma.example",
                  "categoryName": "Pharmacy", "totalScore": 4.2, "reviewsCount": 55}, {"title": ""}]
        session = FakeSession([response(200, items)])
        connector = ApifyMapsConnector("secret-token", enabled=True, terms_ack=True, session=session)
        records = list(connector.discover(QUERY))
        self.assertEqual([r.fields["business_name"] for r in records], ["Padma Drugs"])
        method, url, body, headers, params = session.calls[0]
        self.assertIn("compass~crawler-google-places", url)
        self.assertNotIn("secret-token", url)
        self.assertEqual(headers["Authorization"], "Bearer secret-token")
        self.assertEqual(body["maxCrawledPlacesPerSearch"], 3)

    def test_billing_error(self):
        connector = ApifyMapsConnector("t", enabled=True, terms_ack=True, session=FakeSession([response(402, {})]))
        with self.assertRaises(ConnectorError):
            list(connector.discover(QUERY))


class FakePage:
    """Stands in for a Playwright page on Google Maps."""

    def __init__(self, places, blocked=False):
        self.places = places
        self.blocked = blocked
        self.url = ""
        self.visited = []

    def set_default_timeout(self, ms):
        pass

    def goto(self, url, wait_until=None):
        self.url = "https://www.google.com/sorry/index" if self.blocked else url
        self.visited.append(url)

    def inner_text(self, selector):
        return "Our systems have detected unusual traffic" if self.blocked else "Results"

    def wait_for_selector(self, selector, timeout=None):
        return True

    def eval_on_selector_all(self, selector, script):
        return list(self.places)

    def eval_on_selector(self, selector, script):
        return None

    def evaluate(self, script):
        index = list(self.places).index(self.url)
        return {"name": f"Shop {index}", "category": "Pharmacy", "address": "Address: Banani, Dhaka 1213",
                "website": "https://www.google.com/url?q=https://shop.example/&sa=U", "phone": "Phone: 01711-000111"}


class FakePlaywright:
    def __init__(self, page):
        self.page = page
        self.closed = False
        browser = SimpleNamespace(
            new_context=lambda locale=None: SimpleNamespace(new_page=lambda: page),
            close=lambda: setattr(self, "closed", True),
        )
        self.chromium = SimpleNamespace(launch=lambda headless=True: browser)

    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class BrowserConnectorTests(unittest.TestCase):
    PLACES = [f"https://www.google.com/maps/place/Shop+{i}/data=!4m6!3m5!1s0x3755:0x{i:04x}!8m2" for i in range(5)]

    def test_off_by_default_and_needs_ack(self):
        with self.assertRaises(ConnectorNotPermitted):
            GoogleMapsBrowserConnector(enabled=False, terms_ack=True, playwright_factory=FakePlaywright(None)).validate_configuration()
        with self.assertRaises(ConnectorNotPermitted):
            GoogleMapsBrowserConnector(enabled=True, terms_ack=False, playwright_factory=FakePlaywright(None)).validate_configuration()

    def test_scrolls_feed_and_reads_places_with_delay(self):
        page = FakePage(self.PLACES)
        sleeps = []
        connector = GoogleMapsBrowserConnector(enabled=True, terms_ack=True, max_results=3, delay=0.5,
                                               playwright_factory=FakePlaywright(page), sleep=sleeps.append)
        records = list(connector.discover(DiscoveryQuery("pharmacy", "Dhaka", "pharmacy in Dhaka", 10)))
        self.assertEqual(len(records), 3)  # vendor cap wins over the query
        first = records[0]
        self.assertEqual(first.fields["website"], "https://shop.example/")
        self.assertEqual(first.fields["phone"], "01711-000111")
        self.assertEqual(first.fields["city"], "Dhaka")
        self.assertEqual(first.external_id, "0x3755:0x0000")
        self.assertTrue(all(s >= 2.0 for s in sleeps))  # minimum polite delay

    def test_block_page_stops_the_run(self):
        connector = GoogleMapsBrowserConnector(enabled=True, terms_ack=True,
                                               playwright_factory=FakePlaywright(FakePage(self.PLACES, blocked=True)),
                                               sleep=lambda s: None)
        with self.assertRaises(ConnectorError) as ctx:
            list(connector.discover(QUERY))
        self.assertEqual(ctx.exception.code, "blocked")
        self.assertTrue(ctx.exception.permanent)

    def test_pure_parsers(self):
        self.assertEqual(clean_label("Address: Road 5, Dhaka "), "Road 5, Dhaka")
        self.assertEqual(unwrap_website("https://www.google.com/url?q=https://a.example/&sa=U"), "https://a.example/")
        self.assertIsNone(unwrap_website("javascript:alert(1)"))
        self.assertEqual(place_id_from_url("https://www.google.com/maps/place/X/@1,2z"), "X")
        self.assertIsNone(parse_place({"name": ""}, "u", QUERY))


class AIListingTests(unittest.TestCase):
    PAGE = "<html><body><h2>Members</h2><p>Lazz Pharma, Kalabagan. Call 01711-222333.</p></body></html>"

    def test_hallucinated_names_and_contacts_are_dropped(self):
        soup = BeautifulSoup(self.PAGE, "html.parser")
        items = [
            {"business_name": "Lazz Pharma", "phone": "01711-222333", "email": "made@up.example", "website": "",
             "address": "", "city": "Dhaka", "industry": "Pharmacy"},
            {"business_name": "Invented Traders", "phone": "", "email": "", "website": "", "address": "",
             "city": "", "industry": ""},
        ]
        kept = verified_ai_listings(items, soup)
        self.assertEqual([k["business_name"] for k in kept], ["Lazz Pharma"])
        self.assertEqual(kept[0]["phone"], "01711-222333")
        self.assertNotIn("email", kept[0])

    def test_crawler_uses_ai_only_when_page_has_no_structure(self):
        calls = []

        def fetch(url, **kwargs):
            if url.endswith("robots.txt"):
                from reckon_sales_agent.research.url_safety import FetchError

                raise FetchError("404")
            return FetchResult(url, 200, "text/html", self.PAGE, False)

        def ai(text, url):
            calls.append(text)
            return [{"business_name": "Lazz Pharma", "phone": "", "email": "", "website": "", "address": "",
                     "city": "", "industry": ""}]

        crawler = DirectoryCrawler(["https://dir.example/members"], user_agent="t", fetcher=fetch,
                                   sleep=lambda s: None, ai_extractor=ai)
        records = list(crawler.discover(DiscoveryQuery("pharmacy", "Dhaka", "q", 5)))
        self.assertEqual([r.fields["business_name"] for r in records], ["Lazz Pharma"])
        self.assertIn("Lazz Pharma", calls[0])


class EnrichmentTests(unittest.TestCase):
    def test_website_finder_requires_name_match_and_skips_directories(self):
        results = [{"link": "https://www.facebook.com/lazzpharma"}, {"link": "https://bdtradeinfo.com/lazz"},
                   {"link": "https://unrelated.example/"}, {"link": "https://www.lazzpharma.com/about"}]
        self.assertEqual(pick_website(results, "Lazz Pharma Ltd"), "https://lazzpharma.com")
        self.assertIsNone(pick_website([{"link": "https://unrelated.example/"}], "Lazz Pharma"))

    def test_social_profiles_are_collected_as_facts(self):
        html = ('<a href="https://www.facebook.com/lazzpharma/">FB</a><a href="https://facebook.com/">home</a>'
                '<a href="https://www.linkedin.com/company/lazz?trk=x">LI</a>')
        page = parse_html(html, "https://lazz.example/")
        self.assertEqual(page.social_profiles,
                         ["https://www.facebook.com/lazzpharma", "https://www.linkedin.com/company/lazz"])
        statements = [f.statement for f in rule_facts([page], {})]
        self.assertIn("Social profile: https://www.facebook.com/lazzpharma", statements)

    def test_review_volume_raises_scale(self):
        base = score({"industry": "Pharmacy", "website": "x"}, [], {"target_industries": "Pharmacy"})
        busy = score({"industry": "Pharmacy", "website": "x", "review_count": "250"}, [], {"target_industries": "Pharmacy"})
        self.assertGreater(busy["scale"], base["scale"])
        self.assertGreater(busy["fit_score"], base["fit_score"])


if __name__ == "__main__":
    unittest.main()

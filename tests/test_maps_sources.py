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
    canonical_place_url,
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
from reckon_sales_agent.connectors.scrapingbee_maps import (  # noqa: E402
    ScrapingBeeMapsConnector,
    maps_results,
    own_website,
)
from reckon_sales_agent.connectors.scrapingdog_maps import ScrapingdogMapsConnector, coordinates_for  # noqa: E402
from reckon_sales_agent.connectors.serpapi_maps import SerpAPIMapsConnector  # noqa: E402
from reckon_sales_agent.discovery.normalize import apply_field_policy, fit_length  # noqa: E402
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

    def get(self, url, params=None, timeout=None, headers=None):
        self.calls.append(("GET", url, params, headers))
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


class ScrapingBeeTests(unittest.TestCase):
    PAGE = {"map_results": [
        {"title": "Lazz Pharma", "address": "Kalabagan, Dhaka 1205", "phone": "01711-000111", "rating": "4.6",
         "reviews": 812, "category": "Pharmacy", "link": "https://www.google.com/aclk?sa=l"},
        {"title": "Padma Drugs", "address": "Uttara, Dhaka", "website": "https://padma.example/", "cid": "42"},
    ]}

    def test_maps_search_with_key_in_header(self):
        session = FakeSession([response(200, self.PAGE), response(200, {"map_results": []})])
        connector = ScrapingBeeMapsConnector(" bee-KEY \n", enabled=True, terms_ack=True, session=session)
        records = list(connector.discover(DiscoveryQuery("pharmacy", "Dhaka", "pharmacy in Dhaka", 5)))
        self.assertEqual([r.fields["business_name"] for r in records], ["Lazz Pharma", "Padma Drugs"])
        self.assertIsNone(records[0].fields["website"])  # Google ad link is not the business site
        self.assertEqual(records[1].fields["website"], "https://padma.example/")
        self.assertEqual(records[0].fields["review_count"], 812)
        method, url, params, headers = session.calls[0]
        self.assertEqual(params["search_type"], "maps")
        self.assertEqual(params["country_code"], "bd")
        self.assertNotIn("api_key", params)
        self.assertEqual(headers["Authorization"], "Bearer bee-KEY")

    def test_result_key_variants(self):
        self.assertEqual(len(maps_results({"maps_results": [{"title": "a"}]})), 1)
        self.assertEqual(len(maps_results({"local_results": [{"title": "a"}, "junk"]})), 1)
        self.assertEqual(maps_results({}), [])
        self.assertIsNone(own_website({"link": "https://maps.google.com/x"}))

    def test_fails_closed_and_explains_errors(self):
        with self.assertRaises(ConnectorNotPermitted):
            ScrapingBeeMapsConnector("k", enabled=False, terms_ack=True).validate_configuration()
        session = FakeSession([response(401, {"message": "Invalid api key"})])
        connector = ScrapingBeeMapsConnector("k", enabled=True, terms_ack=True, session=session)
        with self.assertRaises(ConnectorError) as ctx:
            list(connector.discover(QUERY))
        self.assertIn("ScrapingBee HTTP 401", str(ctx.exception))


class WebsiteFinderProviderTests(unittest.TestCase):
    def test_scrapingbee_and_scrapingdog_requests(self):
        from reckon_sales_agent.research.website_finder import find_website

        bee = FakeSession([response(200, {"organic_results": [{"url": "https://www.lazzpharma.com/"}]})])
        self.assertEqual(find_website("k", "Lazz Pharma", "Dhaka", session=bee, provider="scrapingbee"),
                         "https://lazzpharma.com")
        self.assertEqual(bee.calls[0][3]["Authorization"], "Bearer k")
        dog = FakeSession([response(200, {"organic_results": [{"link": "https://lazzpharma.com"}]})])
        self.assertEqual(find_website(" k ", "Lazz Pharma", "Dhaka", session=dog), "https://lazzpharma.com")
        self.assertEqual(dog.calls[0][2]["api_key"], "k")


class ProviderErrorTests(unittest.TestCase):
    def test_error_explains_status_and_redacts_key(self):
        body = {"success": False, "message": "Invalid API key sd-SECRET-123"}
        session = FakeSession([response(401, body)])
        connector = ScrapingdogMapsConnector("  sd-SECRET-123\n", enabled=True, terms_ack=True, session=session)
        with self.assertRaises(ConnectorError) as ctx:
            list(connector.discover(QUERY))
        message = str(ctx.exception)
        self.assertIn("HTTP 401", message)
        self.assertIn("invalid or missing", message)
        self.assertIn("Invalid API key ***", message)
        self.assertNotIn("SECRET", message)
        self.assertEqual(session.calls[0][2]["api_key"], "sd-SECRET-123")  # whitespace trimmed
        self.assertTrue(ctx.exception.permanent)

    def test_forbidden_means_plan_or_credits(self):
        session = FakeSession([response(403, {"message": "Your plan does not include this API"})])
        connector = ScrapingdogMapsConnector("k", enabled=True, terms_ack=True, session=session)
        with self.assertRaises(ConnectorError) as ctx:
            list(connector.discover(QUERY))
        self.assertEqual(ctx.exception.code, "forbidden")
        self.assertIn("does not include this API", str(ctx.exception))


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

    def __init__(self, places, blocked=False, has_search_box=True, feed=True, body="Results"):
        self.places = places
        self.blocked = blocked
        self.has_search_box = has_search_box
        self.feed = feed
        self.body = body
        self.url = ""
        self.visited = []
        self.typed = []

    def set_default_timeout(self, ms):
        pass

    def goto(self, url, wait_until=None):
        self.url = "https://www.google.com/sorry/index" if self.blocked else url
        self.visited.append(url)

    def inner_text(self, selector):
        return "Our systems have detected unusual traffic" if self.blocked else self.body

    def wait_for_selector(self, selector, timeout=None):
        if "searchboxinput" in selector and not self.has_search_box:
            raise TimeoutError("no search box")
        if 'role="feed"' in selector and not self.feed:
            raise TimeoutError("no feed")
        return True

    def fill(self, selector, text):
        self.typed.append(text)

    def press(self, selector, key):
        self.typed.append(key)
        self.url = "https://www.google.com/maps/search/results"

    def wait_for_load_state(self, state=None):
        return None

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

    def test_missing_browser_binary_gives_install_instructions(self):
        def launch(headless=True):
            raise RuntimeError("BrowserType.launch: Executable doesn't exist at /home/x/.cache/ms-playwright/...")

        playwright = FakePlaywright(FakePage(self.PLACES))
        playwright.chromium = SimpleNamespace(launch=launch)
        connector = GoogleMapsBrowserConnector(enabled=True, terms_ack=True, playwright_factory=playwright,
                                               sleep=lambda s: None)
        with self.assertRaises(ConnectorNotPermitted) as ctx:
            list(connector.discover(QUERY))
        self.assertIn("./env/bin/playwright install chromium", str(ctx.exception))

    def test_opens_maps_home_and_types_the_search(self):
        page = FakePage(self.PLACES)
        connector = GoogleMapsBrowserConnector(enabled=True, terms_ack=True, max_results=1,
                                               playwright_factory=FakePlaywright(page), sleep=lambda s: None)
        list(connector.discover(DiscoveryQuery("pharmacy", "Dhaka", "pharmacy in Dhaka", 1)))
        self.assertTrue(page.visited[0].startswith("https://maps.google.com/"))
        self.assertEqual(page.typed, ["pharmacy in Dhaka", "Enter"])
        self.assertFalse(any("/maps/search/" in url for url in page.visited))

    def test_falls_back_to_search_url_without_search_box(self):
        page = FakePage(self.PLACES, has_search_box=False)
        connector = GoogleMapsBrowserConnector(enabled=True, terms_ack=True, max_results=1,
                                               playwright_factory=FakePlaywright(page), sleep=lambda s: None)
        records = list(connector.discover(DiscoveryQuery("pharmacy", "Dhaka", "pharmacy in Dhaka", 1)))
        self.assertEqual(page.typed, [])
        self.assertIn("https://www.google.com/maps/search/pharmacy%20in%20Dhaka?hl=en", page.visited)
        self.assertEqual(len(records), 1)

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

    def test_missing_results_list_is_a_retryable_error_not_zero_leads(self):
        connector = GoogleMapsBrowserConnector(enabled=True, terms_ack=True, sleep=lambda s: None,
                                               playwright_factory=FakePlaywright(FakePage(self.PLACES, feed=False)))
        with self.assertRaises(ConnectorError) as ctx:
            list(connector.discover(QUERY))
        self.assertEqual(ctx.exception.code, "no_results_list")
        self.assertFalse(ctx.exception.permanent)

    def test_genuine_no_results_is_empty(self):
        page = FakePage(self.PLACES, feed=False, body="Google Maps can't find pharmacy in Nowhere")
        connector = GoogleMapsBrowserConnector(enabled=True, terms_ack=True, sleep=lambda s: None,
                                               playwright_factory=FakePlaywright(page))
        self.assertEqual(list(connector.discover(QUERY)), [])

    def test_pure_parsers(self):
        self.assertEqual(clean_label("Address: Road 5, Dhaka "), "Road 5, Dhaka")
        self.assertEqual(unwrap_website("https://www.google.com/url?q=https://a.example/&sa=U"), "https://a.example/")
        self.assertIsNone(unwrap_website("javascript:alert(1)"))
        self.assertEqual(place_id_from_url("https://www.google.com/maps/place/X/@1,2z"), "X")
        self.assertIsNone(parse_place({"name": ""}, "u", QUERY))


class LongValueTests(unittest.TestCase):
    PLACE = ("https://www.google.com/maps/place/Ferdousi+Pharmacy+%28Main+Branch%29/data=!4m7!3m6!1s0x3755c43c31ac4581"
             ":0xdc3c1635b9ee7c70!8m2!3d23.87!4d90.39!16s%2Fg%2F11c608k7fk?authuser=0&hl=en&g_ep=EgoyMDI2&rclk=1")

    def test_place_url_loses_tracking_query_but_keeps_the_place(self):
        url = canonical_place_url(self.PLACE)
        self.assertNotIn("?", url)
        self.assertEqual(place_id_from_url(url), "0x3755c43c31ac4581:0xdc3c1635b9ee7c70")

    def test_fit_length_clips_text_and_drops_urls(self):
        self.assertEqual(fit_length("short", 140), "short")
        self.assertEqual(fit_length("x" * 200, 140), "x" * 140)
        self.assertIsNone(fit_length(self.PLACE, 100, url=True))


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

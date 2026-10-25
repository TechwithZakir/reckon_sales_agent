"""Web search lead sources: result filtering, Brave and SERP API providers, the browser bot (no network)."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1]))

from reckon_sales_agent.connectors.base import ConnectorError, ConnectorNotPermitted, DiscoveryQuery  # noqa: E402
from reckon_sales_agent.connectors.brave_search import (  # noqa: E402
    BraveLLMContextConnector,
    BravePlaceSearchConnector,
    BraveSearchConnector,
)
from reckon_sales_agent.connectors.search_api import (  # noqa: E402
    ScrapingBeeSearchConnector,
    ScrapingdogSearchConnector,
    SerpAPISearchConnector,
)
from reckon_sales_agent.connectors.search_browser import GoogleSearchBrowserConnector  # noqa: E402
from reckon_sales_agent.connectors.search_common import (  # noqa: E402
    business_name,
    email_from,
    is_business_site,
    is_listing_page,
    phone_from,
    records_from_results,
    search_field_policy,
)

QUERY = DiscoveryQuery("pharmacy", "Mirpur, Dhaka", "pharmacy in Mirpur, Dhaka", 3)


def response(status, payload):
    return SimpleNamespace(status_code=status, json=lambda: payload, text="")


class FakeSession:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def get(self, url, params=None, timeout=None, headers=None):
        self.calls.append((url, params, headers))
        return self.pages.pop(0)


def organic(*items):
    return [{"title": title, "link": link, "snippet": snippet} for title, link, snippet in items]


PAGE_ONE = organic(
    ("Lazz Pharma | Online Pharmacy in Bangladesh", "https://www.lazzpharma.com/shop?x=1", "Call 01711-000111"),
    ("Lazz Pharma - Facebook", "https://www.facebook.com/lazzpharma", ""),
    ("Top 10 pharmacies in Dhaka", "https://www.prothomalo.com/top-10", ""),
    ("Buy medicine online", "https://www.daraz.com.bd/medicine", ""),
)
PAGE_TWO = organic(
    ("Lazz Pharma Kalabagan", "https://lazzpharma.com/kalabagan", ""),  # same domain: counted once
    ("Home - Tamanna Pharmacy", "https://tamannapharmacy.com.bd/", "Mirpur 10, Dhaka. 02-9001234"),
    ("Welcome to Care Pharmacy Ltd", "https://care-pharmacy.com/about", ""),
)


class ResultFilterTests(unittest.TestCase):
    def test_only_business_websites_count(self):
        for url in ("https://www.facebook.com/x", "https://www.daraz.com.bd/y", "https://www.google.com.bd/maps",
                    "https://bn.wikipedia.org/wiki/Z", "https://www.prothomalo.com/a", "https://dghs.gov.bd/",
                    "https://www.bdyellowpages.com/p"):
            self.assertFalse(is_business_site(url), url)
        for url in ("https://www.lazzpharma.com/", "https://www.fedex.com/", "https://abc.com.bd/",
                    "https://example-pharma.net/contact"):
            self.assertTrue(is_business_site(url), url)

    def test_business_name_from_title(self):
        self.assertEqual(business_name("Lazz Pharma | Online Pharmacy in Bangladesh", "https://lazzpharma.com"),
                         "Lazz Pharma")
        self.assertEqual(business_name("Home - Tamanna Pharmacy", "https://t.com.bd"), "Tamanna Pharmacy")
        self.assertEqual(business_name("Welcome to Care Pharmacy Ltd", "https://c.com"), "Care Pharmacy Ltd")
        self.assertEqual(business_name("", "https://www.green-life-pharma.com/"), "Green Life Pharma")

    def test_lists_and_directories_are_not_leads(self):
        # Titles Brave Web Search returned for "pharmacy in Dhanmondi, Dhaka" on the live site.
        for title, url in (
            ("List of pharmacies in Bangladesh", "https://example-blog.com/pharmacies"),
            ("Top 10 Pharmacy / Drugstore in Dhaka", "https://some-site.com/top-10"),
            ("The 6 Best Drugstores in Dhanmondi", "https://guide.example.com/dhaka"),
            ("Dhanmondi Hospital Discounts List", "https://discounts.example.com/"),
            ("Dhanmondi Pharmacy 2 in the city Dhaka", "https://citylocal.example.com/x"),
            ("Pharmacies near me", "https://finder.example.com/"),
            ("Square Pharmacy", "https://shops.example.com/listing/square-pharmacy"),
            ("Pharmacy", "https://site.example.com/category/pharmacy"),
        ):
            self.assertTrue(is_listing_page(title, url), title)
        self.assertFalse(is_business_site("https://medex.com.bd/companies"))
        self.assertFalse(is_business_site("https://www.mawbiz.com.bd/x"))
        for title, url in (("Lazz Pharma | Online Pharmacy", "https://lazzpharma.com/"),
                           ("Best Pharma Ltd", "https://bestpharma.com.bd/about"),
                           ("Aster Pharmacy", "https://asterpharmacy.com/company/about")):
            self.assertFalse(is_listing_page(title, url), title)

    def test_only_a_businesss_own_site_is_a_lead(self):
        # Brave Web Search for "pharmacy in Gulshan, Dhaka" on the live site, after the listicle filter.
        live = [
            {"title": "HugeDomains.com", "url": "http://www.dhakapharma.com/"},
            {"title": "BRAC Healthcare", "url": "https://brachealthcare.com/"},
            {"title": "Best Pharmacies in Dhaka at DhakaSnob.com", "url": "https://www.dhakasnob.com/"},
            {"title": "Gulshan Homeo Pharmacy", "url": "https://gulshanhomeopharmacy.com/"},
            {"title": "GULSHAN PHARMA, Gulshan, Dhaka, Bangladesh", "url": "https://medicare24bd.com/gulshan-pharma"},
            {"title": "Gulshan Pharma, pharmacy at Dhaka 1212", "url": "https://vymaps.com/BD/Gulshan-Pharma"},
            {"title": "Islamia Pharmacy Ltd.", "url": "https://islamiapharmacyltd.com/"},
            {"title": "ACI Limited | Home", "url": "https://www.aci-bd.com/"},
        ]
        records = records_from_results(live, QUERY, "brave_web_search", set(), 20)
        self.assertEqual([r.fields["business_name"] for r in records],
                         ["BRAC Healthcare", "Gulshan Homeo Pharmacy", "Islamia Pharmacy Ltd.", "ACI Limited"])

    def test_generic_page_title_falls_back_to_the_domain(self):
        self.assertEqual(business_name("Pharmacy", "https://www.tcm-model-pharmacy.com/", "pharmacy"),
                         "Tcm Model Pharmacy")
        self.assertEqual(business_name("Pharmacies | Home", "https://greenlife.com.bd/", "pharmacy"), "Greenlife")
        records = records_from_results([{"title": "Top 10 Pharmacy in Dhaka", "link": "https://x.com.bd/top"},
                                        {"title": "Pharmacy", "link": "https://wellbeing-pharmacy.com/"}],
                                       QUERY, "brave_web_search", set(), 10)
        self.assertEqual([r.fields["business_name"] for r in records], ["Wellbeing Pharmacy"])

    def test_phone_from_snippet(self):
        self.assertEqual(phone_from("Call 01711-000111 today"), "01711-000111")
        self.assertEqual(phone_from("Tel: +880 1811 222333"), "+880 1811 222333")
        self.assertIsNone(phone_from("Open 9am to 10pm"))

    def test_search_fields_are_attributed_and_kept_for_retention(self):
        policy = search_field_policy(30)
        self.assertEqual(policy["website"]["attribution"], "Google Search")
        self.assertEqual(policy["website"]["retention_days"], 30)
        self.assertFalse(policy["website"]["crm_sync"])
        self.assertTrue(search_field_policy(0)["website"]["crm_sync"])


class SearchAPITests(unittest.TestCase):
    def test_off_until_vendor_enables_and_accepts(self):
        for kwargs in ({"enabled": False, "terms_ack": True}, {"enabled": True, "terms_ack": False}):
            with self.assertRaises(ConnectorNotPermitted):
                ScrapingdogSearchConnector("k", **kwargs).validate_configuration()
        with self.assertRaises(ConnectorNotPermitted):
            ScrapingdogSearchConnector(None, enabled=True, terms_ack=True).validate_configuration()

    def test_scrapingdog_pages_filters_and_dedups(self):
        session = FakeSession([response(200, {"organic_results": PAGE_ONE}),
                               response(200, {"organic_results": PAGE_TWO})])
        connector = ScrapingdogSearchConnector("k", enabled=True, terms_ack=True, session=session)
        records = list(connector.discover(QUERY))
        self.assertEqual([r.fields["business_name"] for r in records],
                         ["Lazz Pharma", "Tamanna Pharmacy", "Care Pharmacy Ltd"])
        first = records[0]
        self.assertEqual(first.fields["website"], "https://www.lazzpharma.com/")
        self.assertEqual(first.fields["phone"], "01711-000111")
        self.assertEqual(first.fields["city"], "Dhaka")
        self.assertEqual(first.fields["industry"], "pharmacy")
        self.assertEqual(first.external_id, "lazzpharma.com")
        self.assertEqual(records[1].fields["phone"], "02-9001234")
        self.assertEqual([c[1]["page"] for c in session.calls], [0, 1])
        self.assertEqual(session.calls[0][1]["query"], "pharmacy in Mirpur, Dhaka")
        self.assertEqual(session.calls[0][1]["country"], "bd")

    def test_stops_when_results_run_out(self):
        session = FakeSession([response(200, {"organic_results": PAGE_ONE}), response(200, {"organic_results": []})])
        connector = ScrapingdogSearchConnector("k", enabled=True, terms_ack=True, session=session)
        self.assertEqual(len(list(connector.discover(QUERY))), 1)
        self.assertEqual(len(session.calls), 2)

    def test_scrapingbee_uses_bearer_header_and_its_own_keys(self):
        bee = [{"title": "Lazz Pharma", "url": "https://lazzpharma.com/", "description": "01711-000111"}]
        session = FakeSession([response(200, {"organic_results": bee}), response(200, {"organic_results": []})])
        connector = ScrapingBeeSearchConnector("secret", enabled=True, terms_ack=True, session=session)
        records = list(connector.discover(QUERY))
        self.assertEqual(records[0].fields["phone"], "01711-000111")
        url, params, headers = session.calls[0]
        self.assertEqual(headers["Authorization"], "Bearer secret")
        self.assertNotIn("secret", str(params))
        self.assertEqual(params["page"], 1)
        self.assertEqual(params["country_code"], "bd")

    def test_serpapi_offsets_and_empty_result_message(self):
        session = FakeSession([response(200, {"organic_results": PAGE_ONE}),
                               response(200, {"error": "Google hasn't returned any results for this query."})])
        connector = SerpAPISearchConnector("k", enabled=True, terms_ack=True, session=session)
        self.assertEqual(len(list(connector.discover(QUERY))), 1)
        self.assertEqual([c[1]["start"] for c in session.calls], [0, 10])
        self.assertEqual(session.calls[0][1]["engine"], "google")

    def test_serpapi_error_and_bad_key(self):
        session = FakeSession([response(200, {"error": "Your account has run out of searches."})])
        with self.assertRaises(ConnectorError):
            list(SerpAPISearchConnector("k", enabled=True, terms_ack=True, session=session).discover(QUERY))
        session = FakeSession([response(401, {"message": "Invalid key k"})])
        with self.assertRaises(ConnectorError) as ctx:
            list(ScrapingdogSearchConnector("k", enabled=True, terms_ack=True, session=session).discover(QUERY))
        self.assertTrue(ctx.exception.permanent)
        self.assertEqual(ctx.exception.code, "auth")


class FakeSearchPage:
    """Stands in for a Playwright page on Google Search: two result pages."""

    def __init__(self, pages, blocked=False, has_box=True, results=True, body="Results", consent=None):
        self.pages = pages
        self.consent = consent
        self.consent_done = False
        self.pending = ""
        self.clicks = []
        self.blocked = blocked
        self.has_box = has_box
        self.results = results
        self.body = body
        self.index = 0
        self.url = ""
        self.visited = []
        self.typed = []

    def set_default_timeout(self, ms):
        pass

    def goto(self, url, wait_until=None):
        self.visited.append(url)
        if self._consent_wall(url):
            return
        self.url = "https://www.google.com/sorry/index" if self.blocked else url
        if "start=" in url:
            self.index += 1

    def inner_text(self, selector):
        if "consent.google." in self.url:
            return "Before you continue to Google Search"
        return "Our systems have detected unusual traffic" if self.blocked else self.body

    def _consent_wall(self, url):
        """Show Google's consent page instead of ``url`` until "Reject all" is clicked."""
        if self.consent and not self.consent_done:
            self.pending = url
            self.url = "https://consent.google.com/ml?continue=" + url
            return True
        return False

    def click(self, selector, timeout=None):
        if self.consent == "reject" and "Reject all" in selector and "consent.google." in self.url:
            self.clicks.append(selector)
            self.consent_done = True
            self.url = self.pending
            return None
        raise TimeoutError(selector)

    def wait_for_selector(self, selector, timeout=None):
        if "name=\"q\"" in selector and not self.has_box:
            raise TimeoutError("no box")
        if selector == "#search" and not self.results:
            raise TimeoutError("no results")
        return True

    def fill(self, selector, text):
        self.typed.append(text)

    def press(self, selector, key):
        self.typed.append(key)
        self.url = "https://www.google.com/search?q=x"

    def wait_for_load_state(self, state=None):
        return None

    def evaluate(self, script):
        return self.pages[self.index]

    def get_attribute(self, selector, name, timeout=None):
        return "/search?q=x&start=10" if self.index + 1 < len(self.pages) else None


class FakePlaywright:
    def __init__(self, page):
        browser = SimpleNamespace(new_context=lambda locale=None: SimpleNamespace(new_page=lambda: page),
                                  close=lambda: None)
        self.chromium = SimpleNamespace(launch=lambda headless=True: browser)

    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class SearchBrowserTests(unittest.TestCase):
    def bot(self, page, sleeps=None, **kwargs):
        return GoogleSearchBrowserConnector(enabled=True, terms_ack=True, playwright_factory=FakePlaywright(page),
                                            sleep=(sleeps.append if sleeps is not None else lambda s: None), **kwargs)

    def test_off_until_vendor_enables_and_accepts(self):
        with self.assertRaises(ConnectorNotPermitted):
            GoogleSearchBrowserConnector(enabled=False, terms_ack=True,
                                         playwright_factory=FakePlaywright(None)).validate_configuration()
        with self.assertRaises(ConnectorNotPermitted):
            GoogleSearchBrowserConnector(enabled=True, terms_ack=False,
                                         playwright_factory=FakePlaywright(None)).validate_configuration()

    def test_types_the_search_and_follows_next_with_a_delay(self):
        page = FakeSearchPage([PAGE_ONE, PAGE_TWO])
        sleeps = []
        records = list(self.bot(page, sleeps, delay=1).discover(QUERY))
        self.assertEqual([r.fields["business_name"] for r in records],
                         ["Lazz Pharma", "Tamanna Pharmacy", "Care Pharmacy Ltd"])
        self.assertTrue(page.visited[0].startswith("https://www.google.com/?hl=en&gl=bd"))
        self.assertEqual(page.typed, ["pharmacy in Mirpur, Dhaka", "Enter"])
        self.assertEqual(sleeps, [3.0])  # minimum polite delay between result pages

    def test_falls_back_to_the_search_url(self):
        page = FakeSearchPage([PAGE_ONE], has_box=False)
        records = list(self.bot(page).discover(QUERY))
        self.assertEqual(len(records), 1)
        self.assertIn("https://www.google.com/search?q=pharmacy%20in%20Mirpur%2C%20Dhaka&hl=en&gl=bd", page.visited)

    def test_block_page_stops_the_run(self):
        with self.assertRaises(ConnectorError) as ctx:
            list(self.bot(FakeSearchPage([PAGE_ONE], blocked=True)).discover(QUERY))
        self.assertEqual(ctx.exception.code, "captcha")
        self.assertTrue(ctx.exception.permanent)
        self.assertIn("CAPTCHA", str(ctx.exception))

    def test_consent_page_is_declined_and_the_search_runs(self):
        page = FakeSearchPage([PAGE_ONE, PAGE_TWO], consent="reject")
        records = list(self.bot(page).discover(QUERY))
        self.assertEqual(len(records), 3)
        self.assertEqual(len(page.clicks), 1)

    def test_consent_page_that_cannot_be_declined_says_so(self):
        with self.assertRaises(ConnectorError) as ctx:
            list(self.bot(FakeSearchPage([PAGE_ONE], consent="stuck")).discover(QUERY))
        self.assertEqual(ctx.exception.code, "consent")

    def test_missing_results_retry_but_no_match_is_empty(self):
        with self.assertRaises(ConnectorError) as ctx:
            list(self.bot(FakeSearchPage([PAGE_ONE], results=False)).discover(QUERY))
        self.assertFalse(ctx.exception.permanent)
        page = FakeSearchPage([PAGE_ONE], results=False, body="Your search did not match any documents.")
        self.assertEqual(list(self.bot(page).discover(QUERY)), [])

    def test_hard_cap(self):
        self.assertEqual(GoogleSearchBrowserConnector(enabled=True, terms_ack=True, max_results=500).max_results, 50)


class BraveSearchTests(unittest.TestCase):
    @staticmethod
    def brave_page(*items):
        return {"web": {"results": [{"title": t, "url": u, "description": d} for t, u, d in items]}}

    def test_needs_vendor_switch_and_key_but_no_google_tick(self):
        with self.assertRaises(ConnectorNotPermitted):
            BraveSearchConnector("k", enabled=False).validate_configuration()
        with self.assertRaises(ConnectorNotPermitted):
            BraveSearchConnector(None, enabled=True).validate_configuration()
        BraveSearchConnector("k", enabled=True).validate_configuration()

    def test_searches_with_header_key_and_filters_results(self):
        page = self.brave_page(
            ("<strong>Lazz Pharma</strong> | Online Pharmacy", "https://www.lazzpharma.com/", "Call <strong>01711-000111</strong>"),
            ("Lazz Pharma - Facebook", "https://www.facebook.com/lazzpharma", ""),
            ("Tamanna Pharmacy", "https://tamannapharmacy.com.bd/", "Mirpur 10"),
        )
        session = FakeSession([response(200, page)])
        records = list(BraveSearchConnector("secret", enabled=True, session=session).discover(QUERY))
        self.assertEqual([r.fields["business_name"] for r in records], ["Lazz Pharma", "Tamanna Pharmacy"])
        self.assertEqual(records[0].fields["phone"], "01711-000111")  # HTML tags stripped first
        url, params, headers = session.calls[0]
        self.assertEqual(url, "https://api.search.brave.com/res/v1/web/search")
        self.assertEqual(headers["X-Subscription-Token"], "secret")
        self.assertNotIn("secret", str(params))
        self.assertEqual((params["q"], params["count"], params["offset"]), ("pharmacy in Mirpur, Dhaka", 20, 0))
        self.assertNotIn("country", params)  # all countries unless the vendor sets one
        self.assertEqual(len(session.calls), 1)  # a short page means no more results: no second paid request

    def test_pages_by_offset_while_brave_says_there_are_more(self):
        full = self.brave_page(*[(f"Shop {i}", f"https://shop{i}.com/", "") for i in range(20)])
        full["query"] = {"more_results_available": True}
        session = FakeSession([response(200, full)])
        query = DiscoveryQuery("pharmacy", "Dhaka", "pharmacy in Dhaka", 25)
        more = self.brave_page(*[(f"Store {i}", f"https://store{i}.com/", "") for i in range(20)])
        session.pages.append(response(200, more))
        records = list(BraveSearchConnector("k", enabled=True, country="us", session=session).discover(query))
        self.assertEqual(len(records), 25)
        self.assertEqual([c[1]["offset"] for c in session.calls], [0, 1])
        self.assertEqual(session.calls[0][1]["country"], "US")

    def test_only_brave_supported_country_codes_are_sent(self):
        def country_sent(code):
            session = FakeSession([response(200, self.brave_page())])
            list(BraveSearchConnector("k", enabled=True, country=code, session=session).discover(QUERY))
            return session.calls[0][1].get("country")

        self.assertEqual(country_sent("BD"), "ALL")  # 422 otherwise
        self.assertEqual(country_sent("in"), "IN")
        self.assertIsNone(country_sent(""))
        places = FakeSession([response(200, {"results": []})])
        list(BravePlaceSearchConnector("k", enabled=True, country="IN", session=places).discover(QUERY))
        self.assertEqual(places.calls[0][1]["country"], "IN")
        self.assertEqual(places.calls[0][1]["location"], "mirpur dhaka india")

    def test_bad_key_and_rate_limit(self):
        session = FakeSession([response(401, {"error": {"detail": "Invalid token"}})])
        with self.assertRaises(ConnectorError) as ctx:
            list(BraveSearchConnector("k", enabled=True, session=session).discover(QUERY))
        self.assertTrue(ctx.exception.permanent)
        session = FakeSession([response(429, {})])
        with self.assertRaises(ConnectorError) as ctx:
            list(BraveSearchConnector("k", enabled=True, session=session).discover(QUERY))
        self.assertFalse(ctx.exception.permanent)  # retried by the runner

    def test_rejected_parameters_stop_at_once_with_the_reason(self):
        session = FakeSession([response(422, {"error": {"detail": "Unable to validate request parameter(s)"}})])
        with self.assertRaises(ConnectorError) as ctx:
            list(BraveSearchConnector("secret", enabled=True, session=session).discover(QUERY))
        self.assertTrue(ctx.exception.permanent)
        self.assertEqual(ctx.exception.code, "invalid_request")
        self.assertIn("Unable to validate", str(ctx.exception))
        self.assertNotIn("secret", str(ctx.exception))

    def test_attributed_to_brave(self):
        policy = BraveSearchConnector("k", enabled=True).default_field_policy()
        self.assertEqual(policy["website"]["attribution"], "Brave Search")
        self.assertEqual(BravePlaceSearchConnector("k", enabled=True).default_field_policy()["phone"]["attribution"],
                         "Brave Places")


PLACES = {"type": "locations", "results": [
    {"type": "location_result", "id": "ephemeral-1", "title": "Lazz Pharma", "url": "https://www.lazzpharma.com/",
     "provider_url": "https://search.brave.com/local/x", "coordinates": [23.80652, 90.37231],
     "postal_address": {"displayAddress": "Kalabagan, Dhaka 1205", "addressLocality": "Dhaka", "country": "BD"},
     "contact": {"telephone": "+880 1711-000111", "email": "Info@LazzPharma.com"},
     "rating": {"ratingValue": 4.4, "reviewCount": 900}, "categories": ["Pharmacy", "Health"]},
    {"type": "location_result", "id": "ephemeral-2", "title": "Corner Chemist", "url": "https://www.facebook.com/cc",
     "coordinates": [23.81, 90.36], "postal_address": {"displayAddress": "Mirpur 10"}, "contact": {}},
    {"type": "location_result", "title": ""},
]}


class BravePlaceSearchTests(unittest.TestCase):
    def test_places_become_rich_leads_in_one_request(self):
        session = FakeSession([response(200, PLACES)])
        query = DiscoveryQuery("pharmacy", "Mirpur, Dhaka", "pharmacy in Mirpur, Dhaka", 20)
        records = list(BravePlaceSearchConnector("secret", enabled=True, session=session).discover(query))
        self.assertEqual(len(records), 2)
        lazz = records[0].fields
        self.assertEqual((lazz["business_name"], lazz["phone"], lazz["email"]),
                         ("Lazz Pharma", "+880 1711-000111", "info@lazzpharma.com"))
        self.assertEqual((lazz["address"], lazz["city"], lazz["industry"]), ("Kalabagan, Dhaka 1205", "Dhaka", "Pharmacy"))
        self.assertEqual((lazz["rating"], lazz["review_count"]), (4.4, 900))
        self.assertEqual(lazz["website"], "https://www.lazzpharma.com/")
        self.assertEqual(records[0].external_id, "lazz pharma@23.8065,90.3723")  # not Brave's expiring id
        self.assertIsNone(records[1].fields["website"])  # a Facebook page is not the business's site
        url, params, headers = session.calls[0]
        self.assertEqual(url, "https://api.search.brave.com/res/v1/local/place_search")
        self.assertEqual(headers["X-Subscription-Token"], "secret")
        self.assertEqual((params["q"], params["location"], params["count"]), ("pharmacy", "mirpur dhaka bangladesh", 20))
        self.assertNotIn("country", params)  # Brave rejects BD; the location string carries the country
        self.assertEqual(len(session.calls), 1)

    def test_location_string_and_caps(self):
        connector = BravePlaceSearchConnector("k", enabled=True, country="in")
        self.assertEqual(connector.place_location("Andheri, Mumbai"), "andheri mumbai india")
        self.assertEqual(connector.place_location("Gulshan, Dhaka, Bangladesh"), "gulshan dhaka bangladesh")
        session = FakeSession([response(200, {"results": []})])
        list(BravePlaceSearchConnector("k", enabled=True, session=session).discover(
            DiscoveryQuery("pharmacy", "", "pharmacy", 500)))
        self.assertEqual(session.calls[0][1]["count"], 100)
        self.assertNotIn("location", session.calls[0][1])


class BraveLLMContextTests(unittest.TestCase):
    GROUNDING = {"grounding": {
        "generic": [
            {"url": "https://www.lazzpharma.com/contact", "title": "Contact | Lazz Pharma",
             "snippets": ["Call us: 01711-000111", "Email: sales@lazzpharma.com"]},
            {"url": "https://en.wikipedia.org/wiki/Pharmacy", "title": "Pharmacy - Wikipedia", "snippets": ["..."]},
        ],
        "poi": {"name": "Tamanna Pharmacy", "url": "https://tamannapharmacy.com.bd/", "title": "Tamanna Pharmacy",
                "snippets": ["{\"telephone\": \"02-9001234\"}"]},
        "map": [{"name": "Care Pharmacy", "url": "https://care-pharmacy.com/", "title": "Care", "snippets": []}],
    }, "sources": {}}

    def test_page_text_gives_contacts_and_local_entries_become_leads(self):
        session = FakeSession([response(200, self.GROUNDING)])
        query = DiscoveryQuery("pharmacy", "Mirpur, Dhaka", "pharmacy in Mirpur, Dhaka", 10)
        records = list(BraveLLMContextConnector("k", enabled=True, country="bd", session=session).discover(query))
        names = [r.fields["business_name"] for r in records]
        self.assertEqual(names, ["Tamanna Pharmacy", "Care Pharmacy", "Lazz Pharma"])  # local entries first
        lazz = records[2].fields
        self.assertEqual((lazz["phone"], lazz["email"], lazz["website"]),
                         ("01711-000111", "sales@lazzpharma.com", "https://www.lazzpharma.com/"))
        self.assertEqual(records[0].fields["phone"], "02-9001234")
        url, params, headers = session.calls[0]
        self.assertEqual(url, "https://api.search.brave.com/res/v1/llm/context")
        self.assertEqual((params["q"], params["enable_local"]), ("pharmacy in Mirpur, Dhaka", "true"))
        self.assertNotIn("country", params)  # BD is not a Brave country code
        self.assertEqual(headers["X-Loc-City"], "Dhaka")
        self.assertNotIn("X-Loc-Country", headers)

    def test_email_finder_ignores_image_names(self):
        self.assertEqual(email_from("logo@2x.png and hello@shop.com.bd"), "hello@shop.com.bd")
        self.assertIsNone(email_from("no contact here"))


class WiringTests(unittest.TestCase):
    def test_settings_read_by_the_registry_and_studio_exist(self):
        import json
        import re

        app = Path(__file__).parents[1] / "reckon_sales_agent"
        settings = json.loads((app / "reckon_sales_agent" / "doctype" / "sales_agent_platform_settings"
                               / "sales_agent_platform_settings.json").read_text(encoding="utf-8"))
        fields = {f["fieldname"] for f in settings["fields"]}
        registry = (app / "connectors" / "registry.py").read_text(encoding="utf-8")
        used = set(re.findall(r"\bs\.((?:search|brave)_\w+)", registry))
        used |= set(re.findall(r'"((?:search|brave)_\w+)"', registry))
        used |= set(re.findall(r'"((?:search|brave)_\w+)"', (app / "api_studio.py").read_text(encoding="utf-8")))
        connector_types = ("_web_search", "_google_search", "_place_search", "_llm_context")
        used = {name for name in used if not name.endswith(connector_types)}
        self.assertIn("brave_api_key", used)
        self.assertTrue(used)
        self.assertEqual(used - fields, set())
        self.assertEqual(settings["field_order"], [f["fieldname"] for f in settings["fields"]])


if __name__ == "__main__":
    unittest.main()

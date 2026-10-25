"""Google Search lead sources: result filtering, SERP API providers and the browser bot (no network)."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1]))

from reckon_sales_agent.connectors.base import ConnectorError, ConnectorNotPermitted, DiscoveryQuery  # noqa: E402
from reckon_sales_agent.connectors.search_api import (  # noqa: E402
    ScrapingBeeSearchConnector,
    ScrapingdogSearchConnector,
    SerpAPISearchConnector,
)
from reckon_sales_agent.connectors.search_browser import GoogleSearchBrowserConnector  # noqa: E402
from reckon_sales_agent.connectors.search_common import (  # noqa: E402
    business_name,
    is_business_site,
    phone_from,
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


class WiringTests(unittest.TestCase):
    def test_settings_read_by_the_registry_and_studio_exist(self):
        import json
        import re

        app = Path(__file__).parents[1] / "reckon_sales_agent"
        settings = json.loads((app / "reckon_sales_agent" / "doctype" / "sales_agent_platform_settings"
                               / "sales_agent_platform_settings.json").read_text(encoding="utf-8"))
        fields = {f["fieldname"] for f in settings["fields"]}
        used = set(re.findall(r"\bs\.(search_\w+)", (app / "connectors" / "registry.py").read_text(encoding="utf-8")))
        used |= set(re.findall(r'"(search_\w+)"', (app / "api_studio.py").read_text(encoding="utf-8")))
        self.assertTrue(used)
        self.assertEqual(used - fields, set())
        self.assertEqual(settings["field_order"], [f["fieldname"] for f in settings["fields"]])


if __name__ == "__main__":
    unittest.main()

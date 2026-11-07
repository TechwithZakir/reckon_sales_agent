"""Spam score, plain-language verdicts, step conversion, CSV export, tracking domain and the campaign goal cards."""

import csv
import io
import re
import unittest
from pathlib import Path

from reckon_sales_agent.campaigns import spamscore, tracking, verdict

ROOT = Path(__file__).resolve().parents[1] / "reckon_sales_agent"


def read(*parts):
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


CLEAN_BODY = ("Hello Rahim, thank you for talking with us last week about your distribution routes. As promised, here is a short "
              "summary of how our team can help with stock visibility across your warehouses. If it is useful, let us know a time "
              "that suits you for a fifteen minute call.")


class SpamScoreTests(unittest.TestCase):
    def test_a_plain_honest_email_scores_low(self):
        result = spamscore.score("A summary of our call", CLEAN_BODY, ["https://reckon.tech/book"])
        self.assertEqual(result["level"], "Low")
        self.assertLess(result["score"], 3)

    def test_a_shouting_salesy_email_scores_high_with_reasons_and_fixes(self):
        result = spamscore.score("FREE WINNER!!! ACT NOW", "CLICK HERE to claim your FREE prize!!! 100% guaranteed!!! Buy now!!!",
                                 ["http://bit.ly/x"])
        self.assertEqual(result["level"], "High")
        self.assertGreaterEqual(result["score"], 6)
        self.assertTrue(all(r["text"] and r["fix"] for r in result["reasons"]))
        self.assertEqual(result["reasons"], sorted(result["reasons"], key=lambda r: -r["points"]))
        self.assertLessEqual(result["score"], 10)

    def test_each_signal_is_counted_for_the_right_reason(self):
        texts = lambda subject, body="", urls=(): " ".join(r["text"] for r in spamscore.score(subject, body or CLEAN_BODY, urls)["reasons"])  # noqa: E731
        self.assertIn("shouts", texts("BUY OUR PRODUCTS TODAY"))
        self.assertIn("reply or a forward", texts("Re: your invoice"))
        self.assertIn("exclamation", texts("Hello!!"))
        self.assertIn("link shortener", texts("Hello", urls=["https://bit.ly/abc"]))
        self.assertIn("not https", texts("Hello", urls=["http://example.org/a"]))
        self.assertIn("no text", spamscore.score("Hello", "", [])["reasons"][0]["text"].lower().replace("there is ", ""))
        self.assertIn("9 links", texts("Hello", urls=[f"https://a.co/{i}" for i in range(9)]))

    def test_words_inside_other_words_do_not_count(self):
        self.assertEqual(spamscore.score("Freedom of choice", CLEAN_BODY, [])["reasons"], [])  # "free" is not "freedom"
        self.assertNotEqual(spamscore.score("Free trial", CLEAN_BODY, [])["reasons"], [])

    def test_no_subject_is_noted(self):
        self.assertTrue(any("no subject" in r["text"].lower() for r in spamscore.score("", CLEAN_BODY, [])["reasons"]))

    def test_levels_and_the_check_line(self):
        self.assertEqual((spamscore.level(0), spamscore.level(3), spamscore.level(6)), ("Low", "Medium", "High"))
        low = spamscore.check_line(spamscore.score("A summary of our call", CLEAN_BODY, []))
        self.assertTrue(low["ok"])
        high = spamscore.check_line(spamscore.score("FREE!!! WINNER!!!", "click here", ["http://bit.ly/x"]))
        self.assertFalse(high["ok"])
        self.assertIn("/10", high["label"])

    def test_it_is_advice_beside_the_other_checks_and_never_a_block(self):
        content = read("campaigns", "template_content.py")
        email = content.split("def compile_content(")[1].split('if channel == "Email":')[1].split('if channel == "SMS":')[0]
        self.assertIn("checks.append(spamscore.check_line(spam))", email)
        self.assertIn('"spam": spam', email)
        self.assertNotIn("issues.append(", email.split("spamscore")[1].split("body =")[0])


class VerdictTests(unittest.TestCase):
    def rates(self, sent, opened, clicked, replied=0, bounced=0, unsub=0):
        pct = lambda n: round(100 * n / sent, 1) if sent else 0.0  # noqa: E731
        return ({"sent": sent, "opened": opened, "clicked": clicked, "replied": replied, "positive": 0},
                {"open_rate": pct(opened), "click_rate": pct(clicked), "reply_rate": pct(replied), "bounce_rate": pct(bounced),
                 "unsubscribe_rate": pct(unsub)})

    def test_a_small_send_is_not_judged(self):
        result = verdict.verdict(*self.rates(10, 9, 5))
        self.assertEqual(result["tone"], "early")
        self.assertIn("Too early", result["headline"])

    def test_strong_normal_and_weak_results_read_differently(self):
        self.assertEqual(verdict.verdict(*self.rates(200, 80, 14))["tone"], "good")
        self.assertEqual(verdict.verdict(*self.rates(200, 52, 6))["headline"], "A normal result")
        weak = verdict.verdict(*self.rates(200, 20, 1))
        self.assertEqual(weak["tone"], "low")
        self.assertTrue(any("subject" in a.lower() for a in weak["advice"]))
        self.assertTrue(any("button" in a.lower() for a in weak["advice"]))

    def test_bounces_and_opt_outs_raise_flags(self):
        counts, rates = self.rates(200, 80, 14, bounced=14)
        result = verdict.verdict(counts, rates)
        self.assertEqual(result["tone"], "low")
        self.assertTrue(any("Clean list" in a for a in result["advice"]))
        counts, rates = self.rates(200, 80, 14, unsub=4)
        self.assertTrue(any("narrower" in a for a in verdict.verdict(counts, rates)["advice"]))

    def test_the_headline_never_mentions_opens_for_other_channels(self):
        counts, rates = self.rates(100, 0, 6)
        lines = " ".join(verdict.verdict(counts, rates, channel="SMS")["lines"])
        self.assertNotIn("opened", lines)

    def test_step_conversion(self):
        steps = verdict.steps({"sent": 200, "delivered": 0, "opened": 80, "clicked": 20, "replied": 4, "positive": 2})
        self.assertEqual([s["key"] for s in steps], ["sent", "opened", "clicked", "replied", "positive"])  # no delivery receipts: skipped
        opened = steps[1]
        self.assertEqual((opened["of_sent"], opened["of_previous"], opened["lost"]), (40.0, 40.0, 120))
        self.assertEqual(steps[2]["of_previous"], 25.0)
        self.assertEqual(verdict.steps({"sent": 0})[0]["of_sent"], 0.0)

    def test_export_rows_and_csv(self):
        messages = [{"name": "M1", "prospect": "P1", "channel": "Email", "step_no": 1, "variant": "A", "status": "Sent", "sent_on": "2026-11-07 10:00:00"},
                    {"name": "M2", "prospect": "P2", "channel": "SMS", "step_no": 1, "variant": None, "status": "Failed", "sent_on": None}]
        events = [{"message": "M1", "event_type": "opened"}, {"message": "M1", "event_type": "positive_reply"}, {"message": "M2", "event_type": "bounced"}]
        people = {"P1": {"name": "Rahim", "email": "r@a.co", "phone": ""}, "P2": {"name": "=HYPERLINK(\"x\")", "email": "", "phone": "+8801700000000"}}
        rows = verdict.export_rows(messages, events, people)
        self.assertEqual(rows[0][8:], ["yes", "", "yes", "", ""])  # opened, replied
        self.assertEqual(rows[1][11], "yes")  # bounced
        self.assertTrue(rows[1][0].startswith("'="))  # a spreadsheet formula is made harmless
        parsed = list(csv.reader(io.StringIO(verdict.to_csv(rows))))
        self.assertEqual(parsed[0], list(verdict.EXPORT_COLUMNS))
        self.assertEqual(len(parsed), 3)


class TrackingDomainTests(unittest.TestCase):
    def test_only_a_plain_host_name_is_accepted(self):
        self.assertEqual(tracking.valid_domain("Track.Example.com"), "track.example.com")
        for bad in ("https://track.example.com", "track.example.com/path", "track", "a b.example.com", "-x.example.com",
                    "track.example.com:8080", "", None, "x" * 300 + ".com", "track.e"):
            self.assertEqual(tracking.valid_domain(bad), "", bad)

    def test_links_use_the_domain_when_set_and_only_https(self):
        source = read("campaigns", "track_links.py")
        public = source.split("def _public_url(")[1].split("def instrument(")[0]
        self.assertIn('f"https://{domain}{path}"', public)
        self.assertEqual(source.count("_public_url(settings,"), 3)  # the definition, the click link and the open pixel
        self.assertNotIn("get_url(f\"{CLICK_PATH}", source)

    def test_the_unsubscribe_link_stays_on_this_site(self):
        self.assertIn("get_url(f\"/api/method/reckon_sales_agent.api.unsubscribe", read("campaigns", "engine.py"))

    def test_the_setting_is_validated_and_checked(self):
        channels = read("api_channels.py")
        self.assertIn('"tracking_domain": "text"', channels)
        self.assertIn("valid_domain(value)", channels)
        check = channels.split("def check_tracking_domain(")[1].split("# The system provider")[0]
        self.assertIn("_require_manager()", check)
        self.assertIn("validate_url(url)", check)
        self.assertIn("allow_redirects=False", check)
        script = read("reckon_sales_agent", "page", "sales_channels", "sales_channels.js")
        self.assertIn("this.tracking_section()", script)
        self.assertIn("check_tracking_domain", script)


class StudioWiringTests(unittest.TestCase):
    SCRIPT = read("reckon_sales_agent", "page", "campaign_studio", "campaign_studio.js")

    def test_the_campaign_page_shows_the_verdict_and_exports(self):
        self.assertIn("${verdict_html(d.verdict, d.step_conversion)}", self.SCRIPT)
        self.assertIn('["export", __("Export CSV")]', self.SCRIPT)
        self.assertIn('API + "export_campaign"', self.SCRIPT)
        api = read("api_campaign_studio.py")
        self.assertIn('"verdict": verdict.verdict(', api)
        self.assertIn('"step_conversion": verdict.steps(', api)
        self.assertIn("def export_campaign(name: str)", api)
        export = api.split("def export_campaign(")[1].split("@frappe.whitelist")[0]
        self.assertIn('get_tenant_doc("Sales Campaign", name, "read")', export)  # only the session's Company
        self.assertIn('"company": doc.company', export)

    def test_the_export_filename_is_safe(self):
        export = read("api_campaign_studio.py").split("def export_campaign(")[1].split("@frappe.whitelist")[0]
        self.assertIn('re.sub(r"[^A-Za-z0-9_-]+"', export)

    def test_the_wizard_offers_goal_cards_that_keep_chosen_templates(self):
        self.assertIn("What do you want to do?", self.SCRIPT)
        ids = re.findall(r'\{ id: "(\w+)", title', self.SCRIPT)
        self.assertGreaterEqual(len(ids), 5)
        self.assertIn("keep templates already chosen", self.SCRIPT)
        goals = set(re.findall(r'goal: "([^"]+)", delays', self.SCRIPT))
        self.assertTrue(goals <= {"Book a meeting", "Re-engage", "Upsell", "Event invite"}, goals)  # the goals the doctype accepts


if __name__ == "__main__":
    unittest.main()

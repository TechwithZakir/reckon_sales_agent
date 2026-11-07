"""Campaign Studio core rules: audiences, tracking, timeline, funnel, copilot and autopilot (pure, no bench)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from reckon_sales_agent.campaigns import audience, autopilot, copilot, timeline, tracking  # noqa: E402
from reckon_sales_agent.campaigns.metrics import funnel, summarize  # noqa: E402


class AudienceTests(unittest.TestCase):
    def test_a_recipient_needs_an_email_or_a_phone(self):
        self.assertIsNone(audience.recipient("Lead", "CRM Lead", "L1", "Nobody"))
        self.assertIsNone(audience.recipient("Lead", "CRM Lead", "L1", "Bad", email="not-an-email", phone="12"))

    def test_addresses_are_normalised(self):
        item = audience.recipient("Lead", "CRM Lead", "L1", "  Rahim   Uddin ", email=" Rahim@Example.COM ", phone="01711-123456")
        self.assertEqual((item["email"], item["phone"], item["name"]), ("rahim@example.com", "+8801711123456", "Rahim Uddin"))

    def test_duplicates_merge_by_email_or_phone_and_fill_gaps(self):
        a = audience.recipient("Lead", "CRM Lead", "L1", "Rahim", email="r@x.com")
        b = audience.recipient("Contact", "Contact", "C1", "", email="r@x.com", phone="01711123456")
        c = audience.recipient("Prospect", "Sales Prospect", "P1", "Other", phone="+8801711123456")
        merged = audience.dedupe([a, b, c])
        self.assertEqual(len(merged), 1)
        self.assertEqual((merged[0]["kind"], merged[0]["phone"], merged[0]["name"]), ("Lead", "+8801711123456", "Rahim"))

    def test_different_people_stay_separate(self):
        rows = audience.dedupe([audience.recipient("Lead", "CRM Lead", "L1", "A", email="a@x.com"),
                                audience.recipient("Lead", "CRM Lead", "L2", "B", email="b@x.com")])
        self.assertEqual(len(rows), 2)

    def test_reachability_follows_the_channel(self):
        email_only = audience.recipient("Lead", "CRM Lead", "L1", "A", email="a@x.com")
        phone_only = audience.recipient("Lead", "CRM Lead", "L2", "B", phone="01711123456")
        self.assertTrue(audience.reachable_by(email_only, ["Email"]))
        self.assertFalse(audience.reachable_by(email_only, ["SMS"]))
        self.assertTrue(audience.reachable_by(phone_only, ["WhatsApp"]))
        self.assertFalse(audience.reachable_by(phone_only, ["Email"]))
        self.assertTrue(audience.reachable_by(phone_only, []))

    def test_summary_counts(self):
        rows = [audience.recipient("Lead", "CRM Lead", "L1", "A", email="a@x.com", phone="01711123456"),
                audience.recipient("Contact", "Contact", "C1", "B", email="b@x.com")]
        result = audience.summary(rows, ["SMS"])
        self.assertEqual((result["total"], result["with_email"], result["with_phone"], result["reachable"]), (2, 2, 1, 1))
        self.assertEqual(result["by_kind"], {"Lead": 1, "Contact": 1})

    def test_lists_are_split_and_deduplicated(self):
        self.assertEqual(audience.split_list("New, Contacted\nNew ,, Qualified"), ["New", "Contacted", "Qualified"])
        self.assertEqual(audience.split_list(None), [])

    def test_six_kinds_of_audience(self):
        self.assertEqual(audience.AUDIENCE_TYPES, ("Prospects", "CRM Leads", "CRM Contacts", "Customers", "Specific people",
                                                   "Segment"))


class TrackingTests(unittest.TestCase):
    @staticmethod
    def make(url):
        return "https://s.io/l/" + str(abs(hash(url)) % 1000)

    def test_html_links_are_rewritten_and_the_label_is_kept(self):
        body = '<p><a href="https://shop.io/p?a=1&amp;b=2" class="x">Buy</a></p>'
        out = tracking.rewrite_html_links(body, lambda url: "https://s.io/l/abc")
        self.assertIn('href="https://s.io/l/abc"', out)
        self.assertIn(">Buy</a>", out)

    def test_the_original_url_is_unescaped_before_it_is_stored(self):
        seen = []
        tracking.rewrite_html_links('<a href="https://shop.io/p?a=1&amp;b=2">x</a>', lambda url: seen.append(url) or "https://s.io/l/a")
        self.assertEqual(seen, ["https://shop.io/p?a=1&b=2"])

    def test_unsubscribe_and_our_own_links_are_never_rewritten(self):
        body = ('<a href="https://site.io/api/method/reckon_sales_agent.api.unsubscribe?token=t">u</a>'
                '<a href="https://site.io/l/abc">t</a><a href="mailto:a@b.co">m</a>')
        self.assertEqual(tracking.rewrite_html_links(body, lambda url: "X"), body)

    def test_text_links_keep_trailing_punctuation(self):
        out = tracking.rewrite_text_links("See https://shop.io/p. Thanks!", lambda url: "https://s.io/l/abc")
        self.assertEqual(out, "See https://s.io/l/abc. Thanks!")

    def test_text_links_skip_the_opt_out_link(self):
        text = "Offer https://shop.io/x\nOpt out: https://site.io/api/method/reckon_sales_agent.api.unsubscribe?token=t"
        out = tracking.rewrite_text_links(text, lambda url: "https://s.io/l/abc")
        self.assertIn("https://s.io/l/abc", out)
        self.assertIn("api.unsubscribe?token=t", out)

    def test_pixel_is_hidden_and_escaped(self):
        tag = tracking.pixel_tag('https://s.io/o?c=a&b="')
        self.assertIn('width="1"', tag)
        self.assertIn("display:none", tag)
        self.assertNotIn('"b="', tag)

    def test_codes_are_short_and_different(self):
        codes = {tracking.new_code() for _ in range(50)}
        self.assertEqual(len(codes), 50)
        self.assertTrue(all(len(c) == 8 for c in codes))

    def test_scanners_and_empty_agents_are_bots(self):
        for agent in (None, "", "Mozilla/5.0 (compatible; Googlebot/2.1)", "python-requests/2.31", "WhatsApp/2.23",
                      "Mozilla/5.0 Proofpoint URL Defense"):
            self.assertTrue(tracking.is_bot(agent), agent)
        self.assertFalse(tracking.is_bot("Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/120 Safari/537.36"))

    def test_the_pixel_is_a_valid_gif(self):
        self.assertTrue(tracking.GIF.startswith(b"GIF89a"))
        self.assertEqual(tracking.GIF[-1:], b";")


def ev(kind, message="M1", channel="Email", at="2026-11-04 10:00:00", **extra):
    return {"event_type": kind, "message": message, "channel": channel, "event_time": at, **extra}


class TimelineTests(unittest.TestCase):
    def test_opens_and_clicks_are_capped(self):
        events = [ev("opened") for _ in range(10)] + [ev("clicked") for _ in range(10)]
        self.assertEqual(timeline.engagement_score(events), 2 * 3 + 5 * 3)

    def test_replies_outweigh_opens_and_opt_outs_subtract(self):
        self.assertGreater(timeline.engagement_score([ev("positive_reply")]), timeline.engagement_score([ev("opened")] * 3))
        self.assertEqual(timeline.engagement_score([ev("unsubscribed")]), 0)
        self.assertEqual(timeline.engagement_score([ev("clicked"), ev("unsubscribed")]), 0)

    def test_temperature(self):
        self.assertEqual(timeline.temperature(30), "Hot")
        self.assertEqual(timeline.temperature(10), "Warm")
        self.assertEqual(timeline.temperature(2), "Cold")
        self.assertEqual(timeline.temperature(50, [ev("complained")]), "Opted out")

    def test_timeline_is_oldest_first_and_hides_internal_events(self):
        messages = [{"name": "M1", "campaign": "C1", "channel": "Email", "step_no": 1, "subject": "Hello"}]
        events = [ev("opened", at="2026-11-04 12:00:00"), ev("drafted", at="2026-11-04 08:00:00"),
                  ev("sent", at="2026-11-04 09:00:00")]
        rows = timeline.build_timeline(messages, events)
        self.assertEqual([r["kind"] for r in rows], ["sent", "opened"])
        self.assertEqual(rows[0]["subject"], "Hello")
        self.assertEqual(len(timeline.build_timeline(messages, events, show_internal=True)), 3)

    def test_one_answer_counts_once_even_when_it_is_several_events(self):
        # Found live: an interested reply is two events (replied, then positive_reply) and showed as 0 replies, and a
        # campaign showed a 200% reply rate. A person's count is the messages that were answered.
        events = [ev("replied", "M1"), ev("positive_reply", "M1"), ev("meeting_requested", "M2")]
        self.assertEqual(timeline.summarize_person(events)["counts"]["replied"], 2)
        self.assertEqual(timeline.summarize_person([ev("positive_reply", "M1")])["counts"]["replied"], 1)

    def test_person_summary(self):
        result = timeline.summarize_person([ev("sent"), ev("opened", at="2026-11-04 11:00:00"), ev("clicked", at="2026-11-04 12:00:00")])
        self.assertEqual(result["counts"]["opened"], 1)
        self.assertEqual(result["last_activity"], "2026-11-04 12:00:00")
        self.assertEqual(result["temperature"], "Warm")


class FunnelTests(unittest.TestCase):
    def events(self):
        out = []
        for n in range(10):
            out.append(ev("sent", f"M{n}", at="2026-11-04 09:00:00"))
        for n in range(4):
            out.append(ev("opened", f"M{n}", at="2026-11-04 10:00:00"))
        out.append(ev("opened", "M0", at="2026-11-04 10:05:00"))  # a second open of the same message
        out += [ev("clicked", "M0"), ev("clicked", "M0"), ev("clicked", "M1")]
        out += [ev("replied", "M0"), ev("positive_reply", "M1"), ev("bounced", "M9"), ev("unsubscribed", "M8")]
        return out

    def test_unique_counts_and_rates(self):
        result = funnel(self.events())
        counts, rates = result["counts"], result["rates"]
        self.assertEqual((counts["sent"], counts["opened"], counts["clicked"], counts["replied"]), (10, 4, 2, 2))
        self.assertEqual(result["totals"], {"opens": 5, "clicks": 3})
        self.assertEqual(rates["open_rate"], 40.0)
        self.assertEqual(rates["click_to_open_rate"], 50.0)
        self.assertEqual(rates["bounce_rate"], 10.0)

    def test_positive_replies_count_as_replies_too(self):
        counts = funnel(self.events())["counts"]
        self.assertEqual((counts["replied"], counts["positive"]), (2, 1))

    def test_daily_series_and_open_hours(self):
        result = funnel(self.events())
        self.assertEqual(result["by_day"]["2026-11-04"]["sent"], 10)
        self.assertEqual(result["open_hours"], {"10": 5})

    def test_by_channel(self):
        events = [ev("sent", "A", channel="Email"), ev("sent", "B", channel="SMS"), ev("clicked", "B", channel="SMS")]
        result = funnel(events)["by_channel"]
        self.assertEqual(result["SMS"]["clicked"], 1)
        self.assertEqual(result["Email"]["clicked"], 0)

    def test_summarize_keeps_its_old_keys_and_adds_engagement(self):
        result = summarize([{"event_type": "sent", "channel": "Email", "step_no": 1}], [], [])
        self.assertIn("by_channel", result)
        self.assertIn("engagement", result)

    def test_an_empty_funnel_does_not_divide_by_zero(self):
        self.assertEqual(funnel([])["rates"]["open_rate"], 0.0)


class CopilotTests(unittest.TestCase):
    @staticmethod
    def metrics(sent=100, opened=10, clicked=0, replied=0, bounced=0, unsubscribed=0, open_hours=None):
        return {"engagement": funnel([ev("sent", f"S{n}") for n in range(sent)]
                                     + [ev("opened", f"S{n}") for n in range(opened)]
                                     + [ev("clicked", f"S{n}") for n in range(clicked)]
                                     + [ev("replied", f"S{n}") for n in range(replied)]
                                     + [ev("bounced", f"S{n}") for n in range(bounced)]
                                     + [ev("unsubscribed", f"S{n}") for n in range(unsubscribed)])
                | ({"open_hours": open_hours} if open_hours else {})}

    def ids(self, metrics, ctx=None):
        return [s["id"] for s in copilot.suggest(metrics, ctx)]

    def test_small_samples_are_not_judged(self):
        self.assertNotIn("low_opens", self.ids(self.metrics(sent=10, opened=0)))
        self.assertNotIn("bounces", self.ids(self.metrics(sent=10, bounced=5)))

    def test_high_bounces_come_first(self):
        suggestions = copilot.suggest(self.metrics(sent=100, bounced=8, opened=40))
        self.assertEqual(suggestions[0]["id"], "bounces")
        self.assertEqual(suggestions[0]["severity"], "high")
        self.assertEqual(suggestions[0]["action"], "pause")

    def test_low_opens_and_no_clicks(self):
        ids = self.ids(self.metrics(sent=100, opened=10))
        self.assertIn("low_opens", ids)
        ids = self.ids(self.metrics(sent=100, opened=30, clicked=0))
        self.assertIn("opens_without_clicks", ids)

    def test_hot_recipients_are_the_top_suggestion(self):
        self.assertEqual(copilot.suggest(self.metrics(), {"hot_recipients": 3})[0]["id"], "hot_recipients")

    def test_unsubscribes_and_replies(self):
        self.assertIn("unsubscribes", self.ids(self.metrics(sent=100, unsubscribed=3, opened=50)))
        self.assertIn("good_replies", self.ids(self.metrics(sent=100, replied=8, opened=50)))

    def test_test_mode_is_called_out(self):
        self.assertIn("test_mode", self.ids(self.metrics(), {"outbound_enabled": False}))

    def test_best_hours_need_enough_opens(self):
        self.assertEqual(copilot.best_hours({"09": 3, "14": 2}), [])
        self.assertEqual(copilot.best_hours({"09": 8, "14": 6, "20": 1}), [9, 14])

    def test_nothing_sent_suggests_a_pilot(self):
        self.assertIn("nothing_sent", self.ids({"engagement": funnel([])}))


class AutopilotTests(unittest.TestCase):
    OK = dict(campaign_active=True, campaign_approved=True, content_passed=True, channel="Email")

    def test_only_auto_send_skips_the_click(self):
        self.assertTrue(autopilot.may_auto_approve("Auto-send", **self.OK)[0])
        for level in ("Off", "Assist", "nonsense"):
            self.assertFalse(autopilot.may_auto_approve(level, **self.OK)[0], level)

    def test_each_guard_stops_it(self):
        for override in ({"campaign_active": False}, {"campaign_approved": False}, {"content_passed": False},
                         {"channel": "Call Task"}, {"channel": "Messenger"}):
            self.assertFalse(autopilot.may_auto_approve("Auto-send", **{**self.OK, **override})[0], override)

    def test_off_does_not_claim_the_copilot_is_silent(self):
        # The Studio shows suggestions at every level; Off only stops the agent acting on them.
        self.assertNotIn("silent", autopilot.DESCRIPTIONS["Off"])
        self.assertIn("no tasks", autopilot.DESCRIPTIONS["Off"])

    def test_levels_default_to_off(self):
        self.assertEqual(autopilot.normalize_level(None), "Off")
        self.assertEqual(autopilot.normalize_level("Assist"), "Assist")

    def test_followup_tasks_from_assist_upwards(self):
        self.assertFalse(autopilot.creates_followup_tasks("Off"))
        self.assertTrue(autopilot.creates_followup_tasks("Assist"))
        self.assertTrue(autopilot.creates_followup_tasks("Auto-send"))

    def test_send_window(self):
        self.assertEqual(autopilot.parse_window("09:00-20:00"), (540, 1200))
        self.assertTrue(autopilot.in_window("09:00-20:00", 600))
        self.assertFalse(autopilot.in_window("09:00-20:00", 1300))
        self.assertTrue(autopilot.in_window("", 1300))  # no window: any time
        self.assertTrue(autopilot.in_window("garbage", 1300))
        self.assertTrue(autopilot.in_window("20:00-06:00", 1380))  # across midnight
        self.assertTrue(autopilot.in_window("20:00-06:00", 120))
        self.assertFalse(autopilot.in_window("20:00-06:00", 720))


if __name__ == "__main__":
    unittest.main()

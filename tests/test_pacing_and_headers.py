"""Sending pace, hourly limit, Brevo free-plan cap and one-click unsubscribe headers."""

import json
import unittest
from pathlib import Path

from reckon_sales_agent.campaigns import pacing
from reckon_sales_agent.providers import brevo

ROOT = Path(__file__).resolve().parents[1] / "reckon_sales_agent"


def read(*parts):
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


class Settings(dict):
    pass


class PaceTests(unittest.TestCase):
    def test_unset_controls_take_their_defaults_and_zero_switches_them_off(self):
        self.assertEqual(pacing.config(Settings()), {"gap": 45, "jitter": 40, "hourly": 30})
        off = pacing.config(Settings(send_gap_seconds=0, hourly_message_limit=0))
        self.assertEqual((off["gap"], off["hourly"]), (0, 0))

    def test_nonsense_settings_fall_back_and_are_capped(self):
        pace = pacing.config(Settings(send_gap_seconds="abc", send_gap_jitter=500, hourly_message_limit=-3))
        self.assertEqual(pace["gap"], 45)
        self.assertEqual(pace["jitter"], 90)
        self.assertEqual(pace["hourly"], 0)
        self.assertEqual(pacing.config(Settings(send_gap_seconds=99999))["gap"], pacing.MAX_GAP_SECONDS)

    def test_the_gap_varies_per_message_within_the_jitter_and_is_repeatable(self):
        gaps = {pacing.message_gap(60, 40, f"MSG-{i}") for i in range(200)}
        self.assertTrue(all(36 <= g <= 84 for g in gaps))
        self.assertGreater(len(gaps), 50)  # not one fixed beat
        self.assertEqual(pacing.message_gap(60, 40, "MSG-1"), pacing.message_gap(60, 40, "MSG-1"))

    def test_no_gap_means_no_wait(self):
        self.assertEqual(pacing.message_gap(0, 40, "x"), 0.0)
        self.assertEqual(pacing.wait_seconds(5, 0), 0.0)

    def test_wait_is_what_is_left_of_the_gap(self):
        self.assertEqual(pacing.wait_seconds(None, 45), 0.0)  # nothing sent before
        self.assertEqual(pacing.wait_seconds(10, 45), 35.0)
        self.assertEqual(pacing.wait_seconds(45, 45), 0.0)
        self.assertEqual(pacing.wait_seconds(500, 45), 0.0)
        self.assertEqual(pacing.wait_seconds(-5, 45), 45.0)  # a clock a little behind never skips the gap

    def test_the_hourly_limit(self):
        self.assertFalse(pacing.hourly_reached(29, 30))
        self.assertTrue(pacing.hourly_reached(30, 30))
        self.assertFalse(pacing.hourly_reached(1000, 0))  # 0 = no hourly cap

    def test_only_bulk_channels_are_paced(self):
        self.assertEqual(set(pacing.PACED_CHANNELS), {"Email", "SMS", "WhatsApp"})


class BrevoCapTests(unittest.TestCase):
    def test_the_free_plan_is_the_default_and_zero_removes_the_cap(self):
        self.assertEqual(pacing.brevo_daily_limit(Settings()), 300)
        self.assertEqual(pacing.brevo_daily_limit(Settings(brevo_daily_cap=0)), 0)
        self.assertEqual(pacing.brevo_daily_limit(Settings(brevo_daily_cap=1000)), 1000)

    def test_the_cap_lowers_todays_email_limit_only_for_brevo(self):
        body = read("agents", "deliverability.py").split("def today_email_limit(")[1]
        self.assertIn('settings.get("email_provider") == "Brevo"', body)
        self.assertIn("min(cap, provider_cap) if provider_cap else cap", body)


class UnsubscribeHeaderTests(unittest.TestCase):
    URL = "https://crm.example.com/api/method/reckon_sales_agent.api.unsubscribe?token=abc123"

    def test_one_click_pair(self):
        headers = pacing.unsubscribe_headers(self.URL)
        self.assertEqual(headers["List-Unsubscribe"], f"<{self.URL}>")
        self.assertEqual(headers["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click")

    def test_no_header_for_a_link_the_standard_would_not_accept(self):
        self.assertEqual(pacing.unsubscribe_headers("http://crm.example.com/x"), {})
        self.assertEqual(pacing.unsubscribe_headers(""), {})
        self.assertEqual(pacing.unsubscribe_headers("https://a.example/x>\r\nBcc: x@y.z"), {})  # header injection

    def test_the_headers_go_on_top_of_a_stored_message(self):
        raw = "Content-Type: text/html\nSubject: Hi\n\nBody"
        out = pacing.add_headers_to_mime(raw, pacing.unsubscribe_headers(self.URL))
        head, _, body = out.partition("\n\n")
        self.assertIn(f"List-Unsubscribe: <{self.URL}>", head)
        self.assertIn("List-Unsubscribe-Post: List-Unsubscribe=One-Click", head)
        self.assertTrue(head.endswith("Subject: Hi"))
        self.assertEqual(body, "Body")

    def test_crlf_messages_keep_crlf_and_an_existing_header_is_left_alone(self):
        crlf = pacing.add_headers_to_mime("Subject: Hi\r\n\r\nBody", pacing.unsubscribe_headers(self.URL))
        self.assertIn("List-Unsubscribe: <", crlf)
        self.assertNotIn("\n\n", crlf.replace("\r\n", ""))
        already = "List-Unsubscribe: <mailto:x@y.z>\nSubject: Hi\n\nBody"
        self.assertEqual(pacing.add_headers_to_mime(already, pacing.unsubscribe_headers(self.URL)), already)
        self.assertEqual(pacing.add_headers_to_mime("x", {}), "x")

    def test_a_header_named_in_the_body_is_not_mistaken_for_one(self):
        raw = "Subject: Hi\n\nList-Unsubscribe: in the text"
        self.assertIn("List-Unsubscribe-Post", pacing.add_headers_to_mime(raw, pacing.unsubscribe_headers(self.URL)))

    def test_brevo_carries_the_headers_and_omits_them_when_there_are_none(self):
        headers = pacing.unsubscribe_headers(self.URL)
        self.assertEqual(brevo.email_payload("a@b.co", "s@b.co", "S", "Hi", "<p>x</p>", "MSG-1", headers)["headers"], headers)
        self.assertNotIn("headers", brevo.email_payload("a@b.co", "s@b.co", "S", "Hi", "<p>x</p>", "MSG-1"))


class WiringTests(unittest.TestCase):
    def test_sendgrid_carries_the_headers(self):
        self.assertIn('payload["headers"]', read("providers", "twilio.py"))
        self.assertIn("_unsubscribe_headers(message)", read("providers", "twilio.py"))

    def test_replies_are_not_bulk_mail(self):
        for name in ("brevo.py", "twilio.py"):
            self.assertIn('None if message.get("is_reply")', read("providers", name))
        self.assertIn('message.get("is_reply")', read("campaigns", "mailheaders.py"))

    def test_the_system_email_path_is_covered_by_a_queue_hook(self):
        hooks = read("hooks.py")
        self.assertIn('doc_events["Email Queue"]', hooks)
        self.assertIn("campaigns.mailheaders.add_to_queued_email", hooks)

    def test_the_engine_enforces_the_pace_after_the_dry_run_and_never_on_replies(self):
        engine = read("campaigns", "engine.py")
        send = engine.split("def send_message(")[1].split("\ndef _instrument(")[0]
        self.assertLess(send.index("if not settings.outbound_enabled:"), send.index("pace_wait(message, settings)"))
        self.assertIn("if not is_reply and pace_wait(message, settings) > 0:", send)
        self.assertLess(send.index("pace_wait(message, settings)"), send.index("reserve(message.company"))

    def test_the_pace_counts_real_sends_of_the_same_channel_and_company(self):
        body = read("campaigns", "engine.py").split("def pace_wait(")[1].split("\ndef run_paced_send(")[0]
        self.assertIn('"company": message.company, "channel": channel, "status": "Sent"', body)
        self.assertIn("PACED_CHANNELS", body)

    def test_a_paced_job_runs_per_company_and_every_ten_minutes(self):
        engine = read("campaigns", "engine.py")
        job = engine.split("def run_paced_send(")[1].split("\ndef send_due_messages(")[0]
        self.assertIn("for company in", job)
        self.assertIn("deduplicate=True", job)
        self.assertIn('f"reckon_sales_agent_paced_send_{company}"', job)
        self.assertIn('"*/10 * * * *": ["reckon_sales_agent.campaigns.engine.run_paced_send"]', read("hooks.py"))

    def test_the_paced_job_rereads_a_message_after_waiting(self):
        body = read("campaigns", "engine.py").split("def send_due_messages(")[1].split("\ndef send_message(")[0]
        self.assertLess(body.index("time.sleep(wait)"), body.index('message.status != "Approved"'))

    def test_settings_fields_exist_in_order_and_are_editable_numbers(self):
        doc = json.loads(read("reckon_sales_agent", "doctype", "sales_agent_settings", "sales_agent_settings.json"))
        names = {f["fieldname"] for f in doc["fields"]}
        order = doc["field_order"]
        for field in ("send_gap_seconds", "send_gap_jitter", "hourly_message_limit", "brevo_daily_cap"):
            self.assertIn(field, names)
            self.assertIn(field, order)
            self.assertIn(f'"{field}": "number"', read("api_channels.py"))
        self.assertEqual(doc["field_order"].count("send_gap_seconds"), 1)

    def test_the_panels_show_the_pace_and_the_brevo_signup(self):
        js = read("reckon_sales_agent", "page", "sales_channels", "sales_channels.js")
        self.assertEqual(js.count("this.pace_section()"), 2)  # System Email and Brevo
        self.assertIn("https://www.brevo.com/pricing/", js)
        self.assertIn("300 emails a day", js)
        self.assertIn('f: "brevo_daily_cap"', js)


class LiveFindingTests(unittest.TestCase):
    def test_a_message_without_a_subject_line_still_gets_a_label(self):
        """Live test: drafting an SMS failed with 'Value missing for Sales Outreach Message: Subject'."""
        body = read("campaigns", "engine.py").split("def draft_message(")[1].split("\ndef _personal_line(")[0]
        self.assertIn('[:140] or f"{channel} message"', body)


class LiveHeaderFindingTests(unittest.TestCase):
    """Live test: the queued email had no List-Unsubscribe, because a background worker builds http links."""

    FOOT = '<a href="https://crm.example.com/api/method/reckon_sales_agent.api.unsubscribe?token=abc123" rel="noopener">Unsubscribe</a>'

    def test_the_footer_link_is_the_source(self):
        self.assertEqual(pacing.unsubscribe_url_from_body("<p>Hi</p>" + self.FOOT),
                         "https://crm.example.com/api/method/reckon_sales_agent.api.unsubscribe?token=abc123")
        self.assertEqual(pacing.unsubscribe_url_from_body("<p>No link</p>"), "")
        self.assertEqual(pacing.unsubscribe_url_from_body('<a href="https://evil.example/x?token=abc">x</a>'), "")

    def test_a_public_http_link_becomes_https_and_a_local_one_stays(self):
        self.assertEqual(pacing.ensure_https("http://crm.example.com/x?token=a"), "https://crm.example.com/x?token=a")
        self.assertEqual(pacing.ensure_https("http://localhost:8000/x"), "http://localhost:8000/x")
        self.assertEqual(pacing.ensure_https("https://crm.example.com/x"), "https://crm.example.com/x")

    def test_the_header_uses_the_body_link_first(self):
        source = read("campaigns", "mailheaders.py")
        body = source.split("def unsubscribe_url_for(")[1].split("\ndef headers_for(")[0]
        self.assertLess(body.index("unsubscribe_url_from_body"), body.index("unsubscribe_token"))
        self.assertIn("ensure_https", body)
        self.assertIn('"is_reply", "body"', source)


class SmsGatewayFailureTests(unittest.TestCase):
    def test_a_refused_platform_gateway_marks_the_message_failed_instead_of_retrying_forever(self):
        body = read("providers", "sms.py").split("def send(")[1].split("def receive(")[0]
        gateway = body.split('if provider == "Platform gateway":')[1].split('if provider == "Twilio')[0]
        self.assertIn("except Exception as exc:", gateway)
        self.assertIn("raise ChannelUnavailable(", gateway)


class SmsSecretTests(unittest.TestCase):
    def test_a_refusal_never_carries_the_providers_key(self):
        """Live test: BulkSMSBD answered 'user id not found in this <key> key' and it was stored on the message."""
        body = read("providers", "sms.py").split("def send(")[1].split("def receive(")[0]
        self.assertIn('secret = ""', body)
        self.assertIn("secret = key", body)
        self.assertIn("secret = token or \"\"", body)
        refused = body.split("if not ok:")[1]
        self.assertLess(refused.index('detail.replace(secret, "***")'), refused.index("raise ChannelUnavailable"))


if __name__ == "__main__":
    unittest.main()

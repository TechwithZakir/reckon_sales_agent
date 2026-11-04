"""Template foundation: merge fields with fallbacks, dynamic content, the ten email blocks, per-channel checks,
pre-send checks and starters (pure, no bench)."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from reckon_sales_agent.agents.content import check_step  # noqa: E402
from reckon_sales_agent.campaigns import builder, presend, starters  # noqa: E402
from reckon_sales_agent.campaigns import templates as t  # noqa: E402


class FieldTests(unittest.TestCase):
    def test_a_field_with_no_value_uses_its_fallback(self):
        self.assertEqual(t.render("Hi {{first_name|there}}", {}), "Hi there")
        self.assertEqual(t.render("Hi {{first_name|there}}", {"first_name": "Rahim"}), "Hi Rahim")
        self.assertEqual(t.render("Hi {{ first_name | there }}", {"first_name": " "}), "Hi there")

    def test_a_field_without_a_fallback_is_empty_when_missing(self):
        self.assertEqual(t.render("Hi {{first_name}}!", {}), "Hi !")

    def test_values_and_fallbacks_are_escaped_and_unknown_fields_removed(self):
        self.assertEqual(t.render("{{business_name}}", {"business_name": "A&B <x>"}), "A&amp;B &lt;x&gt;")
        self.assertEqual(t.render("{{business_name|<b>}}", {}), "&lt;b&gt;")
        self.assertEqual(t.render("a{{bogus|x}}b", {}), "ab")
        self.assertEqual(t.render("{{1}}", {}), "{{1}}")  # Meta's numbered variables are not our fields

    def test_the_field_catalog_is_consistent(self):
        keys = [f[1] for f in t.FIELDS]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(tuple(keys), t.PLACEHOLDERS)
        for group, key, label, sample, fallback, needs in t.FIELDS:
            self.assertTrue(group and label and sample is not None, key)
            if needs and key not in ("contact_name", "offer"):
                self.assertTrue(fallback, f"{key} needs a fallback to offer")

    def test_missing_fallbacks_only_flags_fields_that_can_be_empty(self):
        self.assertEqual(t.missing_fallbacks("{{first_name}} {{city|Dhaka}} {{company}} {{city}}"), ["first_name", "city"])
        self.assertEqual(t.missing_fallbacks("{{personal_line}} {{sender_name}}"), [])


class DynamicTests(unittest.TestCase):
    def block(self):
        return builder._dynamic({"type": "dynamic", "fallback": "Everyone else",
                                 "rules": [{"field": "industry", "op": "contains", "value": "pharma", "text": "For pharma"},
                                           {"field": "city", "op": "is", "value": "Dhaka", "text": "For Dhaka"}]})

    def test_the_first_matching_rule_wins_else_the_fallback(self):
        html = self.block()
        self.assertIn("For pharma", t.resolve_dynamic(html, {"industry": "Pharmaceutical", "city": "Dhaka"}))
        self.assertIn("For Dhaka", t.resolve_dynamic(html, {"industry": "food", "city": "dhaka"}))
        out = t.resolve_dynamic(html, {"industry": "food", "city": "Khulna"})
        self.assertIn("Everyone else", out)
        self.assertNotIn("For pharma", out)

    def test_the_rules_never_reach_the_customer(self):
        out = t.resolve_dynamic(self.block(), {"industry": "pharma"})
        self.assertNotIn("data-rsa-dynamic", out)
        self.assertNotIn("Everyone else", out)

    def test_empty_and_not_empty_rules(self):
        self.assertTrue(t.rule_matches({"field": "city", "op": "empty"}, {}))
        self.assertTrue(t.rule_matches({"field": "city", "op": "not_empty"}, {"city": "x"}))
        self.assertFalse(t.rule_matches({"field": "city", "op": "contains", "value": ""}, {"city": "x"}))

    def test_a_rule_on_an_unknown_field_never_matches(self):
        self.assertFalse(t.rule_matches({"field": "salary", "op": "not_empty"}, {"salary": "1"}))

    def test_unreadable_rules_leave_the_fallback(self):
        out = t.resolve_dynamic('<div data-rsa-dynamic="not json" style="x">fallback</div>', {})
        self.assertIn("fallback", out)

    def test_the_content_check_reads_every_alternative(self):
        words = t.strip_html(self.block())
        for text in ("Everyone else", "For pharma", "For Dhaka"):
            self.assertIn(text, words)

    def test_a_rule_text_is_checked_for_banned_claims(self):
        block = builder._dynamic({"type": "dynamic", "fallback": "ok", "rules": [
            {"field": "industry", "op": "contains", "value": "x", "text": "We guarantee results"}]})
        body = f'<div {t.BUILDER_MARK} style="x">{block}</div>'
        issues = check_step({"step_no": 1, "channel": "Email", "subject_template": "s", "body_template": body}, "", "", [])
        self.assertTrue(any("guarantee" in i for i in issues))


class ContentCheckTests(unittest.TestCase):
    def test_builder_html_is_checked_by_its_words_not_its_markup(self):
        # Styles contain "100%" and make the HTML long; neither is content.
        html = builder.email_html([{"type": "image", "src": "https://x.io/a.png", "alt": "Logo"},
                                   {"type": "text", "text": "Hello there."}])
        self.assertIn("100%", html)
        issues = check_step({"step_no": 1, "channel": "Email", "subject_template": "Hello", "body_template": html}, "", "", [])
        self.assertEqual(issues, [])

    def test_a_banned_phrase_is_still_found_in_the_words(self):
        html = builder.email_html([{"type": "text", "text": "A guaranteed result."}])
        issues = check_step({"step_no": 1, "channel": "Email", "subject_template": "Hello", "body_template": html}, "", "", [])
        self.assertTrue(any("guaranteed" in i for i in issues))

    def test_fallback_fields_are_not_unknown_fields(self):
        issues = check_step({"step_no": 1, "channel": "Email", "subject_template": "Hi {{first_name|there}}",
                             "body_template": "Hello {{business_name|your business}} {{nickname}}"}, "", "", [])
        self.assertTrue(any("nickname" in i for i in issues))
        self.assertFalse(any("first_name" in i or "business_name" in i for i in issues))

    def test_subject_variants_are_checked_too(self):
        issues = check_step({"step_no": 1, "channel": "Email", "subject_template": "Fine",
                             "subject_variants": json.dumps(["The cheapest option"]), "body_template": "Hello"}, "", "", [])
        self.assertTrue(any("cheapest" in i for i in issues))


class EmailBlockTests(unittest.TestCase):
    def test_every_palette_block_compiles_and_starts_valid_except_its_blanks(self):
        for kind in builder.PALETTE:
            block = builder.new_block(kind)
            self.assertEqual(block["type"], kind)
            self.assertIsInstance(builder.email_blocks([block])[0], str)

    def test_a_new_block_with_blanks_says_what_to_fill(self):
        self.assertTrue(builder._check_block(1, builder.new_block("button")))  # "https://" alone is not an address
        self.assertTrue(builder._check_block(1, builder.new_block("image")))
        self.assertEqual(builder._check_block(1, builder.new_block("heading")), [])
        self.assertEqual(builder._check_block(1, builder.new_block("signature")), [])

    def test_columns_product_signature_and_social_output(self):
        columns = builder._columns({"left": "L", "right": "R"})
        self.assertEqual(columns.count("<td "), 2)
        product = builder._product({"title": "Item", "text": "Nice", "price": "Tk 100", "image": "https://x.io/i.png",
                                    "alt": "Item", "label": "View", "url": "https://x.io/p"})
        for needle in ("Item", "Nice", "Tk 100", 'src="https://x.io/i.png"', 'href="https://x.io/p"'):
            self.assertIn(needle, product)
        signature = builder._signature({"closing": "Best,", "name": "Nadia", "company": "Reckon", "phone": "017", "email": "n@x.io"})
        self.assertIn("<b>Nadia</b>", signature)
        social = builder._social({"links": [{"label": "LinkedIn", "url": "https://l.in/x"}, {"label": "Bad", "url": "http://x"}]})
        self.assertIn("LinkedIn", social)
        self.assertNotIn("Bad", social)

    def test_the_preheader_is_hidden_and_escaped(self):
        html = builder.email_html([{"type": "text", "text": "Hi"}], "Plan <inside>")
        self.assertIn("display:none", html)
        self.assertIn("Plan &lt;inside&gt;", html)
        self.assertNotIn("display:none", builder.email_html([{"type": "text", "text": "Hi"}]))

    def test_a_dynamic_block_needs_rules_a_fallback_and_values(self):
        issues = builder._check_block(1, {"type": "dynamic", "rules": [], "fallback": ""})
        self.assertEqual(len(issues), 2)
        issues = builder._check_block(1, {"type": "dynamic", "fallback": "x", "rules": [
            {"field": "salary", "op": "contains", "value": "", "text": ""}]})
        self.assertGreaterEqual(len(issues), 3)

    def test_subject_variants_have_a_limit(self):
        ok = [{"type": "text", "text": "x"}]
        self.assertEqual(builder.check_email("S", ok, ["A", "B"]), [])
        self.assertTrue(any("at most 2" in i for i in builder.check_email("S", ok, ["A", "B", "C"])))
        self.assertTrue(any("variant 1 is empty" in i for i in builder.check_email("S", ok, [""])))

    def test_the_plain_text_covers_the_new_blocks(self):
        text = builder.email_text([{"type": "columns", "left": "L", "right": "R"},
                                   {"type": "product", "title": "Item", "text": "Nice", "label": "View", "url": "https://x.io"},
                                   {"type": "signature", "closing": "Best,", "name": "Nadia"},
                                   {"type": "social", "links": [{"label": "LinkedIn", "url": "https://l.in"}]}])
        for needle in ("L", "R", "Item · Nice", "View: https://x.io", "Best,\nNadia", "LinkedIn: https://l.in"):
            self.assertIn(needle, text)

    def test_unknown_block_types_are_reported_and_compile_to_nothing(self):
        self.assertEqual(builder.email_blocks([{"type": "marquee"}]), [""])
        self.assertTrue(any("unknown type" in i for i in builder.check_email("S", [{"type": "marquee"}])))


class ChannelTests(unittest.TestCase):
    def test_whatsapp_media_headers_need_a_sample_address(self):
        self.assertTrue(any("sample" in i for i in builder.check_whatsapp("", "Body.", "", [], "Image")))
        self.assertEqual(builder.check_whatsapp("https://x.io/a.png", "Body.", "", [], "Image"), [])
        out = builder.whatsapp_components("https://x.io/a.png", "Body.", "", [], "Image")
        self.assertEqual(out["components"]["header"], {"type": "image", "example": "https://x.io/a.png"})

    def test_whatsapp_allows_one_link_and_one_phone_button_together(self):
        buttons = [{"kind": "url", "label": "Site", "url": "https://x.io"}, {"kind": "phone", "label": "Call", "phone": "+8801711123456"}]
        self.assertEqual(builder.check_whatsapp("", "Body.", "", buttons), [])
        two = [{"kind": "url", "label": "A", "url": "https://x.io"}, {"kind": "url", "label": "B", "url": "https://y.io"}]
        self.assertTrue(any("one link button" in i for i in builder.check_whatsapp("", "Body.", "", two)))

    def test_whatsapp_fallback_fields_number_in_order(self):
        out = builder.whatsapp_components("", "Hi {{first_name|there}}, from {{sender_name|us}}.", "", [])
        self.assertEqual(out["components"]["body"]["text"], "Hi {{1}}, from {{2}}.")
        self.assertEqual(out["params"], ["first_name", "sender_name"])

    def test_sms_accepts_the_chosen_keyword_or_the_usual_words(self):
        self.assertEqual(builder.check_sms("Offer. Reply OUT to leave.", "OUT"), [])
        self.assertEqual(builder.check_sms("Offer. Reply STOP to opt out.", "OUT"), [])
        self.assertTrue(builder.check_sms("Offer today", "OUT"))

    def test_linkedin_limits(self):
        self.assertEqual(builder.check_linkedin("Hi", "A message"), [])
        self.assertTrue(builder.check_linkedin("Hi", ""))
        self.assertTrue(any("1900" in i for i in builder.check_linkedin("Hi", "x" * 1901)))


class PresendTests(unittest.TestCase):
    def labels(self, items):
        return {i["label"]: i["ok"] for i in items}

    def test_a_complete_email_passes_every_check(self):
        blocks = [{"type": "heading", "text": "Hi {{first_name|there}}"},
                  {"type": "image", "src": "https://x.io/a.png", "alt": "Logo"},
                  {"type": "button", "label": "Book", "url": "https://x.io/b"}]
        items = presend.email("Short subject", blocks, has_address=True)
        self.assertTrue(all(i["ok"] for i in items), [i for i in items if not i["ok"]])
        self.assertEqual(presend.summary(items), {"ok": True, "open": 0, "total": 7})

    def test_each_email_problem_is_named(self):
        blocks = [{"type": "text", "text": "Hi {{first_name}} about [PRODUCT AREA]"},
                  {"type": "image", "src": "https://x.io/a.png", "alt": ""}]
        text = " | ".join(i["label"] for i in presend.email("s" * 70, blocks, has_address=False) if not i["ok"])
        for needle in ("business address", "70 characters", "first_name", "alt text", "button", "[PRODUCT AREA]"):
            self.assertIn(needle, text)

    def test_a_subject_variant_counts_toward_the_length_check(self):
        blocks = [{"type": "button", "label": "Go", "url": "https://x.io"}]
        items = presend.email("Short", blocks, ["v" * 80])
        self.assertFalse(items[1]["ok"])

    def test_sms_whatsapp_and_linkedin_checks(self):
        self.assertTrue(all(i["ok"] for i in presend.sms("Hi {{first_name|there}} Reply STOP to opt out.", "STOP", "09:00-21:00")))
        self.assertFalse(presend.sms("Hello", "STOP", "")[0]["ok"])
        wa = presend.whatsapp("", "Hi {{first_name|there}}, hello.", "Reply STOP to unsubscribe", [], {"first_name": "Rahim"}, category="Marketing")
        self.assertTrue(all(i["ok"] for i in wa), [i for i in wa if not i["ok"]])
        bad = presend.whatsapp("", "Hi {{first_name}}, hello.", "", [], {}, category="")
        self.assertEqual(sum(1 for i in bad if not i["ok"]), 4)
        self.assertTrue(all(i["ok"] for i in presend.linkedin("Hi", "A short note for {{first_name|you}}")))

    def test_bracket_placeholders_are_found_once_each(self):
        self.assertEqual(presend.bracket_placeholders("[SHORT LINK] and [SHORT LINK]", "https://[BOOKING LINK]"),
                         ["[SHORT LINK]", "[BOOKING LINK]"])
        self.assertEqual(presend.bracket_placeholders("[x] [ok] [Mixed Case]"), [])


class StarterTests(unittest.TestCase):
    def test_every_starter_passes_the_builders_own_checks(self):
        for starter in starters.STARTERS:
            email = starter.get("Email")
            if email:
                self.assertEqual(builder.check_email(email["subject"], email["blocks"], email.get("variants", [])), [], starter["id"])
            sms = starter.get("SMS")
            if sms:
                self.assertEqual(builder.check_sms(sms["text"], sms.get("keyword", "STOP")), [], starter["id"])
            wa = starter.get("WhatsApp")
            if wa:
                self.assertEqual(builder.check_whatsapp(wa["header"], wa["body"], wa["footer"], wa["buttons"], wa["header_type"]),
                                 [], starter["id"])
            li = starter.get("LinkedIn")
            if li:
                self.assertEqual(builder.check_linkedin(li["subject"], li["text"]), [], starter["id"])

    def test_every_starter_passes_the_content_check_apart_from_its_placeholders(self):
        for starter in starters.STARTERS:
            email = starter.get("Email")
            if email:
                body = builder.email_html(email["blocks"], email["preheader"])
                issues = check_step({"step_no": 1, "channel": "Email", "subject_template": email["subject"],
                                     "subject_variants": email["variants"], "body_template": body}, "", "", [])
                self.assertEqual(issues, [], starter["id"])

    def test_starters_leave_the_links_to_fill_and_say_so(self):
        email = starters.starter_content("post_demo", "Email")
        flagged = presend.email(email["subject"], email["blocks"], email["variants"])
        self.assertTrue(any("[BOOKING LINK]" in i["label"] for i in flagged if not i["ok"]))

    def test_starter_content_is_a_copy(self):
        first = starters.starter_content("post_demo", "SMS")
        first["text"] = "changed"
        self.assertNotEqual(starters.starter_content("post_demo", "SMS")["text"], "changed")
        self.assertIsNone(starters.starter_content("post_demo", "Fax"))
        self.assertIsNone(starters.starter_content("nope", "Email"))

    def test_the_summaries_list_the_channels_each_starter_has(self):
        by_id = {s["id"]: s for s in starters.starter_summaries()}
        self.assertEqual(by_id["post_demo"]["channels"], ["Email", "SMS", "WhatsApp", "LinkedIn"])
        self.assertEqual(by_id["event"]["channels"], ["Email", "SMS"])

    def test_the_built_in_sections_compile(self):
        for section in starters.BUILTIN_SECTIONS:
            self.assertTrue(all(isinstance(h, str) for h in builder.email_blocks(section["blocks"])), section["id"])


if __name__ == "__main__":
    unittest.main()

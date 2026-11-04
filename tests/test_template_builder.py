"""Template builder for Email, SMS and WhatsApp: output and channel rules (pure, no bench)."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from reckon_sales_agent.campaigns import builder  # noqa: E402

APP = Path(__file__).parents[1] / "reckon_sales_agent"
OPT_OUT = "Reply STOP to opt out."


class EmailBuilderTests(unittest.TestCase):
    def test_blocks_compile_to_inline_styled_html(self):
        html = builder.email_html([{"type": "heading", "text": "Hi {{business_name}}"},
                                   {"type": "text", "text": "One.\n\nTwo"}])
        self.assertIn("<h2", html)
        self.assertIn("style=", html)
        self.assertIn("Hi {{business_name}}", html)  # merge tags survive for the renderer
        self.assertEqual(html.count("<p "), 2)

    def test_text_is_escaped(self):
        html = builder.email_html([{"type": "text", "text": "<script>x</script> & more"}])
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_button_and_image_links_are_escaped(self):
        html = builder.email_html([{"type": "button", "label": "Go", "url": "https://x.io/?a=1&b=2"},
                                   {"type": "image", "src": "https://x.io/a.png", "alt": 'a "b"'}])
        self.assertIn('href="https://x.io/?a=1&amp;b=2"', html)
        self.assertIn('alt="a &quot;b&quot;"', html)

    def test_plain_text_version_keeps_the_words_and_the_links(self):
        text = builder.email_text([{"type": "heading", "text": "Title"}, {"type": "text", "text": "Body"},
                                   {"type": "button", "label": "Book", "url": "https://x.io/b"}])
        self.assertEqual(text, "Title\n\nBody\n\nBook: https://x.io/b")

    def test_subject_is_required_and_capped(self):
        self.assertIn("The email needs a subject.", builder.check_email("", [{"type": "text", "text": "x"}]))
        self.assertTrue(any("keep it under" in i for i in builder.check_email("s" * 151, [{"type": "text", "text": "x"}])))

    def test_buttons_need_https_and_a_label(self):
        issues = builder.check_email("S", [{"type": "button", "label": "", "url": "http://x.io"}])
        self.assertTrue(any("needs a label" in i for i in issues))
        self.assertTrue(any("https://" in i for i in issues))

    def test_unknown_merge_tags_are_reported(self):
        issues = builder.check_email("Hi {{first_name}}", [{"type": "text", "text": "{{offer}} and {{bogus}}"}])
        self.assertIn("Unknown merge tag {{bogus}}.", issues)
        self.assertIn("Unknown merge tag {{first_name}}.", issues)
        self.assertNotIn("Unknown merge tag {{offer}}.", issues)

    def test_an_empty_email_has_no_blocks_issue_only_when_there_are_blocks(self):
        self.assertIn("Add at least one block to the email.", builder.check_email("S", []))


class SmsBuilderTests(unittest.TestCase):
    def test_gsm_text_is_160_for_one_part_and_153_when_split(self):
        self.assertEqual(builder.sms_parts("a" * 160), 1)
        self.assertEqual(builder.sms_parts("a" * 161), 2)
        self.assertEqual(builder.sms_parts("a" * 306), 2)
        self.assertEqual(builder.sms_parts("a" * 307), 3)

    def test_unicode_text_is_70_for_one_part_and_67_when_split(self):
        bangla = "আ" * 70
        self.assertEqual(builder.sms_encoding(bangla), "UCS-2")
        self.assertEqual(builder.sms_parts(bangla), 1)
        self.assertEqual(builder.sms_parts("আ" * 71), 2)
        self.assertEqual(builder.sms_parts("আ" * 134), 2)

    def test_gsm_extension_characters_count_twice(self):
        self.assertEqual(builder.sms_encoding("[ok]"), "GSM-7")
        self.assertEqual(builder.sms_length("[]"), 4)

    def test_opt_out_line_is_required(self):
        self.assertTrue(any("opt-out" in i for i in builder.check_sms("Offer today")))
        self.assertEqual(builder.check_sms(f"Offer today. {OPT_OUT}"), [])

    def test_bangla_opt_out_word_counts(self):
        self.assertEqual(builder.check_sms("অফার। বন্ধ লিখুন"), [])

    def test_too_many_parts_is_refused(self):
        self.assertTrue(any("parts" in i for i in builder.check_sms("a" * 500 + " " + OPT_OUT)))

    def test_empty_sms_is_refused(self):
        self.assertEqual(builder.check_sms("  "), ["The SMS needs a message."])


class WhatsAppBuilderTests(unittest.TestCase):
    def test_merge_tags_become_numbered_variables_in_order(self):
        out = builder.whatsapp_components("", "Dear {{business_name}}, offer {{offer}} for {{business_name}}.", "", [])
        self.assertEqual(out["components"]["body"]["text"], "Dear {{1}}, offer {{2}} for {{1}}.")
        self.assertEqual(out["params"], ["business_name", "offer"])

    def test_components_follow_metas_shape(self):
        out = builder.whatsapp_components("Hello", "Body text here.", "Reckon",
                                          [{"kind": "quick", "label": "Yes"}, {"kind": "url", "label": "Site", "url": "https://x.io"}])
        c = out["components"]
        self.assertEqual(c["header"], {"type": "text", "text": "Hello"})
        self.assertEqual(c["footer"], {"text": "Reckon"})
        self.assertEqual(c["buttons"], [{"type": "quick_reply", "text": "Yes"},
                                        {"type": "url", "text": "Site", "url": "https://x.io"}])

    def test_body_limits_and_header_limits(self):
        self.assertTrue(any("1024" in i for i in builder.check_whatsapp("", "a" * 1025, "", [])))
        self.assertTrue(any("header is" in i for i in builder.check_whatsapp("h" * 61, "Body.", "", [])))
        self.assertTrue(any("footer is" in i for i in builder.check_whatsapp("", "Body.", "f" * 61, [])))

    def test_body_cannot_start_or_end_with_a_variable(self):
        self.assertTrue(any("starts with a variable" in i for i in builder.check_whatsapp("", "{{offer}} now", "", [])))
        self.assertTrue(any("ends with a variable" in i for i in builder.check_whatsapp("", "Offer {{offer}}", "", [])))

    def test_header_takes_no_merge_tags(self):
        self.assertTrue(any("header cannot use" in i for i in builder.check_whatsapp("Hi {{first_name}}", "Body.", "", [])))

    def test_button_rules(self):
        self.assertTrue(any("up to 3" in i for i in builder.check_whatsapp("", "Body.", "", [{"kind": "quick", "label": str(n)} for n in range(4)])))
        self.assertTrue(any("25" in i for i in builder.check_whatsapp("", "Body.", "", [{"kind": "quick", "label": "x" * 26}])))
        self.assertTrue(any("https://" in i for i in builder.check_whatsapp("", "Body.", "", [{"kind": "url", "label": "Go", "url": "http://x.io"}])))
        self.assertTrue(any("not both" in i for i in builder.check_whatsapp("", "Body.", "", [{"kind": "url", "label": "Go", "url": "https://x.io"}, {"kind": "quick", "label": "Yes"}])))

    def test_valid_template_has_no_issues(self):
        self.assertEqual(builder.check_whatsapp("Hello", "Dear {{business_name}}, we can help.", "Reckon",
                                                [{"kind": "quick", "label": "Yes"}]), [])


class EndpointTests(unittest.TestCase):
    def test_check_and_save_are_manager_only_and_tenant_checked(self):
        source = (APP / "api_templates.py").read_text(encoding="utf-8")
        for name in ("def check(", "def save("):
            body = source.split(name)[1].split("\n@")[0]
            self.assertIn("_require_manager()", body, name)
        save_body = source.split("def save(")[1].split("\n@")[0] if "\n@" in source.split("def save(")[1] else source.split("def save(")[1]
        self.assertIn('get_tenant_doc("Sales Message Template", template, "write")', save_body)
        self.assertIn("doc.save(ignore_permissions=False)", save_body)

    def test_save_keeps_the_draft_status_for_approval(self):
        source = (APP / "api_templates.py").read_text(encoding="utf-8")
        save_body = source.split("def save(")[1]
        self.assertNotIn('doc.status = "Approved"', save_body)

    def test_the_builder_source_is_stored_on_the_template(self):
        doc = json.loads((APP / "reckon_sales_agent" / "doctype" / "sales_message_template"
                          / "sales_message_template.json").read_text(encoding="utf-8"))
        self.assertIn("builder_content", doc["field_order"])
        self.assertIn("builder_content", [f["fieldname"] for f in doc["fields"]])


class BuilderScreenTests(unittest.TestCase):
    PAGE = APP / "reckon_sales_agent" / "page" / "sales_templates"

    def test_each_channel_has_its_own_editor(self):
        source = (self.PAGE / "sales_templates.js").read_text(encoding="utf-8")
        for needle in ('ch === "Email"', 'ch === "SMS"', '"heading", "text", "button", "image", "divider", "spacer"',
                       'data-k="header"', 'data-k="footer"', "stp-b-addbtn"):
            self.assertIn(needle, source)

    def test_the_screen_checks_before_it_saves_and_saves_only_on_request(self):
        source = (self.PAGE / "sales_templates.js").read_text(encoding="utf-8")
        self.assertIn('API + "check"', source)
        self.assertEqual(source.count('API + "save"'), 1)

    def test_existing_templates_can_be_reopened_in_the_builder(self):
        source = (self.PAGE / "sales_templates.js").read_text(encoding="utf-8")
        self.assertIn("stp-open", source)
        self.assertIn("builder_content", (APP / "api_templates.py").read_text(encoding="utf-8"))

    def test_the_page_is_one_column_now_that_email_health_moved(self):
        css = (self.PAGE / "sales_templates.css").read_text(encoding="utf-8")
        self.assertIn("grid-template-columns: minmax(0, 1fr);", css)
        self.assertNotIn("300px", css)

    def test_editing_an_approved_template_sends_it_back_to_draft(self):
        source = (APP / "api_templates.py").read_text(encoding="utf-8")
        body = source.split("def save(")[1].split("\n@")[0]
        self.assertIn('doc.status = "Draft"', body)

    def test_starting_a_template_is_manager_only_and_creates_a_draft(self):
        source = (APP / "api_templates.py").read_text(encoding="utf-8")
        body = source.split("def start(")[1]
        self.assertIn("_require_manager()", body)
        self.assertIn('"status": "Draft"', body)


if __name__ == "__main__":
    unittest.main()

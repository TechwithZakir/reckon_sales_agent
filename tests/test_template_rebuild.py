"""The template builder rebuild: content mapping, A/B variants, AI draft handling, the template agent, the engine, the
screens and their calls into the backend (pure, no bench)."""
import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from reckon_sales_agent import constants  # noqa: E402
from reckon_sales_agent.agents import template_ai  # noqa: E402
from reckon_sales_agent.agents.templates import template_issues  # noqa: E402
from reckon_sales_agent.campaigns import builder, starters, template_content, variants  # noqa: E402
from reckon_sales_agent.campaigns import templates as t  # noqa: E402

APP = Path(__file__).parents[1] / "reckon_sales_agent"
INNER = APP / "reckon_sales_agent"
PAGE = INNER / "page" / "sales_templates"
STUDIO = INNER / "page" / "campaign_studio"


def read(*parts) -> str:
    return Path(APP, *parts).read_text(encoding="utf-8")


def doctype(name: str) -> dict:
    folder = name.lower().replace(" ", "_")
    return json.loads((INNER / "doctype" / folder / f"{folder}.json").read_text(encoding="utf-8"))


class NormalizeTests(unittest.TestCase):
    def test_unknown_blocks_and_keys_are_dropped_and_text_is_capped(self):
        c = template_content.normalize("Email", {"subject": "s" * 500, "blocks": [
            {"type": "marquee", "text": "x"}, {"type": "text", "text": "y" * 9000, "evil": "<script>"}, "junk", None]})
        self.assertEqual(len(c["subject"]), 300)
        self.assertEqual(len(c["blocks"]), 1)
        self.assertEqual(len(c["blocks"][0]["text"]), 5000)
        self.assertNotIn("evil", c["blocks"][0])

    def test_blocks_are_limited_and_their_lists_are_bounded(self):
        c = template_content.normalize("Email", {"blocks": [{"type": "divider"}] * 200})
        self.assertEqual(len(c["blocks"]), template_content.MAX_BLOCKS)
        c = template_content.normalize("Email", {"blocks": [{"type": "dynamic", "rules": [{"field": "city"}] * 20, "fallback": "f"},
                                                           {"type": "social", "links": [{"label": "a", "url": "https://x.io"}] * 20}]})
        self.assertEqual((len(c["blocks"][0]["rules"]), len(c["blocks"][1]["links"])), (6, 6))

    def test_whatsapp_content_is_typed_and_samples_are_for_real_fields_only(self):
        c = template_content.normalize("WhatsApp", {"header_type": "Video", "body": "b", "category": "Gambling", "buttons": [
            {"kind": "weird", "label": "x" * 99}] * 9, "samples": {"first_name": "Rahim", "password": "x"}})
        self.assertEqual((c["header_type"], c["category"]), ("None", "Marketing"))
        self.assertEqual(len(c["buttons"]), 5)
        self.assertEqual(c["buttons"][0]["kind"], "quick")
        self.assertEqual(len(c["buttons"][0]["label"]), 40)
        self.assertEqual(c["samples"], {"first_name": "Rahim"})

    def test_anything_that_is_not_a_dict_gives_empty_content(self):
        for bad in (None, "x", [1], 5):
            c = template_content.normalize("SMS", bad)
            self.assertEqual((c["text"], c["keyword"]), ("", "STOP"))

    def test_actions_keep_only_the_known_ones(self):
        c = template_content.normalize("SMS", {"actions": {"personalize": 0, "hack": 1, "handoff": "yes"}})
        self.assertEqual(c["actions"], {"personalize": False, "handoff": True})


class FieldMappingTests(unittest.TestCase):
    def test_email_content_becomes_stored_fields_and_back(self):
        content = {"subject": "Hi {{first_name|there}}", "preheader": "Pre", "variants": ["B subject"],
                   "blocks": [{"type": "text", "text": "Hello"}], "actions": {"personalize": True}, "ai": {"brief": "b", "goal": "Upsell", "tone": "Direct"}}
        fields = template_content.fields_to_store("Email", content)
        self.assertEqual((fields["subject"], fields["preheader"], fields["ai_goal"]), ("Hi {{first_name|there}}", "Pre", "Upsell"))
        self.assertEqual(json.loads(fields["subject_variants"]), ["B subject"])
        self.assertTrue(t.is_builder_html(fields["body"]))
        self.assertIn("Pre", fields["body"])
        back = template_content.content_from_fields("Email", fields)
        self.assertEqual((back["subject"], back["variants"], back["blocks"][0]["text"]), ("Hi {{first_name|there}}", ["B subject"], "Hello"))

    def test_blank_variants_are_not_stored(self):
        fields = template_content.fields_to_store("Email", {"subject": "s", "variants": ["", " "], "blocks": []})
        self.assertEqual(fields["subject_variants"], "")

    def test_sms_whatsapp_and_linkedin_fields(self):
        sms = template_content.fields_to_store("SMS", {"text": "Hi. Reply STOP to opt out.", "keyword": "OUT", "window": " 09:00-21:00 "})
        self.assertEqual((sms["body"], sms["opt_out_keyword"], sms["sms_send_window"]), ("Hi. Reply STOP to opt out.", "OUT", "09:00-21:00"))
        wa = template_content.fields_to_store("WhatsApp", {"body": "Hi {{first_name|there}}, from {{sender_name|us}}.", "footer": "Reply STOP",
                                                           "buttons": [{"kind": "quick", "label": "Yes"}], "samples": {"first_name": "Rahim"}})
        self.assertEqual(wa["whatsapp_params"], "first_name,sender_name")
        self.assertEqual(json.loads(wa["whatsapp_samples"]), {"first_name": "Rahim", "sender_name": "Nadia"})  # a real value for every variable
        li = template_content.fields_to_store("LinkedIn", {"subject": " Hi ", "text": " Body "})
        self.assertEqual((li["subject"], li["body"]), ("Hi", "Body"))

    def test_a_stored_whatsapp_sample_is_what_meta_receives_not_a_blank(self):
        wa = template_content.fields_to_store("WhatsApp", {"body": "Hi {{business_name|you}}, hello.", "samples": {}})
        self.assertEqual(json.loads(wa["whatsapp_samples"])["business_name"], "Acme Foods")

    def test_an_empty_body_is_stored_as_a_dash_because_the_field_is_required(self):
        self.assertEqual(template_content.fields_to_store("SMS", {"text": ""})["body"], "-")

    def test_older_plain_templates_open_in_the_builder(self):
        email = template_content.content_from_fields("Email", {"subject": "Old", "body": "Para one.\n\nPara two."})
        self.assertEqual(email["blocks"], [{"type": "text", "text": "Para one.\n\nPara two."}])
        wa = template_content.content_from_fields("WhatsApp", {"body": "Hi {{1}}, from {{2}}.", "whatsapp_params": "first_name,sender_name"})
        self.assertEqual(wa["body"], "Hi {{first_name}}, from {{sender_name}}.")
        self.assertEqual(template_content.content_from_fields("SMS", {"body": "Text"})["text"], "Text")
        li = template_content.content_from_fields("LinkedIn", {"subject": "S", "body": "B"})
        self.assertEqual((li["subject"], li["text"]), ("S", "B"))

    def test_a_form_edit_of_the_subject_is_not_lost(self):
        saved = template_content.fields_to_store("Email", {"subject": "Builder subject", "blocks": []})
        saved["subject"] = "Changed in the form"
        self.assertEqual(template_content.content_from_fields("Email", saved)["subject"], "Changed in the form")

    def test_corrupt_saved_content_falls_back_to_the_plain_fields(self):
        c = template_content.content_from_fields("SMS", {"builder_content": "{not json", "body": "Plain"})
        self.assertEqual(c["text"], "Plain")


class CompileTests(unittest.TestCase):
    def test_email_result_has_everything_the_screen_shows(self):
        content = template_content.with_starter("Email", starters.starter_content("post_demo", "Email"))
        r = template_content.compile_content("Email", content)
        for key in ("issues", "checks", "summary", "body", "previews", "text", "sample_html", "sample_subject"):
            self.assertIn(key, r)
        self.assertEqual(len(r["previews"]), len(content["blocks"]))
        self.assertIn("Rahim", r["sample_html"])  # sample values fill the fields
        self.assertNotIn("{{first_name", r["sample_html"])

    def test_merge_fields_are_chips_in_the_preview_but_never_inside_a_tag(self):
        r = template_content.compile_content("Email", {"subject": "s", "blocks": [
            {"type": "button", "label": "Go {{first_name|there}}", "url": "https://x.io/?w={{website}}"}]})
        self.assertIn('<span class="tb-tag">{{first_name|there}}</span>', r["previews"][0])
        self.assertIn("w={{website}}", r["previews"][0])  # the address is untouched
        self.assertNotIn('href="https://x.io/?w=<span', r["previews"][0])

    def test_sms_whatsapp_and_linkedin_results(self):
        sms = template_content.compile_content("SMS", {"text": "Hi {{first_name|there}}. Reply STOP to opt out."})
        self.assertEqual((sms["parts"], sms["encoding"], sms["sample"]), (1, "GSM-7", "Hi Rahim. Reply STOP to opt out."))
        wa = template_content.compile_content("WhatsApp", {"body": "Hi {{first_name|there}}, hello.", "footer": "Reply STOP to unsubscribe"})
        self.assertEqual((wa["params"], wa["components"]["body"]["text"]), (["first_name"], "Hi {{1}}, hello."))
        self.assertEqual(wa["sample"], "Hi Rahim, hello.")
        li = template_content.compile_content("LinkedIn", {"subject": "Hi", "text": "Body {{first_name|you}}"})
        self.assertEqual(li["sample"], "Body Rahim")

    def test_the_address_check_follows_the_company(self):
        blocks = [{"type": "button", "label": "Go", "url": "https://x.io"}]
        with_address = template_content.compile_content("Email", {"subject": "s", "blocks": blocks}, has_address=True)
        without = template_content.compile_content("Email", {"subject": "s", "blocks": blocks}, has_address=False)
        self.assertTrue(with_address["checks"][0]["ok"])
        self.assertFalse(without["checks"][0]["ok"])

    def test_blank_templates_and_starters_start_in_a_working_shape(self):
        for channel in ("Email", "SMS", "WhatsApp", "LinkedIn"):
            self.assertIsInstance(template_content.compile_content(channel, template_content.new_content(channel)), dict)
        self.assertEqual(template_content.new_content("SMS")["window"], "09:00-21:00")
        for starter in starters.STARTERS:
            for channel in ("Email", "SMS", "WhatsApp", "LinkedIn"):
                found = starters.starter_content(starter["id"], channel)
                if found:
                    r = template_content.compile_content(channel, template_content.with_starter(channel, found))
                    self.assertEqual(r["issues"], [], f"{starter['id']} {channel}")


class VariantTests(unittest.TestCase):
    def test_no_alternatives_means_no_test(self):
        self.assertEqual(variants.choose("k", "Main", None), ("", "Main"))
        self.assertEqual(variants.choose("k", "Main", "[]"), ("", "Main"))

    def test_the_same_person_and_step_always_get_the_same_subject(self):
        first = variants.choose("MEM-1:1", "Main", '["B"]')
        self.assertEqual(first, variants.choose("MEM-1:1", "Main", '["B"]'))
        self.assertIn(first[0], "AB")

    def test_the_audience_is_split_close_to_evenly(self):
        picks = [variants.choose(f"MEM-{n}:1", "Main", ["B", "C"])[0] for n in range(3000)]
        for letter in "ABC":
            self.assertGreater(picks.count(letter), 800, letter)
        self.assertEqual(variants.choose("x", "Main", ["Main"]), ("", "Main"))  # a repeat of the main subject is no test

    def test_parse_cleans_and_limits(self):
        self.assertEqual(variants.parse(' ["  B  ", "", "B", "C", "D"] '), ["B", "C"])
        self.assertEqual(variants.parse("not json"), [])
        self.assertEqual(variants.parse({"a": 1}), [])

    def test_a_winner_needs_enough_sends_and_a_clear_gap(self):
        rows = {"A": {"sent": 50, "open_rate": 20.0}, "B": {"sent": 50, "open_rate": 31.0}}
        self.assertEqual(variants.winner(rows), ("B", 31.0, 20.0))
        self.assertIsNone(variants.winner({"A": {"sent": 10, "open_rate": 20.0}, "B": {"sent": 50, "open_rate": 40.0}}))
        self.assertIsNone(variants.winner({"A": {"sent": 50, "open_rate": 20.0}, "B": {"sent": 50, "open_rate": 22.0}}))
        self.assertIsNone(variants.winner({"A": {"sent": 50, "open_rate": 20.0}}))


class AiContentTests(unittest.TestCase):
    def test_an_email_answer_becomes_blocks_with_a_link_to_fill(self):
        c = template_ai.email_content({"subject": "Subject", "preheader": "Pre", "variants": ["B", "C", "D", "E"], "headline": "Hello",
                                       "paragraphs": ["One", "Two"], "button_label": "Book"})
        self.assertEqual([b["type"] for b in c["blocks"]], ["heading", "text", "button", "signature"])
        self.assertEqual(c["blocks"][2]["url"], "https://[BOOKING LINK]")
        self.assertEqual(len(c["variants"]), 3)  # the screen keeps two as the test and offers the rest
        self.assertEqual(c["blocks"][1]["text"], "One\n\nTwo")

    def test_an_sms_answer_gets_its_opt_out_line_unless_it_has_one(self):
        self.assertTrue(template_ai.sms_content({"text": "Hello"})["text"].endswith("Reply STOP to opt out."))
        self.assertEqual(template_ai.sms_content({"text": "Hello. Reply STOP to opt out."})["text"], "Hello. Reply STOP to opt out.")
        self.assertIn("বন্ধ করতে STOP", template_ai.sms_content({"text": "হ্যালো"}, "Bangla")["text"])
        self.assertEqual(builder.check_sms(template_ai.sms_content({"text": "Hello"})["text"]), [])

    def test_a_whatsapp_answer_is_made_acceptable_to_meta(self):
        c = template_ai.whatsapp_content({"body": "{{first_name|there}} welcome {{offer}}", "buttons": ["Yes", "No", "Later", "Extra"]})
        self.assertTrue(c["body"].startswith("Hi {{"))
        self.assertTrue(c["body"].endswith("}}."))
        self.assertEqual(len(c["buttons"]), 3)
        self.assertEqual(builder.check_whatsapp(c["header"], c["body"], c["footer"], c["buttons"], c["header_type"]), [])

    def test_content_from_picks_the_channel(self):
        self.assertIn("blocks", template_ai.content_from("Email", {"subject": "s", "headline": "h", "paragraphs": [], "variants": []}))
        self.assertIn("text", template_ai.content_from("LinkedIn", {"subject": "s", "text": "t"}))

    def test_the_prompt_lists_the_real_fields_with_their_fallbacks(self):
        for field in t.FIELDS:
            self.assertIn("{{" + field[1], template_ai.SYSTEM)
        self.assertIn("{{first_name|there}}", template_ai.SYSTEM)

    def test_every_channel_has_a_schema_and_a_length_rule(self):
        for channel in template_ai.CHANNELS:
            self.assertIn(channel, template_ai.SCHEMAS)
            self.assertIn(channel, template_ai.LENGTHS)


class TemplateAgentTests(unittest.TestCase):
    source = read("agents", "templates.py")

    def test_whatsapp_variables_may_be_named_or_numbered(self):
        self.assertEqual(template_issues("WhatsApp", "Hi {{first_name|there}}, from {{sender_name|us}}.", "first_name,sender_name"), [])
        self.assertTrue(template_issues("WhatsApp", "Hi {{first_name}}.", "first_name,sender_name"))
        self.assertEqual(template_issues("WhatsApp", "Hi {{1}}, from {{2}}.", "first_name,sender_name"), [])
        self.assertTrue(template_issues("WhatsApp", "Hi {{1}}, from {{3}}.", "a,b"))

    def test_the_check_reads_the_words_includes_variants_and_catches_unfilled_placeholders(self):
        body = self.source.split("def check_template(")[1].split("\ndef ")[0]
        for needle in ("strip_html(doc.body) if is_builder_html(doc.body)", '"subject_variants": doc.get("subject_variants")',
                       "bracket_placeholders(", "Placeholders still to fill", 'channel = "Call Task" if doc.channel == "LinkedIn"'):
            self.assertIn(needle, body)

    def test_approval_never_waves_through_an_email_without_a_subject(self):
        body = self.source.split("def approve(")[1].split("\ndef ")[0]
        self.assertIn('An email template needs a subject before it can be approved.', body)
        controller = read("reckon_sales_agent", "doctype", "sales_message_template", "sales_message_template.py")
        self.assertNotIn("An email template needs a subject", controller)  # a draft may be unfinished

    def test_the_crm_composer_never_receives_jinja_breaking_fallbacks_or_escaped_markup(self):
        body = self.source.split("def _publish_email(")[1].split("\ndef ")[0]
        self.assertIn("fallbacks_only", body)
        self.assertIn("fallback_only(doc.body) if is_builder_html(doc.body)", body)

    def test_meta_receives_numbered_variables_header_footer_samples_and_buttons(self):
        body = self.source.split("def _publish_whatsapp(")[1].split("\ndef apply_to_step(")[0]
        for needle in ("meta_body(doc.body)", '"sample_values"', '"footer"', '"header_type"', 'template.set("buttons"',
                       "_meta_button", "Attach the sample"):
            self.assertIn(needle, body)
        button = self.source.split("def _meta_button(")[1]
        for needle in ("Visit Website", "Call Phone", "Quick Reply"):
            self.assertIn(needle, button)

    def test_a_step_takes_the_variants_the_hours_the_personalisation_and_maps_linkedin_to_a_task(self):
        body = self.source.split("def apply_to_step(")[1].split("\ndef ")[0]
        for needle in ('"LinkedIn Task" if template.channel == "LinkedIn"', "row.subject_variants", "row.send_window",
                       "use_ai_personalisation", '"sms_send_window"', '"agent_actions"'):
            self.assertIn(needle, body)

    def test_a_linkedin_template_cannot_be_broadcast(self):
        self.assertIn("A LinkedIn message is sent by a person", self.source)


class EngineWiringTests(unittest.TestCase):
    engine = read("campaigns", "engine.py")

    def test_the_new_fields_dynamic_content_and_variants_reach_each_message(self):
        body = self.engine.split("def draft_message(")[1].split("def _personal_line(")[0]
        for needle in ('"first_name": contact.split(" ")[0] if contact else ""', '"contact_name": contact', '"owner_name":',
                       "resolve_dynamic(step.body_template, values)", "variants.choose(key, step.subject_template",
                       '"variant": letter or None'):
            self.assertIn(needle, body)

    def test_a_step_can_have_its_own_sending_hours(self):
        body = self.engine.split("def send_message(")[1]
        self.assertIn('step_window = next((s.get("send_window") for s in campaign.steps', body)
        self.assertIn("or not in_window(step_window, minutes)", body)

    def test_variants_are_counted_per_subject(self):
        self.assertIn("m.variant", read("campaigns", "people.py"))
        self.assertIn("m.variant", read("campaigns", "analytics.py"))
        self.assertIn('"by_variant": by_variant', read("campaigns", "metrics.py"))
        self.assertIn('ab.winner(engagement.get("by_variant")', read("campaigns", "copilot.py"))

    def test_the_approval_binds_variants_and_hours_only_when_set(self):
        source = read("agents", "approvals.py")
        self.assertIn('extra = [_get(step, "subject_variants") or "", _get(step, "send_window") or ""]', source)
        self.assertIn("if any(extra) else key", source)


class DataModelTests(unittest.TestCase):
    def test_the_template_has_the_builder_fields_and_linkedin(self):
        doc = doctype("Sales Message Template")
        fields = {f["fieldname"]: f for f in doc["fields"]}
        for name in ("preheader", "subject_variants", "opt_out_keyword", "sms_send_window", "whatsapp_header_type", "whatsapp_header",
                     "whatsapp_footer", "whatsapp_buttons", "whatsapp_samples", "agent_actions", "ai_brief", "ai_goal", "ai_tone"):
            self.assertIn(name, fields, name)
        self.assertIn("LinkedIn", fields["channel"]["options"].split("\n"))
        self.assertEqual(fields["whatsapp_header_type"]["options"].split("\n"), ["None", "Text", "Image", "Document"])
        self.assertEqual([f["fieldname"] for f in doc["fields"]], doc["field_order"])

    def test_every_approval_bound_field_is_listed_on_the_controller(self):
        controller = read("reckon_sales_agent", "doctype", "sales_message_template", "sales_message_template.py")
        for name in ("preheader", "subject_variants", "sms_send_window", "whatsapp_header", "whatsapp_footer", "whatsapp_buttons"):
            self.assertIn(f'"{name}"', controller.split("BOUND = ")[1].split("\n\n")[0], name)

    def test_the_other_doctypes_carry_what_the_engine_writes(self):
        for name, field in (("Sales Campaign Step", "subject_variants"), ("Sales Campaign Step", "send_window"),
                            ("Sales Outreach Message", "variant"), ("Sales Prospect", "contact_name"), ("Sales Campaign", "goal")):
            doc = doctype(name)
            self.assertIn(field, [f["fieldname"] for f in doc["fields"]], f"{name}.{field}")
            self.assertEqual([f["fieldname"] for f in doc["fields"]], doc["field_order"], name)

    def test_sections_are_a_company_doctype_with_a_required_company(self):
        self.assertIn("Sales Template Section", constants.COMPANY_DOCTYPES)
        doc = doctype("Sales Template Section")
        company = next(f for f in doc["fields"] if f["fieldname"] == "company")
        self.assertEqual((company["fieldtype"], company["options"], company.get("reqd")), ("Link", "Company", 1))
        users = next(p for p in doc["permissions"] if p["role"] == "Reckon Sales Agent User")
        self.assertFalse(users.get("write") or users.get("create") or users.get("delete"))

    def test_the_prospect_contact_name_feeds_the_greeting(self):
        self.assertIn('"first_name": contact.split(" ")[0]', read("campaigns", "engine.py"))
        self.assertIn("contact_name", [f[1] for f in t.FIELDS])


class ApiTests(unittest.TestCase):
    api = read("api_templates.py")

    def whitelisted(self) -> set[str]:
        return set(re.findall(r"@frappe\.whitelist\([^)]*\)\n(?:@[^\n]+\n)*def (\w+)\(", self.api))

    def test_the_builder_only_calls_endpoints_that_exist(self):
        script = (PAGE / "sales_templates.js").read_text(encoding="utf-8")
        calls = set(re.findall(r'API \+ "(\w+)"', script))
        self.assertTrue(calls)
        self.assertEqual(calls - self.whitelisted(), set())

    def test_the_studio_calls_template_endpoints_that_exist(self):
        script = (STUDIO / "campaign_studio.js").read_text(encoding="utf-8")
        named = set(re.findall(r'"reckon_sales_agent\.api_templates\.(\w+)"', script))
        self.assertEqual(named - self.whitelisted(), set())

    def test_every_writer_needs_a_manager_and_is_post_only(self):
        for name in ("start", "save", "duplicate", "ai_draft", "ai_edit", "send_test", "save_section", "delete_section"):
            body = self.api.split(f"def {name}(")[1].split("\n@frappe.whitelist")[0]
            self.assertIn("_require_manager()", body, name)
        for name in ("start", "save", "duplicate", "ai_draft", "ai_edit", "send_test", "save_section"):
            decorator = self.api.split(f"def {name}(")[0].rsplit("@frappe.whitelist", 1)[1].split("\n")[0]
            self.assertIn('methods=["POST"]', decorator, name)

    def test_templates_are_loaded_with_a_permission_check(self):
        self.assertNotIn("frappe.get_doc(", self.api.replace("frappe.get_doc({", ""))
        for needle in ('get_tenant_doc("Sales Message Template", template, "read")', 'get_tenant_doc("Sales Message Template", template, "write")',
                       'get_tenant_doc("Sales Template Section", section, "delete")'):
            self.assertIn(needle, self.api)

    def test_the_test_email_goes_to_the_signed_in_person_only_and_only_for_email(self):
        body = self.api.split("def send_test(")[1].split("\n@frappe.whitelist")[0]
        self.assertIn('doc.channel != "Email"', body)
        self.assertIn('frappe.db.get_value("User", frappe.session.user, "email")', body)
        self.assertIn("recipients=[recipient]", body)
        self.assertNotIn("Sales Prospect", body)

    def test_editing_an_approved_template_is_reported_and_an_autosave_can_be_unfinished(self):
        body = self.api.split("def save(")[1].split("\n@frappe.whitelist")[0]
        self.assertIn("back_to_draft", body)
        self.assertIn("doc.save()", body)  # the controller returns it to draft and checks the content

    def test_the_library_gives_the_screen_what_it_needs(self):
        body = self.api.split("def library(")[1].split("\n@frappe.whitelist")[0]
        for key in ('"fields"', '"starters"', '"sections"', '"palette"', '"new_blocks"', '"limits"', '"ai"', '"has_address"', '"can_manage"'):
            self.assertIn(key, body)


class ScreenTests(unittest.TestCase):
    script = (PAGE / "sales_templates.js").read_text(encoding="utf-8")
    css = (PAGE / "sales_templates.css").read_text(encoding="utf-8")

    def test_the_three_panes_and_their_tabs(self):
        for needle in ('class="tb-left"', 'class="tb-main"', 'class="tb-right"', '["blocks", __("Blocks")]', '["fields", __("Fields")]',
                       '["starters", __("Templates")]'):
            self.assertIn(needle, self.script)

    def test_all_ten_blocks_are_offered(self):
        for kind in builder.PALETTE:
            self.assertIn(f"{kind}:", self.script.split("const GLYPH")[1].split("};")[0], kind)
            self.assertIn(f"{kind}: () =>", self.script.split("const forms = {")[1].split("return `<div class=\"tb-blockeditor\"")[0])

    def test_every_channel_has_its_editor(self):
        for needle in ("paint_email()", "paint_sms_form()", "paint_wa_form()", "paint_li_form()"):
            self.assertIn(needle, self.script)

    def test_the_ai_panel_the_actions_and_the_checks(self):
        for needle in ("What should this message achieve?", "Draft with AI", "TONES", "Agent actions on send", "Pre-send checks",
                       "Subject lines · A/B test", 'API + "ai_draft"', 'API + "ai_edit"', "Undo the last AI change"):
            self.assertIn(needle, self.script)

    def test_actions_that_do_not_work_yet_are_not_switches(self):
        for key in ("besttime", "followup"):
            self.assertRegex(self.script, rf'\["{key}", [^\]]*false,')
        self.assertEqual(template_content.ACTIONS_AVAILABLE, ("personalize",))

    def test_it_autosaves_checks_as_you_type_and_returns_to_draft_after_an_approved_edit(self):
        for needle in ("setTimeout(() => this.check(), 350)", "setTimeout(() => this.save(false), 4000)", "if (seq !== this.seq) return",
                       "back_to_draft", "Changed after approval: approve it again"):
            self.assertIn(needle, self.script)

    def test_blocks_can_be_dragged_and_reordered(self):
        for needle in ('draggable="true"', "dragstart", '"dragover"', ".on(\"drop\"", "rsa-block:", "move_block(", "Save as section"):
            self.assertIn(needle, self.script)

    def test_a_template_opens_by_route_and_the_campaign_wizard_can_pick_it_up(self):
        self.assertIn('frappe.set_route("sales-templates", n)', self.script)
        self.assertIn('localStorage.setItem("cst_use_template", name)', self.script)
        studio = (STUDIO / "campaign_studio.js").read_text(encoding="utf-8")
        self.assertIn('store.get("cst_use_template"', studio)
        self.assertIn('frappe.set_route("sales-templates"', studio)

    def test_the_preview_is_sandboxed(self):
        self.assertIn('<iframe sandbox=""', self.script)

    def test_the_page_has_the_builder_layout_and_stacks_on_small_screens(self):
        for needle in (".tb-work { display: grid; grid-template-columns: minmax(230px, 270px) minmax(0, 1fr) minmax(290px, 340px)",
                       ".tb-phone", ".tb-tag", "@media (max-width: 1150px)", "--tb-navy: #121733"):
            self.assertIn(needle, self.css)

    def test_the_old_email_health_column_is_gone(self):
        self.assertNotIn("stp-side", self.script + self.css)
        self.assertNotIn("render_health", self.script)


class WizardTests(unittest.TestCase):
    script = (STUDIO / "campaign_studio.js").read_text(encoding="utf-8")

    def test_the_four_steps(self):
        for label in ('__("Setup")', '__("Audience")', '__("Content")', '__("Schedule & review")'):
            self.assertIn(label, self.script)
        for method in ("wz_setup()", "wz_audience_step()", "wz_content()", "wz_review()"):
            self.assertIn(method, self.script)

    def test_creating_never_sends_and_can_submit_for_approval(self):
        self.assertIn("does not send anything", self.script)
        self.assertIn("Create and submit for approval", self.script)
        api = read("api_campaign_studio.py").split("def create_campaign(")[1].split("\n@frappe.whitelist")[0]
        self.assertIn("submit_campaign(doc.name)", api)
        self.assertIn('"status": "Draft"', api)

    def test_the_wizard_restores_unfinished_work_and_returns_from_the_audience_dialog(self):
        self.assertIn('store.get("cst_wizard"', self.script)
        self.assertIn("audience_dialog(existing, after)", self.script)
        self.assertIn("if (after) after(saved);", self.script)

    def test_a_pilot_is_off_by_default_because_it_holds_people_back(self):
        self.assertIn("pilot: false", self.script)

    def test_templates_show_their_pre_send_checks_in_the_wizard(self):
        self.assertIn("pre-send checks open", self.script)
        self.assertIn('"reckon_sales_agent.api_templates.get"', self.script)

    def test_ab_results_are_shown_per_subject(self):
        self.assertIn("ab_card(d, en)", self.script)
        api = read("api_campaign_studio.py")
        self.assertIn('"variants": variants.parse(s.get("subject_variants"))', api)


class LiveFindingTests(unittest.TestCase):
    """Found testing the rebuilt builder on the live site."""

    def test_the_crm_composer_never_receives_the_rules_of_a_dynamic_block(self):
        block = builder._dynamic({"type": "dynamic", "fallback": "Everyone else", "rules": [
            {"field": "industry", "op": "contains", "value": "pharma", "text": "Only for pharma"}]})
        body = f'<div {t.BUILDER_MARK} style="x">{block}</div>'
        out = t.fallback_only(body)
        self.assertIn("Everyone else", out)
        self.assertNotIn("data-rsa-dynamic", out)
        self.assertNotIn("Only for pharma", out)
        self.assertIn(t.BUILDER_MARK, out)  # still builder HTML

    def test_publishing_to_the_crm_uses_the_fallback_only(self):
        body = read("agents", "templates.py").split("def _publish_email(")[1].split("\ndef ")[0]
        self.assertIn("fallback_only(doc.body) if is_builder_html(doc.body)", body)

    def test_a_sample_never_ends_in_a_full_stop_that_a_sentence_then_doubles(self):
        for field in t.FIELDS:
            self.assertFalse(field[3].endswith(".") and field[1] != "personal_line", field[1])
        self.assertEqual(t.render("{{company}}.", {}), ".")  # fields are filled from real data, never the samples
        self.assertNotIn("..", t.render("from {{company}}. Thanks", t.sample_values()))

    def test_the_image_header_message_reads_correctly(self):
        self.assertTrue(any(i.startswith("An image header") for i in builder.check_whatsapp("", "Body.", "", [], "Image")))
        self.assertTrue(any(i.startswith("A document header") for i in builder.check_whatsapp("", "Body.", "", [], "Document")))


if __name__ == "__main__":
    unittest.main()

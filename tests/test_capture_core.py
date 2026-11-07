"""Tags, segments, capture forms, CSV import and the automation flow: the pure rules."""

import unittest

from reckon_sales_agent.automation import flow as fl
from reckon_sales_agent.campaigns import capture, importer, segments, tags


class TagTests(unittest.TestCase):
    def test_clean_and_normalize(self):
        self.assertEqual(tags.clean("  VIP Customer!! "), "vip customer")
        self.assertEqual(tags.normalize("a, B ,a\nc"), ["a", "b", "c"])
        self.assertEqual(tags.normalize(["x", "X", ""]), ["x"])
        self.assertEqual(tags.clean("x" * 80), "x" * 40)
        self.assertEqual(len(tags.normalize([f"t{i}" for i in range(80)])), 30)

    def test_add_remove_has(self):
        self.assertEqual(tags.add("a, b", "b, c"), ["a", "b", "c"])
        self.assertEqual(tags.remove("a, b, c", "B"), ["a", "c"])
        self.assertTrue(tags.has("a, b", " A "))
        self.assertFalse(tags.has("a, b", ""))

    def test_bangla_tags_are_kept(self):
        self.assertEqual(tags.clean("নতুন গ্রাহক"), "নতুন গ্রাহক")


class SegmentTests(unittest.TestCase):
    PERSON = {"joined_days": 10, "last_opened_days": 3, "last_clicked_days": None, "last_replied_days": None,
              "last_sent_days": 5, "tags": ["vip"], "city": "Dhaka", "industry": "Food distribution", "source": "form:news",
              "fit_score": 72, "email": "a@b.co", "phone": "", "sms_consent": False, "whatsapp_consent": False,
              "confirmed": True, "temperature": "Warm"}

    def ok(self, field, op, value=""):
        cond, why = segments.clean_condition({"field": field, "op": op, "value": value})
        self.assertIsNotNone(cond, why)
        return segments.condition_matches(self.PERSON, cond)

    def test_dates_and_events(self):
        self.assertTrue(self.ok("joined", "within", 30))
        self.assertFalse(self.ok("joined", "within", 5))
        self.assertTrue(self.ok("joined", "before", 5))
        self.assertTrue(self.ok("opened", "within", 7))
        self.assertFalse(self.ok("opened", "not_within", 7))
        self.assertTrue(self.ok("clicked", "never"))
        self.assertTrue(self.ok("clicked", "not_within", 14))
        self.assertFalse(self.ok("replied", "within", 30))

    def test_text_tags_numbers_flags(self):
        self.assertTrue(self.ok("tag", "has", "VIP"))
        self.assertTrue(self.ok("tag", "not_has", "cold"))
        self.assertTrue(self.ok("city", "is", "dhaka"))
        self.assertTrue(self.ok("industry", "contains", "food"))
        self.assertTrue(self.ok("fit_score", "at_least", 70))
        self.assertTrue(self.ok("has_email", "yes"))
        self.assertTrue(self.ok("has_phone", "no"))
        self.assertTrue(self.ok("sms_consent", "no"))
        self.assertTrue(self.ok("confirmed", "yes"))
        self.assertTrue(self.ok("temperature", "is", "Warm"))

    def test_an_unconfirmed_person_does_not_match_confirmed(self):
        cond, _ = segments.clean_condition({"field": "confirmed", "op": "yes"})
        self.assertFalse(segments.condition_matches({**self.PERSON, "confirmed": False}, cond))

    def test_all_any_and_empty(self):
        a, _ = segments.clean_condition({"field": "city", "op": "is", "value": "Dhaka"})
        b, _ = segments.clean_condition({"field": "city", "op": "is", "value": "Chattogram"})
        self.assertFalse(segments.matches(self.PERSON, [a, b], segments.ALL))
        self.assertTrue(segments.matches(self.PERSON, [a, b], segments.ANY))
        self.assertFalse(segments.matches(self.PERSON, [], segments.ALL))  # no rules: nobody

    def test_bad_conditions_are_refused_with_a_reason(self):
        good, problems = segments.clean_conditions([
            {"field": "nope"}, {"field": "opened", "op": "within", "value": "abc"}, {"field": "fit_score", "op": "at_least", "value": 500},
            {"field": "tag", "op": "has", "value": "  "}, {"field": "temperature", "op": "is", "value": "Lukewarm"},
            {"field": "city", "op": "is", "value": "Dhaka"}])
        self.assertEqual(len(good), 1)
        self.assertEqual(len(problems), 5)
        self.assertTrue(all(p.startswith("Rule ") for p in problems))

    def test_summary_reads_as_a_sentence(self):
        conds, _ = segments.clean_conditions([{"field": "opened", "op": "within", "value": 30}, {"field": "tag", "op": "has", "value": "vip"}])
        self.assertEqual(segments.summary(conds), "Opened an email in the last 30 days and Tag has vip")
        self.assertEqual(segments.summary(conds, segments.ANY), "Opened an email in the last 30 days or Tag has vip")
        self.assertEqual(segments.summary([]), "No rules yet")

    def test_catalog_is_complete(self):
        keys = {c["key"] for c in segments.catalog()}
        self.assertEqual(keys, set(segments.CONDITIONS))
        self.assertTrue(all(c["ops"] for c in segments.catalog()))


class CaptureTests(unittest.TestCase):
    def test_email_is_always_first_and_required(self):
        fields = capture.clean_fields([{"key": "first_name"}, {"key": "bogus"}, {"key": "email", "label": "Your email"}])
        self.assertEqual([f["key"] for f in fields], ["email", "first_name"])
        self.assertTrue(fields[0]["required"])
        self.assertEqual(fields[0]["label"], "Your email")
        self.assertEqual(capture.clean_fields([])[0]["key"], "email")

    def test_a_good_submission(self):
        clean, errors = capture.validate_submission(
            [{"key": "email"}, {"key": "first_name", "required": True}, {"key": "phone"}],
            {"email": " Rahim@Example.COM ", "first_name": "  Rahim ", "phone": "01712345678", "consent": "on",
             "sms_opt_in": "1"}, ask_sms=True)
        self.assertEqual(errors, {})
        self.assertEqual(clean["email"], "rahim@example.com")
        self.assertEqual(clean["first_name"], "Rahim")
        self.assertTrue(clean["phone"].endswith("1712345678"))
        self.assertTrue(clean["sms_opt_in"])
        self.assertFalse(clean["whatsapp_opt_in"])

    def test_problems_are_reported_per_field(self):
        _clean, errors = capture.validate_submission([{"key": "email"}, {"key": "first_name", "required": True}],
                                                    {"email": "not-an-email", "consent": ""})
        self.assertEqual(set(errors), {"email", "first_name", "consent"})

    def test_consent_can_be_optional_for_a_form_that_says_so(self):
        _clean, errors = capture.validate_submission([{"key": "email"}], {"email": "a@b.co"}, require_consent=False)
        self.assertEqual(errors, {})

    def test_sms_opt_in_needs_a_phone_and_a_form_that_asks(self):
        clean, _ = capture.validate_submission([{"key": "email"}], {"email": "a@b.co", "consent": "1", "sms_opt_in": "1"}, ask_sms=True)
        self.assertFalse(clean["sms_opt_in"])
        clean, _ = capture.validate_submission([{"key": "email"}, {"key": "phone"}],
                                               {"email": "a@b.co", "phone": "01712345678", "consent": "1", "sms_opt_in": "1"})
        self.assertFalse(clean["sms_opt_in"])  # the form never asked

    def test_the_hidden_field_marks_a_bot(self):
        clean, errors = capture.validate_submission([{"key": "email"}], {"email": "a@b.co", capture.HONEYPOT: "http://spam"})
        self.assertEqual((clean, errors), ({"bot": True}, {}))

    def test_values_are_length_limited(self):
        _clean, errors = capture.validate_submission([{"key": "email"}, {"key": "first_name"}],
                                                    {"email": "a@b.co", "first_name": "x" * 200, "consent": "1"})
        self.assertIn("first_name", errors)

    def test_accent_redirect_and_rate(self):
        self.assertEqual(capture.accent("#112233"), "#112233")
        self.assertEqual(capture.accent("red; background:url(x)"), capture.DEFAULT_ACCENT)
        self.assertEqual(capture.safe_redirect("https://example.com/thanks"), "https://example.com/thanks")
        self.assertEqual(capture.safe_redirect("javascript:alert(1)"), "")
        self.assertEqual(capture.safe_redirect("http://example.com"), "")
        self.assertEqual(capture.safe_redirect('https://a.com/"x'), "")
        self.assertTrue(capture.rate_limited(30))
        self.assertFalse(capture.rate_limited(29))

    def test_the_consent_record_names_the_form(self):
        self.assertIn("news", capture.consent_source("Newsletter", "news", "2026-11-07"))


class ImportTests(unittest.TestCase):
    CSV = "Name,E-mail,Mobile,Company,Tags\nRahim,rahim@a.co,01712345678,Acme,\"vip, news\"\nBad,,,,\nKarim,not-mail,,,\n"

    def test_parse_and_map(self):
        headers, rows = importer.parse_csv(self.CSV)
        self.assertEqual(headers, ["Name", "E-mail", "Mobile", "Company", "Tags"])
        self.assertEqual(len(rows), 3)
        self.assertEqual(importer.suggest_mapping(headers), ["contact_name", "email", "phone", "business_name", "tags"])

    def test_semicolon_tab_and_bom(self):
        headers, rows = importer.parse_csv("﻿email;name\na@b.co;A\n")
        self.assertEqual((headers, rows), (["email", "name"], [["a@b.co", "A"]]))
        self.assertEqual(importer.parse_csv("email\tname\na@b.co\tA\n")[0], ["email", "name"])

    def test_rows_are_cleaned_or_skipped_with_a_reason(self):
        headers, rows = importer.parse_csv(self.CSV)
        mapping = importer.suggest_mapping(headers)
        person, why = importer.clean_row(rows[0], mapping)
        self.assertEqual(why, "")
        self.assertEqual(person["email"], "rahim@a.co")
        self.assertEqual(person["tags"], ["vip", "news"])
        self.assertEqual(importer.clean_row(rows[1], mapping), (None, "No email or phone"))
        self.assertEqual(importer.clean_row(rows[2], mapping), (None, "Invalid email address"))

    def test_first_and_last_name_make_the_name(self):
        person, _ = importer.clean_row(["a@b.co", "Ada", "Lovelace"], ["email", "first_name", "last_name"])
        self.assertEqual(person["contact_name"], "Ada Lovelace")

    def test_a_field_is_suggested_for_one_column_only(self):
        self.assertEqual(importer.suggest_mapping(["email", "e-mail", "mail"]), ["email", "", ""])

    def test_mapping_checks(self):
        self.assertIn("email or the phone", importer.validate_mapping(["contact_name", ""]))
        self.assertEqual(importer.validate_mapping(["email", "contact_name"]), "")
        self.assertIn("one column", importer.validate_mapping(["email", "email"]))
        self.assertIn("not a person field", importer.validate_mapping(["email", "role"]))

    def test_file_limits(self):
        with self.assertRaises(ValueError):
            importer.parse_csv("email\n")
        with self.assertRaises(ValueError):
            importer.parse_csv("email\n" + "a@b.co\n" * (importer.MAX_ROWS + 1))

    def test_repeats_are_merged(self):
        people, repeats = importer.dedupe_rows([
            {"email": "a@b.co", "phone": "", "contact_name": "", "business_name": "", "city": "", "industry": "", "tags": ["x"]},
            {"email": "a@b.co", "phone": "+8801712345678", "contact_name": "Ada", "business_name": "", "city": "", "industry": "", "tags": ["y"]}])
        self.assertEqual(repeats, 1)
        self.assertEqual(people[0]["phone"], "+8801712345678")
        self.assertEqual(people[0]["contact_name"], "Ada")
        self.assertEqual(people[0]["tags"], ["x", "y"])


def sample_flow():
    return {"start": "n1", "nodes": {
        "n1": {"type": "trigger", "config": {"event": "signup"}, "next": "n2"},
        "n2": {"type": "send", "config": {"template": "T1"}, "next": "n3"},
        "n3": {"type": "wait", "config": {"amount": 2, "unit": "days"}, "next": "n4"},
        "n4": {"type": "condition", "config": {"check": "opened", "ref": "n2", "wait_days": 3}, "yes": "n5", "no": "n6"},
        "n5": {"type": "action", "config": {"do": "add_tag", "value": "Engaged"}, "next": None},
        "n6": {"type": "send", "config": {"template": "T2"}, "next": None}}}


class FlowTests(unittest.TestCase):
    def test_a_good_flow_survives_normalize_and_has_no_issues(self):
        flow = fl.normalize(sample_flow())
        self.assertEqual(flow["nodes"]["n5"]["config"]["value"], "engaged")
        status = {"T1": ("Email", "Approved"), "T2": ("SMS", "Approved")}
        self.assertEqual(fl.issues(flow, status.get), [])

    def test_order_follows_yes_before_no(self):
        self.assertEqual(fl.order(fl.normalize(sample_flow())), ["n1", "n2", "n3", "n4", "n5", "n6"])
        self.assertEqual(fl.send_nodes(fl.normalize(sample_flow())), ["n2", "n6"])

    def test_normalize_drops_everything_unknown(self):
        raw = sample_flow()
        raw["nodes"]["n2"]["config"]["evil"] = "<script>"
        raw["nodes"]["x1"] = {"type": "shell", "config": {}}
        raw["nodes"]["n5"]["next"] = "ghost"
        raw["nodes"]["n9"] = {"type": "trigger", "config": {}}
        flow = fl.normalize(raw)
        self.assertNotIn("evil", flow["nodes"]["n2"]["config"])
        self.assertNotIn("x1", flow["nodes"])
        self.assertIsNone(flow["nodes"]["n5"]["next"])
        self.assertNotIn("n9", flow["nodes"])  # a second trigger is not allowed

    def test_garbage_becomes_an_empty_flow(self):
        for junk in (None, [], "x", {"nodes": []}, {"start": "a", "nodes": {"a": {"type": "send"}}}):
            flow = fl.normalize(junk)
            self.assertEqual(list(flow["nodes"]), ["n1"])
            self.assertEqual(flow["nodes"]["n1"]["type"], "trigger")

    def test_node_limit(self):
        nodes = {"n0": {"type": "trigger", "config": {}, "next": "n1"}}
        for i in range(1, 200):
            nodes[f"n{i}"] = {"type": "wait", "config": {}, "next": f"n{i + 1}" if i < 199 else None}
        self.assertLessEqual(len(fl.normalize({"start": "n0", "nodes": nodes})["nodes"]), fl.MAX_NODES)

    def test_wait_is_clamped(self):
        self.assertEqual(fl.clean_config("wait", {"amount": 99999, "unit": "days"})["amount"], 365)
        self.assertEqual(fl.clean_config("wait", {"amount": -4, "unit": "hours"})["amount"], 1)
        self.assertEqual(fl.clean_config("wait", {"amount": "x", "unit": "weeks"}), {"amount": 1, "unit": "days"})
        self.assertEqual(fl.wait_minutes({"amount": 2, "unit": "hours"}), 120)

    def test_issues_are_plain_and_point_at_the_step(self):
        raw = sample_flow()
        raw["nodes"]["n2"]["config"]["template"] = ""
        raw["nodes"]["n6"]["config"]["template"] = "NOPE"
        raw["nodes"]["n4"]["config"]["ref"] = "n6"
        problems = fl.issues(fl.normalize(raw), {"T1": ("Email", "Approved")}.get)
        by_node = {p["node"]: p["message"] for p in problems}
        self.assertIn("template", by_node["n2"])
        self.assertIn("does not exist", by_node["n6"])
        self.assertIn("earlier", by_node["n4"])

    def test_an_unapproved_or_wrong_channel_template_blocks(self):
        flow = fl.normalize(sample_flow())
        status = {"T1": ("Email", "Draft"), "T2": ("LinkedIn", "Approved")}
        messages = [p["message"] for p in fl.issues(flow, status.get)]
        self.assertTrue(any("not approved" in m for m in messages))
        self.assertTrue(any("Only Email" in m for m in messages))

    def test_a_flow_with_only_a_trigger_cannot_start(self):
        self.assertTrue(any("at least one step" in p["message"] for p in fl.issues(fl.new_flow())))

    def test_a_loop_is_found(self):
        raw = sample_flow()
        raw["nodes"]["n6"]["next"] = "n2"
        flow = fl.normalize(raw)
        self.assertTrue(fl.has_cycle(flow))
        self.assertTrue(any("loops" in p["message"] for p in fl.issues(flow)))

    def test_triggers_need_their_filter(self):
        flow = fl.normalize({"start": "n1", "nodes": {"n1": {"type": "trigger", "config": {"event": "tag_added"}, "next": "n2"},
                                                      "n2": {"type": "action", "config": {"do": "stop"}, "next": None}}})
        self.assertTrue(any("tag" in p["message"] for p in fl.issues(flow)))

    def test_webhooks_must_be_https(self):
        self.assertEqual(fl.clean_config("webhook", {"url": "http://x.co/h"})["url"], "")
        self.assertEqual(fl.clean_config("webhook", {"url": "https://x.co/h"})["url"], "https://x.co/h")
        self.assertEqual(fl.clean_config("webhook", {"url": "https://x.co/h y"})["url"], "")

    def test_the_simulator_walks_both_ways(self):
        flow = fl.normalize(sample_flow())
        yes = fl.walk(flow, {"n4": True})
        self.assertEqual([s["node"] for s in yes], ["n1", "n2", "n3", "n4", "n5"])
        self.assertEqual(yes[-1]["after_minutes"], 2 * 1440)
        no = fl.walk(flow, {"n4": False})
        self.assertEqual([s["node"] for s in no][-1], "n6")
        self.assertEqual(no[-1]["after_minutes"], 5 * 1440)  # the 2 day wait plus the 3 day window

    def test_stop_ends_the_walk(self):
        flow = fl.normalize({"start": "n1", "nodes": {"n1": {"type": "trigger", "config": {}, "next": "n2"},
                                                     "n2": {"type": "action", "config": {"do": "stop"}, "next": "n3"},
                                                     "n3": {"type": "wait", "config": {}, "next": None}}})
        self.assertEqual([s["node"] for s in fl.walk(flow)], ["n1", "n2"])

    def test_descriptions(self):
        flow = fl.normalize(sample_flow())
        self.assertEqual(fl.describe(flow["nodes"]["n3"]), "Wait 2 days")
        self.assertEqual(fl.describe(flow["nodes"]["n4"]), "If they opened the email, deciding after 3 days")
        self.assertEqual(fl.describe(flow["nodes"]["n5"]), "Add a tag: engaged")
        self.assertEqual(fl.duration_text(0), "now")
        self.assertEqual(fl.duration_text(90), "1.5 hours")
        self.assertEqual(fl.duration_text(2880), "2 days")


if __name__ == "__main__":
    unittest.main()

"""Address checking, the public API, outgoing webhooks and the MCP endpoint."""

import json
import re
import unittest
from pathlib import Path

from reckon_sales_agent import constants
from reckon_sales_agent.campaigns import segments, verify
from reckon_sales_agent.campaigns import webhook_events as hooks

ROOT = Path(__file__).resolve().parents[1] / "reckon_sales_agent"


def read(*parts):
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def whitelisted(source):
    return set(re.findall(r"@frappe\.whitelist\([^)]*\)\s*\ndef (\w+)\(", source))


class VerifyTests(unittest.TestCase):
    def test_a_good_address_with_a_mail_server_is_valid(self):
        self.assertEqual(verify.check("rahim@acmefoods.com", True)["status"], "Valid")

    def test_bad_syntax_and_reserved_domains_are_invalid(self):
        for email in ("not-an-email", "a@b", "a b@c.com", "x@@y.com", "a..b@c.com", ""):
            self.assertEqual(verify.check(email, True)["status"], "Invalid", email)
        for email in ("x@example.com", "x@mail.test", "x@site.invalid", "x@localhost"):
            self.assertEqual(verify.check(email, True)["status"], "Invalid", email)

    def test_a_domain_with_no_mail_server_is_invalid_and_unknown_is_undecided(self):
        self.assertEqual(verify.check("a@nodomainhere.com", False)["status"], "Invalid")
        undecided = verify.check("a@acmefoods.com", None)
        self.assertEqual(undecided["status"], "")  # a network hiccup never marks a good address
        self.assertIn("could not be checked", undecided["reason"])

    def test_risky_addresses_say_why(self):
        self.assertIn("disposable", verify.check("a@mailinator.com", True)["reason"].lower())
        self.assertEqual(verify.check("info@acmefoods.com", True)["status"], "Risky")
        typo = verify.check("rahim@gmial.com", True)
        self.assertEqual((typo["status"], typo["suggestion"]), ("Risky", "rahim@gmail.com"))

    def test_the_worse_answer_wins_when_a_provider_is_added(self):
        valid = verify.check("rahim@acmefoods.com", True)
        self.assertEqual(verify.merge(valid, {"status": "Invalid", "reason": "No such mailbox.", "suggestion": ""})["status"], "Invalid")
        self.assertEqual(verify.merge(valid, {"status": "Valid", "reason": "", "suggestion": ""})["status"], "Valid")
        risky = verify.check("info@acmefoods.com", True)
        self.assertEqual(verify.merge(risky, {"status": "Valid", "reason": "", "suggestion": ""})["status"], "Risky")
        self.assertEqual(verify.merge(valid, None), valid)
        self.assertEqual(verify.merge({"status": "", "reason": "x", "suggestion": ""}, {"status": "Risky", "reason": "y", "suggestion": ""})["status"], "Risky")

    def test_zerobounce_answers_are_mapped(self):
        self.assertEqual(verify.zerobounce({"status": "valid"})["status"], "Valid")
        self.assertEqual(verify.zerobounce({"status": "invalid", "sub_status": "mailbox_not_found"})["status"], "Invalid")
        self.assertIn("mailbox not found", verify.zerobounce({"status": "invalid", "sub_status": "mailbox_not_found"})["reason"])
        self.assertEqual(verify.zerobounce({"status": "spamtrap"})["status"], "Invalid")
        self.assertEqual(verify.zerobounce({"status": "catch-all"})["status"], "Risky")
        self.assertEqual(verify.zerobounce({"status": "unknown"})["status"], "Risky")
        self.assertEqual(verify.zerobounce({})["status"], "")

    def test_the_bar_adds_to_one_hundred(self):
        bar = verify.breakdown({"Valid": 1, "Risky": 1, "Invalid": 1, "Unchecked": 0})
        self.assertEqual(sum(bar["percent"].values()), 100)
        self.assertEqual(bar["deliverable"], 67)
        self.assertEqual(verify.breakdown({})["total"], 0)
        self.assertEqual(verify.breakdown({"Unchecked": 5})["deliverable"], 0)

    def test_a_segment_can_use_the_check(self):
        cond, why = segments.clean_condition({"field": "email_check", "op": "is", "value": "Invalid"})
        self.assertIsNotNone(cond, why)
        self.assertTrue(segments.condition_matches({"email_status": "Invalid"}, cond))
        unchecked, _ = segments.clean_condition({"field": "email_check", "op": "is", "value": "Unchecked"})
        self.assertTrue(segments.condition_matches({"email_status": ""}, unchecked))
        self.assertFalse(segments.condition_matches({"email_status": "Valid"}, unchecked))


class VerifyWiringTests(unittest.TestCase):
    def test_an_invalid_address_is_never_emailed_by_a_campaign(self):
        channels = read("providers", "channels.py")
        email = channels.split('if channel == "Email":')[1].split('if channel in ("SMS", "WhatsApp")')[0]
        self.assertLess(email.index('email_status") == "Invalid"'), email.index("return True"))

    def test_new_people_and_imports_are_checked_in_the_background(self):
        self.assertIn("check_later(prospect)", read("campaigns", "capture_service.py"))
        self.assertIn("start_checks(job.company", read("campaigns", "import_service.py"))
        self.assertIn("verify_service.daily", read("hooks.py"))

    def test_the_provider_is_only_asked_when_the_built_in_check_passed(self):
        service = read("campaigns", "verify_service.py").split("def check_email(")[1].split("def check_prospect(")[0]
        self.assertIn("(verify.VALID, verify.RISKY)", service)

    def test_the_lookup_is_cached_and_a_failure_decides_nothing(self):
        service = read("campaigns", "verify_service.py").split("def mx_exists(")[1].split("def _provider_answer(")[0]
        self.assertIn("frappe.cache.set_value", service)
        self.assertIn("return None", service)

    def test_the_settings_and_prospect_fields_exist(self):
        def fields(folder):
            return {f["fieldname"] for f in json.loads(read("reckon_sales_agent", "doctype", folder, f"{folder}.json"))["fields"]}

        self.assertTrue({"email_status", "email_check_note", "email_checked_at"} <= fields("sales_prospect"))
        self.assertTrue({"verify_provider", "zerobounce_api_key"} <= fields("sales_agent_settings"))
        self.assertIn('"zerobounce_api_key": "secret"', read("api_channels.py"))

    def test_enqueue_names_are_not_reserved(self):
        for call in re.findall(r"frappe\.enqueue\((.*?)\)\n", read("campaigns", "verify_service.py"), re.S):
            self.assertNotRegex(call, r"\bjob_name=|\bevent=|\bnow=")


class WebhookEventTests(unittest.TestCase):
    def test_events_are_cleaned_in_catalogue_order(self):
        self.assertEqual(hooks.clean_events("opened, signup, nonsense, SIGNUP"), ["signup", "opened"])
        self.assertEqual(hooks.clean_events(["bounced", "clicked"]), ["clicked", "bounced"])
        self.assertEqual(hooks.clean_events(""), [])
        self.assertTrue(hooks.wants("signup, opened", "opened"))
        self.assertFalse(hooks.wants("signup", "opened"))

    def test_communication_events_map_to_webhook_events(self):
        self.assertEqual(hooks.FROM_COMMUNICATION["positive_reply"], "replied")
        self.assertEqual(hooks.FROM_COMMUNICATION["unsubscribed"], "unsubscribed")
        self.assertNotIn("drafted", hooks.FROM_COMMUNICATION)  # internal events are never sent out
        self.assertTrue(set(hooks.FROM_COMMUNICATION.values()) <= set(hooks.EVENTS))

    def test_signatures_verify_and_a_changed_body_does_not(self):
        body = b'{"event":"signup"}'
        signature = hooks.sign("s3cret", body)
        self.assertEqual(len(signature), 64)
        self.assertTrue(hooks.verify("s3cret", body, signature))
        self.assertFalse(hooks.verify("s3cret", body + b" ", signature))
        self.assertFalse(hooks.verify("other", body, signature))
        self.assertFalse(hooks.verify("", body, hooks.sign("", body)))

    def test_only_public_https_addresses(self):
        self.assertEqual(hooks.safe_url("https://hooks.example.com/in"), "https://hooks.example.com/in")
        for bad in ("http://x.co", "ftp://x.co", "https://x.co/a b", "https://x.co/'", "", None):
            self.assertEqual(hooks.safe_url(bad), "", bad)


class WebhookWiringTests(unittest.TestCase):
    def test_the_doctype_is_company_owned_and_well_formed(self):
        self.assertIn("Sales Webhook Subscription", constants.COMPANY_DOCTYPES)
        doc = json.loads(read("reckon_sales_agent", "doctype", "sales_webhook_subscription", "sales_webhook_subscription.json"))
        self.assertEqual(doc["field_order"], [f["fieldname"] for f in doc["fields"]])
        company = next(f for f in doc["fields"] if f["fieldname"] == "company")
        self.assertEqual((company["fieldtype"], company["options"], company["reqd"]), ("Link", "Company", 1))
        self.assertEqual(next(f for f in doc["fields"] if f["fieldname"] == "secret")["fieldtype"], "Password")

    def test_events_are_emitted_from_the_places_that_happen(self):
        self.assertIn("emit_communication(message, event_type)", read("campaigns", "engine.py"))
        capture = read("campaigns", "capture_service.py")
        self.assertIn('emit_person(form.company, "signup"', capture)
        self.assertIn('emit_person(row.company, "confirmed"', capture)
        self.assertIn('"tag_added"', read("campaigns", "tag_service.py"))
        self.assertIn('"automation_completed"', read("automation", "engine.py"))

    def test_a_delivery_never_blocks_and_is_checked_and_signed(self):
        service = read("campaigns", "webhook_service.py")
        deliver = service.split("def deliver(")[1].split("def send_test(")[0]
        self.assertIn("validate_url(url)", deliver)
        self.assertIn("allow_redirects=False", deliver)
        self.assertIn("X-Reckon-Signature", deliver)
        self.assertIn("MAX_FAILURES", deliver)
        emit = service.split("def emit(")[1].split("def person_data(")[0]
        self.assertIn("frappe.enqueue", emit)
        self.assertIn("enqueue_after_commit=True", emit)
        self.assertNotRegex(emit, r"\bevent=event")  # frappe.enqueue reserves the name "event"

    def test_the_emitters_never_raise_into_the_caller(self):
        service = read("campaigns", "webhook_service.py")
        for name in ("emit_person", "emit_communication"):
            body = service.split(f"def {name}(")[1].split("\ndef ")[0]
            self.assertIn("except Exception:", body, name)

    def test_the_secret_is_shown_once(self):
        api = read("api_developer.py")
        self.assertIn("shown = secrets.token_hex(24)", api)
        self.assertNotIn('get_password("secret"', api)  # never read back out to the page


class PublicApiTests(unittest.TestCase):
    def test_every_call_needs_a_manager_and_a_subscription(self):
        source = read("api_public.py")
        self.assertIn("if not _can_manage():", source.split("def _company(")[1].split("def _find(")[0])
        self.assertIn("assert_entitled(company)", source.split("def _company(")[1].split("def _find(")[0])
        for name in whitelisted(source):
            body = source.split(f"def {name}(")[1].split("@frappe.whitelist")[0]
            self.assertIn("_company()", body, name)

    def test_the_api_cannot_send_or_approve(self):
        source = read("api_public.py")
        for forbidden in ("send_message", "approve_message", "approve_campaign", "send_due_messages", "activate("):
            self.assertNotIn(forbidden, source)

    def test_a_new_person_needs_a_statement_of_consent(self):
        body = read("api_public.py").split("def person_upsert(")[1].split("@frappe.whitelist")[0]
        self.assertIn("len(statement) < 10", body)
        self.assertIn("consent_source=", body)

    def test_the_documented_calls_exist(self):
        implemented = whitelisted(read("api_public.py")) | {"trigger"}
        developer = read("api_developer.py")
        for _method, path, _text in re.findall(r'\["(GET|POST)", "(api_\w+\.\w+)", "([^"]*)"\]', developer):
            module, function = path.split(".")
            self.assertIn(function, whitelisted(read(f"{module}.py")) | implemented, path)


class McpTests(unittest.TestCase):
    SOURCE = read("api_mcp.py")

    def test_no_tool_can_send_approve_activate_import_or_delete(self):
        tools = self.SOURCE.split("TOOLS = {")[1].split("\n}\n")[0]
        names = re.findall(r'^    "(\w+)":', tools, re.M)
        self.assertGreaterEqual(len(names), 10)
        for name in names:
            self.assertNotRegex(name, r"send|approve|activate|import|delete|remove|launch|pause")
        for forbidden in ("approve_", "activate(", "send_", "delete_", "import_start", "enroll"):
            self.assertNotIn(forbidden, tools)

    def test_a_tool_that_changes_something_needs_a_manager(self):
        source = self.SOURCE
        self.assertIn("if not read_only and not _can_manage():", source)
        tools = source.split("TOOLS = {")[1].split("\n}\n")[0]
        for name in ("save_segment", "tag_person"):
            block = tools.split(f'"{name}":')[1].split('\n    "')[0]
            self.assertTrue(block.rstrip().rstrip(",").endswith("False)"), name)  # read_only is False

    def test_the_protocol_methods_are_handled(self):
        handle = self.SOURCE.split("def handle(")[1].split("@frappe.whitelist")[0]
        for method in ("initialize", "ping", "tools/list", "tools/call"):
            self.assertIn(f'"{method}"', handle)
        self.assertIn("-32601", handle)
        self.assertIn('startswith("notifications/")', handle)

    def test_the_endpoint_is_not_a_guest_endpoint(self):
        self.assertNotIn("allow_guest", self.SOURCE)
        self.assertIn('@frappe.whitelist(methods=["POST"])\ndef rpc(', self.SOURCE)

    def test_errors_become_tool_errors_not_crashes(self):
        call = self.SOURCE.split("def _call(")[1].split("def handle(")[0]
        self.assertIn("except Exception as exc:", call)
        self.assertIn('"isError": True', call)


class DeveloperPageTests(unittest.TestCase):
    def test_the_page_calls_only_functions_that_exist(self):
        script = read("reckon_sales_agent", "page", "capture_studio", "capture_studio.js")
        for const, module in (("V", "api_verify"), ("D", "api_developer")):
            for call in set(re.findall(rf'\b{const} \+ "(\w+)"', script)):
                self.assertIn(call, whitelisted(read(f"{module}.py")), f"{module}.{call}")

    def test_the_tabs_exist_and_addresses_follow_the_browser_domain(self):
        script = read("reckon_sales_agent", "page", "capture_studio", "capture_studio.js")
        self.assertIn('["clean", __("Clean list")]', script)
        self.assertIn('["developers", __("Developers")]', script)
        self.assertIn("window.location.origin", script.split("tab_developers()")[1])
        self.assertNotIn("reckon.tech", script)

    def test_the_email_panel_offers_address_checking(self):
        script = read("reckon_sales_agent", "page", "sales_channels", "sales_channels.js")
        self.assertIn("this.verify_section()", script)
        self.assertIn('f: "verify_provider"', script)


if __name__ == "__main__":
    unittest.main()

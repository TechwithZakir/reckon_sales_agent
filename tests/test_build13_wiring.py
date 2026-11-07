"""Lead capture, segments, import and automations: everything is registered, wired and safe by construction."""

import json
import re
import unittest
from pathlib import Path

from reckon_sales_agent import constants

ROOT = Path(__file__).resolve().parents[1] / "reckon_sales_agent"
DOCTYPES = ("Sales Capture Form", "Sales Segment", "Sales Import Job", "Sales Automation", "Sales Automation Run")


def read(*parts):
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def doctype(name):
    folder = name.lower().replace(" ", "_")
    return json.loads(read("reckon_sales_agent", "doctype", folder, f"{folder}.json"))


def functions(source):
    """Names of the whitelisted functions of an API module."""
    return set(re.findall(r"@frappe\.whitelist\([^)]*\)\s*\ndef (\w+)\(", source))


class DoctypeTests(unittest.TestCase):
    def test_every_new_doctype_is_company_owned_and_well_formed(self):
        for name in DOCTYPES:
            self.assertIn(name, constants.COMPANY_DOCTYPES, name)
            doc = doctype(name)
            self.assertEqual(doc["field_order"], [f["fieldname"] for f in doc["fields"]], name)
            company = next(f for f in doc["fields"] if f["fieldname"] == "company")
            self.assertEqual((company["fieldtype"], company["options"], company.get("reqd")), ("Link", "Company", 1), name)
            self.assertFalse(doc.get("istable"), name)

    def test_the_controllers_have_no_template_leftovers(self):
        for name in DOCTYPES:
            folder = name.lower().replace(" ", "_")
            source = read("reckon_sales_agent", "doctype", folder, f"{folder}.py")
            self.assertNotIn("CLASS", source)
            self.assertTrue(read("reckon_sales_agent", "doctype", folder, "__init__.py") == "")

    def test_a_new_form_keeps_its_key_after_the_protected_fields_are_cleared(self):
        source = read("reckon_sales_agent", "doctype", "sales_capture_form", "sales_capture_form.py")
        validate = source.split("def validate(self):")[1]
        self.assertLess(validate.index("protect_fields(self, PROTECTED)"), validate.index("self.slug = frappe.generate_hash"))

    def test_existing_doctypes_gained_what_the_build_needs(self):
        prospect = {f["fieldname"] for f in doctype("Sales Prospect")["fields"]}
        self.assertTrue({"tags", "optin_status", "optin_token", "signup_form", "signup_at", "confirmed_at"} <= prospect)
        campaign = {f["fieldname"] for f in doctype("Sales Campaign")["fields"]}
        self.assertIn("automation", campaign)
        audience = doctype("Sales Audience")
        self.assertIn("Segment", next(f for f in audience["fields"] if f["fieldname"] == "audience_type")["options"])
        self.assertIn("segment", {f["fieldname"] for f in audience["fields"]})
        for name in ("Sales Prospect", "Sales Campaign", "Sales Audience"):
            doc = doctype(name)
            self.assertEqual(doc["field_order"], [f["fieldname"] for f in doc["fields"]], name)

    def test_import_files_are_not_kept_after_the_job(self):
        source = read("campaigns", "import_service.py")
        self.assertGreaterEqual(source.count('"payload": None'), 2)  # on success and on failure


class PageTests(unittest.TestCase):
    def test_pages_are_allowed_and_registered(self):
        for page, title in (("capture-studio", "Capture Studio"), ("automation-studio", "Automation Studio")):
            self.assertIn(page, constants.ALLOWED_PAGES)
            folder = page.replace("-", "_")
            meta = json.loads(read("reckon_sales_agent", "page", folder, f"{folder}.json"))
            self.assertEqual((meta["name"], meta["title"]), (page, title))
            self.assertIn("Reckon Sales Agent User", [r["role"] for r in meta["roles"]])
            self.assertIn(f'frappe.pages["{page}"].on_page_load', read("reckon_sales_agent", "page", folder, f"{folder}.js"))

    def test_the_sidebar_links_to_them(self):
        items = json.loads(read("workspace_sidebar", "sales_agent.json"))["items"]
        links = {i.get("link_to") for i in items}
        self.assertTrue({"capture-studio", "automation-studio", "Sales Capture Form", "Sales Segment"} <= links)

    def test_every_api_a_page_calls_exists(self):
        modules = {"api_capture": read("api_capture.py"), "api_segments": read("api_segments.py"), "api_automation": read("api_automation.py")}
        pages = {
            "capture_studio": {"F": "api_capture", "S": "api_segments"},
            "automation_studio": {"API": "api_automation"},
        }
        for page, names in pages.items():
            script = read("reckon_sales_agent", "page", page, f"{page}.js")
            for const, module in names.items():
                for call in set(re.findall(rf'\b{const} \+ "(\w+)"', script)):
                    self.assertIn(call, functions(modules[module]), f"{page} calls {module}.{call}")

    def test_no_screen_hard_codes_a_domain(self):
        for page in ("capture_studio", "automation_studio"):
            script = read("reckon_sales_agent", "page", page, f"{page}.js")
            self.assertNotRegex(script, r"https?://(?!www\.example\.com)[a-z0-9.-]+\.(tech|com|net)\b")
            self.assertNotIn("reckon.tech", script)

    def test_the_form_script_only_talks_to_the_public_endpoints(self):
        script = read("public", "js", "rsa_form.js")
        guest = set(re.findall(r'@frappe\.whitelist\(allow_guest=True[^)]*\)\s*\ndef (\w+)\(', read("api_capture.py")))
        for call in set(re.findall(r'API \+ "(\w+)', script)):
            self.assertIn(call, guest, call)
        self.assertIn('credentials: "omit"', script)  # a signup never carries the visitor's cookies

    def test_the_form_script_draws_inside_a_shadow_root_and_escapes_everything(self):
        script = read("public", "js", "rsa_form.js")
        self.assertIn("attachShadow", script)
        self.assertNotIn("eval(", script)
        self.assertNotRegex(script, r"\+ cfg\.(headline|description|button|consent_text)(?!\))")  # always through esc()

    def test_campaign_studio_can_pick_a_segment_for_an_audience(self):
        script = read("reckon_sales_agent", "page", "campaign_studio", "campaign_studio.js")
        self.assertIn('"Segment"]', script)
        self.assertIn('options: "Sales Segment"', script)


class GuestEndpointTests(unittest.TestCase):
    def test_only_four_public_endpoints_and_the_signup_is_post_only(self):
        source = read("api_capture.py")
        guest = re.findall(r'@frappe\.whitelist\(allow_guest=True, methods=\[([^\]]*)\]\)\s*\ndef (\w+)\(', source)
        self.assertEqual(sorted(n for _m, n in guest), ["config", "confirm", "page", "submit"])
        self.assertEqual(dict((n, m) for m, n in guest)["submit"], '"POST"')

    def test_confirming_needs_a_post_and_a_get_only_shows_a_button(self):
        source = read("api_capture.py")
        confirm = source.split("def confirm(")[1].split("# Management")[0]
        self.assertLess(confirm.index('frappe.request.method == "POST"'), confirm.index("capture_service.confirm(token)"))
        self.assertIn('method="post"', confirm)

    def test_a_signup_is_read_from_the_request_body(self):
        """Live test: every signup was refused, because form_dict held nothing but the key."""
        source = read("api_capture.py")
        submit = source.split("def submit(")[1].split("def _page(")[0]
        self.assertIn("data = _posted()", submit)
        posted = source.split("def _posted(")[1].split("@frappe.whitelist")[0]
        self.assertIn("request.form.items()", posted)

    def test_the_company_is_decided_by_the_form_never_by_the_visitor(self):
        source = read("campaigns", "capture_service.py")
        self.assertNotIn('data.get("company")', source)
        self.assertNotIn("form_dict", source)
        self.assertIn("form.company", source)

    def test_a_visitor_cannot_learn_who_opted_out(self):
        submit = read("campaigns", "capture_service.py").split("def submit(")[1].split("def _tag_event(")[0]
        self.assertIn('if outcome in ("suppressed", "do_not_contact") or not prospect:\n        return ok', submit)

    def test_the_public_config_never_names_the_company_or_tags(self):
        config = read("campaigns", "capture_service.py").split("def public_config(")[1].split("def _hit(")[0].split("return {")[1]
        for secret in ("company", "tags", "allowed_origins"):
            self.assertNotIn(secret, config)

    def test_cors_only_for_the_origins_a_form_allows(self):
        source = read("api_capture.py").split("def _cors(")[1].split("@frappe.whitelist")[0]
        self.assertIn("allowed", source)
        self.assertIn("Access-Control-Allow-Origin", source)

    def test_a_hosted_page_and_its_short_link(self):
        self.assertIn('{"from_route": "/f/<slug>", "to_route": "f"}', read("hooks.py"))
        self.assertIn("raise frappe.Redirect", read("www", "f.py"))


class EngineWiringTests(unittest.TestCase):
    def test_the_campaign_engine_defers_to_automations(self):
        engine = read("campaigns", "engine.py")
        advance = engine.split("def _advance(")[1].split("def _require_reapproval(")[0]
        self.assertIn('campaign.get("automation")', advance)
        self.assertIn("message_sent(member)", advance)
        tick = engine.split("def run_campaign_tick(")[1]
        self.assertIn('campaign.get("automation")', tick.split("draft_due_messages(campaign)")[0])

    def test_a_reply_stops_a_sequence_unless_the_automation_says_otherwise(self):
        engine = read("campaigns", "engine.py")
        self.assertEqual(engine.count("_stops_on_reply(member)"), 3)  # the definition and its two uses
        self.assertIn("def _stops_on_reply(member)", engine)
        self.assertIn('fire(message.company, "reply_received"', engine)

    def test_an_unconfirmed_signup_is_not_reachable_by_email(self):
        channels = read("providers", "channels.py")
        self.assertIn('prospect.get("optin_status") == "Unconfirmed"', channels)

    def test_hooks_and_scheduler(self):
        hooks = read("hooks.py")
        self.assertIn('doc_events["CRM Deal"]["on_update"] = "reckon_sales_agent.automation.engine.on_deal_update"', hooks)
        self.assertIn('"1-59/5 * * * *": ["reckon_sales_agent.automation.engine.run_due"]', hooks)

    def test_a_send_step_uses_the_campaign_engines_drafting(self):
        engine = read("automation", "engine.py")
        self.assertIn("from reckon_sales_agent.campaigns.engine import draft_message", engine)
        self.assertIn('f"{run.name}:{node_id}"', engine)  # one draft per run and step, however often it is checked

    def test_switching_on_is_the_approval_and_a_change_switches_off(self):
        engine = read("automation", "engine.py")
        activate = engine.split("def activate(")[1].split("def pause(")[0]
        self.assertIn("fingerprint(campaign_payload(campaign))", activate)
        self.assertIn('"approved_by": user', activate)
        self.assertIn("fl.issues(", activate)
        api = read("api_automation.py").split("def activate(")[1].split("@frappe.whitelist")[0]
        self.assertIn("_require_approver()", api)
        self.assertIn('self.status = "Paused"', read("reckon_sales_agent", "doctype", "sales_automation", "sales_automation.py"))

    def test_runs_stop_for_people_who_opt_out_and_for_a_stopped_member(self):
        engine = read("automation", "engine.py")
        stop = engine.split("def _stop_reason(")[1].split("def _ensure_member(")[0]
        self.assertIn("is_suppressed", stop)
        self.assertIn("do_not_contact", stop)
        self.assertIn('member.status == "Stopped"', stop)

    def test_webhooks_check_the_address_and_never_follow_redirects(self):
        engine = read("automation", "engine.py").split("def _webhook(")[1].split("# Scheduled work")[0]
        self.assertIn("validate_url(url)", engine)
        self.assertIn("allow_redirects=False", engine)
        self.assertIn("X-Reckon-Signature", engine)
        self.assertIn("hmac.new(", engine)

    def test_enqueue_arguments_do_not_use_names_frappe_swallows(self):
        for name in ("automation/engine.py", "campaigns/import_service.py", "campaigns/engine.py"):
            for call in re.findall(r"frappe\.enqueue\((.*?)\)\n", read(*name.split("/")), re.S):
                self.assertNotRegex(call, r"\bjob_name=|\bevent=|\bnow=|\bis_async=")

    def test_new_audience_type_is_resolved(self):
        resolve = read("campaigns", "audience_resolve.py")
        self.assertIn("SEGMENT: _segment", resolve)

    def test_studio_list_hides_an_automations_own_campaign(self):
        self.assertIn('"automation": ["is", "not set"]', read("api_campaign_studio.py"))


if __name__ == "__main__":
    unittest.main()

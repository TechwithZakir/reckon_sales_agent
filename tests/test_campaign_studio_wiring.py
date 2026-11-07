"""Campaign Studio wiring: registration, safety guards and the page's calls into the backend (no bench)."""
import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from reckon_sales_agent import constants  # noqa: E402
from reckon_sales_agent.agents.orchestrator import ASK, plan  # noqa: E402

APP = Path(__file__).parents[1] / "reckon_sales_agent"
INNER = APP / "reckon_sales_agent"
DOCTYPES = INNER / "doctype"
PAGE = INNER / "page" / "campaign_studio"


def read(*parts) -> str:
    return Path(APP, *parts).read_text(encoding="utf-8")


def doctype(name: str) -> dict:
    folder = name.lower().replace(" ", "_")
    return json.loads((DOCTYPES / folder / f"{folder}.json").read_text(encoding="utf-8"))


class RegistrationTests(unittest.TestCase):
    def test_the_new_doctypes_are_registered_with_the_right_shape(self):
        for name in ("Sales Audience", "Sales Tracked Link"):
            self.assertIn(name, constants.COMPANY_DOCTYPES)
            company = next(f for f in doctype(name)["fields"] if f["fieldname"] == "company")
            self.assertEqual((company["fieldtype"], company["options"], company.get("reqd")), ("Link", "Company", 1))
        self.assertIn("Sales Audience Member", constants.CHILD_DOCTYPES)
        self.assertEqual(doctype("Sales Audience Member")["istable"], 1)

    def test_field_order_matches_the_fields_on_every_changed_doctype(self):
        for name in ("Sales Audience", "Sales Audience Member", "Sales Tracked Link", "Sales Campaign",
                     "Sales Campaign Member", "Sales Communication Event", "Sales Agent Settings"):
            doc = doctype(name)
            self.assertEqual([f["fieldname"] for f in doc["fields"]], doc["field_order"], name)

    def test_tracked_links_are_written_by_the_system_only(self):
        for role in doctype("Sales Tracked Link")["permissions"]:
            if role["role"].startswith("Reckon Sales Agent"):
                self.assertFalse(role.get("write") or role.get("create") or role.get("delete"), role["role"])

    def test_the_page_is_allowed_and_has_a_definition(self):
        self.assertIn("campaign-studio", constants.ALLOWED_PAGES)
        page = json.loads((PAGE / "campaign_studio.json").read_text(encoding="utf-8"))
        self.assertEqual((page["name"], page["title"]), ("campaign-studio", "Campaign Studio"))
        self.assertIn("(() => {", (PAGE / "campaign_studio.js").read_text(encoding="utf-8"))

    def test_the_sidebar_leads_with_everyday_tasks_and_keeps_the_rest_under_advanced(self):
        items = json.loads(read("workspace_sidebar", "sales_agent.json"))["items"]
        labels = [i["label"] for i in items]
        reach = labels.index("Reach out")
        advanced = labels.index("Advanced")
        self.assertEqual((items[reach]["type"], items[advanced]["type"]), ("Section Break", "Section Break"))
        self.assertLess(reach, advanced)
        inside = labels[reach + 1:advanced]
        for label in ("Campaigns", "Signup forms and lists", "Automations", "Message templates", "Results", "Do-not-contact list"):
            self.assertIn(label, inside)
        self.assertEqual(items[advanced]["keep_closed"], 1)  # the technical lists are out of the way
        self.assertEqual(len([i for i in items if i["type"] == "Link" and i["label"] == "Campaigns"]), 1)
        self.assertEqual(len(labels), len(set((i["label"], i.get("link_to")) for i in items)))
        self.assertTrue(all(i["child"] == 1 for i in items[reach + 1:] if i["type"] == "Link" and labels.index(i["label"]) > reach))

    def test_hooks_route_the_short_link_and_whatsapp_receipts(self):
        hooks = read("hooks.py")
        self.assertIn('{"from_route": "/l/<code>", "to_route": "l"}', hooks)
        self.assertIn('"on_update": "reckon_sales_agent.campaigns.engine.handle_whatsapp_status"', hooks)
        self.assertTrue((APP / "www" / "l.py").exists() and (APP / "www" / "l.html").exists())


class SettingsTests(unittest.TestCase):
    def test_autopilot_starts_off_and_tracking_starts_on(self):
        fields = {f["fieldname"]: f for f in doctype("Sales Agent Settings")["fields"]}
        self.assertEqual(fields["campaign_autopilot"]["default"], "Off")
        self.assertEqual(fields["campaign_autopilot"]["options"].split("\n"), ["Off", "Assist", "Auto-send"])
        self.assertEqual((fields["track_opens"]["default"], fields["track_clicks"]["default"]), ("1", "1"))

    def test_event_types_include_opens_clicks_and_reads(self):
        options = next(f for f in doctype("Sales Communication Event")["fields"] if f["fieldname"] == "event_type")["options"]
        for kind in ("opened", "clicked", "read", "unsubscribed", "auto_approved"):
            self.assertIn(kind, options.split("\n"))

    def test_the_counters_are_protected_and_the_audience_is_in_the_approval(self):
        self.assertIn('"open_count", "click_count"', read("reckon_sales_agent", "doctype", "sales_campaign", "sales_campaign.py"))
        self.assertIn('**({"audience": _get(campaign, "audience")} if _get(campaign, "audience") else {})',
                      read("agents", "approvals.py"))


class EngineTests(unittest.TestCase):
    engine = read("campaigns", "engine.py")

    def test_members_come_from_the_audience_and_it_must_be_the_companys_own(self):
        self.assertIn("for name, source in _candidates(campaign, filters):", self.engine)
        body = self.engine.split("def _candidates(")[1].split("\n\n\n")[0]
        self.assertIn("audience.company != campaign.company", body)
        self.assertIn("materialize(audience)", body)

    def test_autopilot_only_skips_the_click_when_the_rules_allow_it(self):
        body = self.engine.split("def draft_message(")[1].split("def _personal_line(")[0]
        self.assertIn("autopilot.may_auto_approve(", body)
        self.assertIn("auto = bool(approval and auto)", body)
        self.assertIn('"status": "Draft" if (approval and not auto) else "Approved"', body)
        self.assertIn('record_event(message, "auto_approved"', body)

    def test_tracking_changes_only_the_outgoing_copy(self):
        body = self.engine.split("def send_message(")[1].split("def _instrument(")[0]
        self.assertIn("stored_body = message.body", body)
        self.assertIn("_instrument(message, settings)", body)
        self.assertIn("message.body = stored_body", body)
        after = body.split("_instrument(message, settings)")[1]
        self.assertIn("result = send(channel, message, settings)", after)  # the swap happens before the send

    def test_a_tracking_failure_never_stops_a_message(self):
        body = self.engine.split("def _instrument(")[1].split("def _advance(")[0]
        self.assertIn("except Exception:", body)
        self.assertIn("log_error", body)

    def test_the_sending_window_waits_but_does_not_cancel_and_skips_replies(self):
        body = self.engine.split("def send_message(")[1]
        window = body.split("if not in_window(")[0][-300:]
        self.assertIn("if not is_reply:", window)
        after = body.split("if not in_window(")[1].split("\n    if _sent_today")[0]
        self.assertIn("return False", after)
        self.assertNotIn("_cancel(", after)

    def test_builder_email_html_is_used_as_it_is(self):
        self.assertIn("body = rendered if is_builder_html(rendered) else text_to_html(rendered)", self.engine)

    def test_whatsapp_receipts_become_events(self):
        body = self.engine.split("def handle_whatsapp_status(")[1].split("\ndef ")[0]
        for needle in ('"delivered": "delivered"', '"read": "read"', 'doc.get("type") != "Outgoing"',
                       'reference_doctype") != "Sales Outreach Message"'):
            self.assertIn(needle, body)


class TrackingEndpointTests(unittest.TestCase):
    def test_scanners_are_counted_apart_and_never_become_events(self):
        body = read("campaigns", "track_links.py").split("def _visit(")[1].split("def _record(")[0]
        self.assertIn("tracking.is_bot(user_agent)", body)
        self.assertIn("bot_hits", body)
        bot_branch = body.split("if tracking.is_bot(user_agent):")[1].split("now = now_datetime()")[0]
        self.assertIn("return link, None", bot_branch)

    def test_a_click_only_ever_leads_to_a_stored_http_address(self):
        body = read("campaigns", "track_links.py").split("def clicked(")[1].split("def _follow_up_if_hot(")[0]
        self.assertIn('.startswith(("http://", "https://"))', body)
        self.assertIn("return link.url", body)

    def test_hot_lead_tasks_respect_the_autopilot_level_and_happen_once(self):
        body = read("campaigns", "track_links.py").split("def _follow_up_if_hot(")[1]
        self.assertIn("creates_followup_tasks(normalize_level(", body)
        self.assertIn('f"hot_task:{message.member}"', body)
        self.assertIn('frappe.db.exists("Sales Communication Event", {"idempotency_key": key})', body)
        self.assertIn("frappe.set_user(visitor)", body)

    def test_the_pixel_endpoint_is_a_get_that_always_answers_the_same_image(self):
        source = read("api_track.py")
        self.assertIn('@frappe.whitelist(allow_guest=True, methods=["GET"])', source)
        self.assertIn("Response(tracking.GIF", source)

    def test_the_short_link_page_redirects_or_answers_404(self):
        source = read("www", "l.py")
        self.assertIn("raise frappe.DoesNotExistError", source)
        self.assertIn("frappe.local.flags.redirect_location = destination", source)
        self.assertIn("no_cache = 1", source)


class AudienceResolveTests(unittest.TestCase):
    source = read("campaigns", "audience_resolve.py")

    def test_every_query_is_limited_to_the_company(self):
        self.assertIn('filters = {"company": a.company, "review_status": "Approved", "do_not_contact": 0}', self.source)
        self.assertEqual(self.source.count('"rsa_company": a.company'), 3)  # leads, contacts, customers
        self.assertEqual(self.source.count('.get("rsa_company") == company'), 3)  # picked leads, contacts, deals
        self.assertIn("row.company == company", self.source)

    def test_new_prospects_are_approved_but_existing_ones_are_never_re_approved(self):
        create = self.source.split("def _create_prospect(")[1].split("def _apply_opt_in(")[0]
        self.assertIn('"review_status": "Approved"', create)
        self.assertNotIn("review_status", self.source.split("def _apply_opt_in(")[1].split("def materialize(")[0])

    def test_a_do_not_contact_prospect_keeps_its_status_and_gets_no_consent(self):
        body = self.source.split("def _apply_opt_in(")[1].split("def materialize(")[0]
        self.assertIn("row.do_not_contact", body)
        self.assertIn("return", body.split("row.do_not_contact")[1][:30])

    def test_audience_rows_are_checked_by_the_parent_because_frappe_skips_child_validate(self):
        # Found live: a row with no email, phone or record was saved without an error.
        controller = read("reckon_sales_agent", "doctype", "sales_audience", "sales_audience.py")
        self.assertIn("def _check_people(self):", controller)
        self.assertIn("self._check_people()", controller)
        self.assertIn("add a valid email or phone, or pick a record", controller)
        child = read("reckon_sales_agent", "doctype", "sales_audience_member", "sales_audience_member.py")
        self.assertNotIn("def validate(", child)

    def test_consent_is_only_recorded_with_the_audiences_stated_source(self):
        body = self.source.split("def _opt_in_fields(")[1].split("def _create_prospect(")[0]
        self.assertIn("a.opt_in_source", body)
        controller = read("reckon_sales_agent", "doctype", "sales_audience", "sales_audience.py")
        self.assertIn("Say how these people agreed", controller)


class ApiTests(unittest.TestCase):
    api = read("api_campaign_studio.py")

    def whitelisted(self) -> set[str]:
        return set(re.findall(r"@frappe\.whitelist\([^)]*\)\n(?:@[^\n]+\n)*def (\w+)\(", self.api))

    def test_the_page_only_calls_endpoints_that_exist(self):
        script = (PAGE / "campaign_studio.js").read_text(encoding="utf-8")
        calls = set(re.findall(r'API \+ "(\w+)"', script))
        self.assertTrue(calls)
        self.assertEqual(calls - self.whitelisted(), set())
        core = set(re.findall(r'CORE \+ "(\w+)"', script)) | set(re.findall(r'call\("(\w+)"', script))
        core_api = read("api.py")
        for name in core:
            self.assertRegex(core_api, rf"def {name}\(", name)

    def test_the_campaign_list_counts_answered_messages_not_reply_events(self):
        body = self.api.split("def campaigns(")[1].split("def _sms_parts(")[0]
        self.assertIn("count(distinct message)", body)
        self.assertIn("min(rate(replied.get(row.name, 0), sent), 100.0)", body)
        self.assertNotIn("row.reply_count", body)

    def test_every_writer_needs_a_manager(self):
        for name in ("create_campaign", "save_audience", "refresh_audience", "delete_audience", "set_autopilot"):
            body = self.api.split(f"def {name}(")[1].split("\n@frappe.whitelist")[0]
            self.assertIn("_require_manager()", body, name)

    def test_writers_are_post_only(self):
        for name in ("create_campaign", "save_audience", "refresh_audience", "delete_audience", "set_autopilot"):
            decorator = self.api.split(f"def {name}(")[0].rsplit("@frappe.whitelist", 1)[1].split("\n")[0]
            self.assertIn('methods=["POST"]', decorator, name)

    def test_records_are_loaded_with_a_permission_check(self):
        self.assertNotIn("frappe.get_doc(", self.api.replace('frappe.get_doc({', ''))
        for needle in ('get_tenant_doc("Sales Campaign", name, "read")', 'get_tenant_doc("Sales Audience", name, "read")',
                       'get_tenant_doc("Sales Prospect", prospect, "read")'):
            self.assertIn(needle, self.api)

    def test_an_audience_in_use_cannot_be_deleted(self):
        body = self.api.split("def delete_audience(")[1].split("\n@frappe.whitelist")[0]
        self.assertIn('frappe.db.exists("Sales Campaign", {"audience": doc.name})', body)

    def test_autopilot_changes_are_validated_and_logged(self):
        body = self.api.split("def set_autopilot(")[1]
        self.assertIn("autopilot.LEVELS", body)
        self.assertIn("autopilot.parse_window(window)", body)
        self.assertIn("log_activity(", body)


class PlannerTests(unittest.TestCase):
    def test_hot_recipients_become_a_step_for_a_person(self):
        steps = [s for s in plan({"hot_recipients": 3}) if s.key == "hot_recipients"]
        self.assertEqual(len(steps), 1)
        self.assertEqual((steps[0].kind, steps[0].agent), (ASK, "Engagement"))
        self.assertIn("3 people are showing real interest", steps[0].title)

    def test_one_person_reads_naturally_and_none_adds_no_step(self):
        titles = [s.title for s in plan({"hot_recipients": 1}) if s.key == "hot_recipients"]
        self.assertEqual(titles, ["1 person is showing real interest"])
        self.assertFalse([s for s in plan({"hot_recipients": 0}) if s.key == "hot_recipients"])

    def test_the_copilot_is_silent_while_autopilot_is_off(self):
        body = read("agents", "orchestrator.py").split("def _hot_recipients(")[1].split("\ndef ")[0]
        self.assertIn("creates_followup_tasks(normalize_level(", body)
        self.assertIn("return 0", body)

    def test_agent_studio_can_open_the_recipients_tab(self):
        script = read("reckon_sales_agent", "page", "sales_agent", "sales_agent.js")
        self.assertIn("ask_hot_recipients(body)", script)
        self.assertIn('frappe.set_route("campaign-studio")', script)


if __name__ == "__main__":
    unittest.main()

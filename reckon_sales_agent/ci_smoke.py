"""Smoke test on a real site (CI): ``bench --site <site> execute reckon_sales_agent.ci_smoke.run``.

It catches what the database-free unit tests cannot: a DocType that does not migrate, a field name a query uses that
does not exist, an API that fails when it runs against real tables. It creates one test Company, loads every page's
API once, and walks one conversation end to end (a website chat in, assignment, tag, status, a person's reply in
dry run). No network calls: outbound stays in dry run and the AI is off.
"""

from __future__ import annotations

import json

import frappe

COMPANY = "CI Smoke Ltd"


def _company() -> str:
    # A CI site skips ERPNext's setup wizard, whose fixtures a Company needs (e.g. Warehouse Type "Transit").
    if not frappe.db.exists("Warehouse Type", "Transit"):
        from erpnext.setup.setup_wizard.operations.install_fixtures import install

        install("Bangladesh")
        frappe.db.commit()
    if not frappe.db.exists("Company", COMPANY):
        frappe.get_doc({"doctype": "Company", "company_name": COMPANY, "abbr": "CIS", "default_currency": "BDT",
                        "country": "Bangladesh"}).insert(ignore_permissions=True)
    return COMPANY


def run() -> None:
    from reckon_sales_agent import api, api_agent_studio, api_channels, api_conversations, api_setup
    from reckon_sales_agent.agents.chat import receive_chat
    from reckon_sales_agent.constants import COMPANY_DOCTYPES
    from reckon_sales_agent.usage import get_settings

    frappe.set_user("Administrator")
    company = _company()
    frappe.form_dict["company"] = company  # the system provider acting for this Company
    settings = get_settings(company)
    settings.db_set({"outbound_enabled": 0, "ai_enabled": 0, "webchat_enabled": 1, "chat_agents": "Administrator"})
    failures = []

    def check(label, fn):
        try:
            fn()
            print(f"ok   {label}")
        except Exception as exc:  # report every failure, then fail once
            frappe.db.rollback()
            failures.append(f"{label}: {exc!r}")
            print(f"FAIL {label}: {exc!r}")

    for doctype in COMPANY_DOCTYPES:
        check(f"meta {doctype}", lambda d=doctype: frappe.get_meta(d) and frappe.db.count(d))
    check("Agent Studio state", api_agent_studio.state)
    check("Get started status", api_setup.status)
    check("Campaign Analytics", lambda: api.analytics_dashboard(30))
    check("Channels overview", api_channels.overview)
    check("Conversations list", api_conversations.threads)
    check("Integration panel save", lambda: api_channels.save_settings(
        {"calling_hours": "09:00-20:00", "sms_provider": "BulkSMSBD", "sms_api_key": ""}))

    def conversation():
        name = receive_chat(company, "Web Chat", "web", "c" * 32, "Do you deliver to Chattogram?",
                            f"web:ci:{frappe.generate_hash(length=8)}", contact_name="CI Visitor")
        prospect = frappe.db.get_value("Sales Chat Message", name, "prospect")
        thread = api_conversations.thread(prospect)
        assert thread["conversation"]["status"] == "Open", thread["conversation"]
        api_conversations.tag(prospect, "vip")
        api_conversations.set_mode(prospect, "Suggest only")
        assert "vip" in api_conversations.thread(prospect)["conversation"]["tags"]
        from reckon_sales_agent.agents.ownership import owner_for, reassign

        reassign(company, prospect, "Administrator")  # the whole lead follows its owner
        assert frappe.db.get_value("Sales Prospect", prospect, "sales_owner") == "Administrator"
        assert owner_for(prospect) == "Administrator"
        from reckon_sales_agent.agents.omni import compose

        # The CI Company has no subscription, so the approved reply waits ("Approved") instead of a dry run.
        status = compose(prospect, "Web Chat", "Yes, we deliver to Chattogram.")
        assert status in ("Dry Run", "Approved"), status
        assert api_conversations.thread(prospect)["conversation"]["ai_mode"] == "Human only"
        api_conversations.set_status(prospect, "Resolved")

    check("Conversation end to end", conversation)

    def isolation():
        # Two Companies on one site. The check runs as a real user of the other Company (not Administrator, who sees
        # everything): that user must neither list nor open a lead of the first Company.
        other = "CI Smoke Other Ltd"
        if not frappe.db.exists("Company", other):
            frappe.get_doc({"doctype": "Company", "company_name": other, "abbr": "CIO", "default_currency": "BDT",
                            "country": "Bangladesh"}).insert(ignore_permissions=True)
        get_settings(other)
        user = "ci-other-company@example.com"
        if not frappe.db.exists("User", user):
            frappe.get_doc({"doctype": "User", "email": user, "first_name": "CI Other", "send_welcome_email": 0,
                            "roles": [{"role": "Reckon Sales Agent User"}]}).insert(ignore_permissions=True)
        if not frappe.db.exists("Tenant User Assignment", {"user": user}):
            frappe.get_doc({"doctype": "Tenant User Assignment", "user": user, "company": other, "active": 1,
                            "is_default": 1}).insert(ignore_permissions=True)
        name = receive_chat(company, "Web Chat", "web", "d" * 32, "Who are you?",
                            f"web:iso:{frappe.generate_hash(length=8)}", contact_name="Isolation Visitor")
        prospect = frappe.db.get_value("Sales Chat Message", name, "prospect")
        frappe.set_user(user)
        try:
            listed = [row["prospect"] for row in api_conversations.threads()]
            assert prospect not in listed, "another Company's lead is listed"
            try:
                api_conversations.thread(prospect)
            except Exception:
                pass  # refused, as it should be
            else:
                raise AssertionError("another Company's lead opened")
        finally:
            frappe.set_user("Administrator")

    check("Companies stay separate", isolation)

    def capture_segments_automation():
        # Lead capture, segments, CSV import and an automation, end to end on real tables. The Company is made internal for
        # this check (no subscription in CI); the change is rolled back with everything else.
        from reckon_sales_agent import api_automation, api_capture, api_segments
        from reckon_sales_agent.automation import engine as auto
        from reckon_sales_agent.automation import flow as fl
        from reckon_sales_agent.campaigns import (
            capture,
            capture_service,
            import_service,
            segment_service,
        )
        from reckon_sales_agent.campaigns.audience_resolve import resolve
        from reckon_sales_agent.campaigns.tag_service import add_tags
        from reckon_sales_agent.providers.channels import reachability

        frappe.set_user("Administrator")
        frappe.form_dict["company"] = company  # the earlier check switched users, which clears the acting Company
        frappe.db.set_single_value("Sales Agent Platform Settings", "internal_companies", company)
        frappe.clear_document_cache("Sales Agent Platform Settings", "Sales Agent Platform Settings")
        tag = "ci" + frappe.generate_hash(length=5).lower()
        form = frappe.get_doc({"doctype": "Sales Capture Form", "company": company, "form_name": "CI form", "status": "Published",
                               "tags": tag, "double_opt_in": 1, "require_consent": 1,
                               "fields_json": json.dumps([{"key": "email"}, {"key": "first_name"}])}).insert(ignore_permissions=True)
        assert form.slug and len(form.slug) == 10, form.slug
        email = f"ci-{frappe.generate_hash(length=6).lower()}@example.com"
        result = capture_service.submit(form.slug, {"email": email, "first_name": "Ci", "consent": "on"}, "127.0.0.1")
        assert result["ok"], result
        row = frappe.db.get_value("Sales Prospect", {"company": company, "email": email}, ["name", "optin_status", "optin_token"], as_dict=True)
        assert row and row.optin_status == "Unconfirmed" and row.optin_token, row
        person = frappe.get_doc("Sales Prospect", row.name)
        assert not reachability("Email", person, get_settings(company))[0], "an unconfirmed signup must not be emailed"
        assert capture_service.confirm(row.optin_token), "confirmation refused"
        person.reload()
        assert person.optin_status == "Confirmed" and tag in (person.tags or ""), (person.optin_status, person.tags)
        assert reachability("Email", person, get_settings(company))[0]
        assert capture_service.submit(form.slug, {"email": "bot@example.com", capture.HONEYPOT: "spam"}, "")["ok"]
        assert not frappe.db.exists("Sales Prospect", {"company": company, "email": "bot@example.com"}), "a bot signup was recorded"
        assert not capture_service.submit(form.slug, {"email": "not-an-email"}, "")["ok"]
        assert api_capture.form(form.name)["recent"], "the signup is not listed"
        assert any(r["name"] == form.name for r in api_capture.forms())

        seg = frappe.get_doc({"doctype": "Sales Segment", "company": company, "segment_name": "CI tagged",
                              "rules": json.dumps([{"field": "tag", "op": "has", "value": tag}])}).insert(ignore_permissions=True)
        assert segment_service.refresh(seg.name) == 1, "the segment should hold the confirmed signup"
        assert segment_service.person_in(company, person.name, seg.name)
        assert api_segments.preview([{"field": "tag", "op": "has", "value": tag}], "All")["total"] == 1
        assert any(r["name"] == seg.name for r in api_segments.segment_list())
        audience = frappe.get_doc({"doctype": "Sales Audience", "company": company, "audience_name": "CI segment audience",
                                   "audience_type": "Segment", "segment": seg.name}).insert(ignore_permissions=True)
        assert len(resolve(audience)) == 1

        other = f"imp-{frappe.generate_hash(length=6).lower()}@example.com"
        job = frappe.get_doc({"doctype": "Sales Import Job", "company": company, "label": "CI import", "status": "Queued", "total": 2,
                              "payload": f"email,name,tags\n{other},Imp One,vip\nnot-an-email,Bad,\n",
                              "mapping": json.dumps(["email", "contact_name", "tags"]), "started_by": "Administrator",
                              "source_label": "ci", "consent_statement": "CI test people who agreed"}).insert(ignore_permissions=True)
        import_service.run_job(job.name)
        job.reload()
        assert job.status == "Done" and job.created == 1 and job.skipped == 1, (job.status, job.created, job.skipped, job.problems)
        assert (frappe.db.get_value("Sales Prospect", {"company": company, "email": other}, "tags") or "") == "vip"

        trigger_tag = "go" + frappe.generate_hash(length=4).lower()
        flow = {"start": "n1", "nodes": {
            "n1": {"type": "trigger", "config": {"event": "tag_added", "tag": trigger_tag}, "next": "n2"},
            "n2": {"type": "action", "config": {"do": "add_tag", "value": "ci-done"}, "next": "n3"},
            "n3": {"type": "wait", "config": {"amount": 1, "unit": "minutes"}, "next": None}}}
        flow_doc = frappe.get_doc({"doctype": "Sales Automation", "company": company, "automation_name": "CI flow",
                                   "flow": json.dumps(flow)}).insert(ignore_permissions=True)
        assert fl.issues(auto.flow_of(flow_doc), auto.template_status(company)) == []
        assert auto.activate(flow_doc, "Administrator")["status"] == "Active"
        assert not flow_doc.campaign, "a flow with no message step needs no campaign"
        add_tags(company, person.name, trigger_tag, "ci")  # the trigger: a tag is added
        run = frappe.db.get_value("Sales Automation Run", {"automation": flow_doc.name, "prospect": person.name}, "name")
        assert run, "the tag did not start the automation"
        auto.advance_run(run)
        state = frappe.get_doc("Sales Automation Run", run)
        assert state.status == "Waiting" and state.current_node == "n3", (state.status, state.current_node, state.stop_reason)
        assert "ci-done" in (frappe.db.get_value("Sales Prospect", person.name, "tags") or "")
        frappe.db.set_value("Sales Automation Run", run, "node_entered_on", frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-5))
        auto.advance_run(run)
        assert frappe.db.get_value("Sales Automation Run", run, "status") == "Completed"
        detail = api_automation.automation(flow_doc.name)
        assert detail["status"] == "Active" and detail["stats"]["total"] == 1, detail["stats"]
        assert api_automation.catalog()["triggers"]
        assert any(r["name"] == flow_doc.name for r in api_automation.automations())
        assert api_automation.simulate(flow)["path"]
        assert api_automation.check(flow)["issues"] == []
        assert api_automation.runs(flow_doc.name)

    check("Capture, segments, import and automations", capture_segments_automation)
    frappe.db.rollback()  # leave the CI site as it was (the Company stays for the next run)
    if failures:
        raise AssertionError("Smoke test failed:\n" + "\n".join(failures))
    print("Smoke test passed.")

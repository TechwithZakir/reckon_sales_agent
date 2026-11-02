"""Smoke test on a real site (CI): ``bench --site <site> execute reckon_sales_agent.ci_smoke.run``.

It catches what the database-free unit tests cannot: a DocType that does not migrate, a field name a query uses that
does not exist, an API that fails when it runs against real tables. It creates one test Company, loads every page's
API once, and walks one conversation end to end (a website chat in, assignment, tag, status, a person's reply in
dry run). No network calls: outbound stays in dry run and the AI is off.
"""

from __future__ import annotations

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
        # Two Companies on one site: a lead of one Company must not be listed or opened from the other.
        other = "CI Smoke Other Ltd"
        if not frappe.db.exists("Company", other):
            frappe.get_doc({"doctype": "Company", "company_name": other, "abbr": "CIO", "default_currency": "BDT",
                            "country": "Bangladesh"}).insert(ignore_permissions=True)
        get_settings(other)  # the other Company's own settings
        name = receive_chat(company, "Web Chat", "web", "d" * 32, "Who are you?",
                            f"web:iso:{frappe.generate_hash(length=8)}", contact_name="Isolation Visitor")
        prospect = frappe.db.get_value("Sales Chat Message", name, "prospect")
        frappe.form_dict["company"] = other
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
            frappe.form_dict["company"] = company

    check("Companies stay separate", isolation)
    frappe.db.rollback()  # leave the CI site as it was (the Company stays for the next run)
    if failures:
        raise AssertionError("Smoke test failed:\n" + "\n".join(failures))
    print("Smoke test passed.")

"""Company ownership of native CRM records (runs without a database)."""
import importlib.util
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

APP = Path(__file__).parents[1] / "reckon_sales_agent"


class TenantResolutionError(PermissionError):
    pass


class FakeDB:
    """Just enough of ``frappe.db`` over ``{doctype: {name: {field: value}}}``."""

    def __init__(self, tables):
        self.tables = tables
        self.missing_columns = set()

    def _match(self, doctype, filters):
        rows = self.tables.get(doctype, {})
        if isinstance(filters, str):
            return [filters] if filters in rows else []
        return [n for n, row in rows.items() if all(row.get(k) == v for k, v in filters.items())]

    def exists(self, doctype, filters):
        found = self._match(doctype, filters)
        return found[0] if found else None

    def get_value(self, doctype, filters, field):
        found = self._match(doctype, filters)
        if not found:
            return None
        return found[0] if field == "name" else self.tables[doctype][found[0]].get(field)

    def has_column(self, doctype, column):
        return (doctype, column) not in self.missing_columns

    def get_all(self, doctype, filters=None, pluck=None):
        return [self.tables[doctype][n].get(pluck, n) for n in self._match(doctype, filters or {})]

    def set_value(self, doctype, name, field, value, update_modified=True):
        self.tables[doctype][name][field] = value

    @staticmethod
    def escape(value):
        return f"'{value}'"


class Doc(SimpleNamespace):
    def __init__(self, doctype, name=None, new=False, **fields):
        super().__init__(doctype=doctype, name=name, _new=new, **fields)

    def get(self, field):
        return getattr(self, field, None)

    def set(self, field, value):
        setattr(self, field, value)

    def is_new(self):
        return self._new


class CRMTenancyTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeDB(
            {
                "Company": {"Acme": {"abbr": "AC"}, "Beta": {"abbr": "BT"}},
                "CRM Lead": {
                    "LEAD-A": {"rsa_company": "Acme"},
                    "LEAD-B": {"rsa_company": "Beta"},
                },
                "CRM Organization": {
                    "Globex": {"organization_name": "Globex", "rsa_company": "Beta"},
                },
                "CRM Deal": {"DEAL-B": {"rsa_company": "Beta"}},
                "FCRM Note": {"NOTE-B": {"rsa_company": "Beta"}},
                "Contact": {
                    "Ann": {"rsa_company": "Acme"},
                    "Bob": {"rsa_company": "Beta"},
                    "Sys": {},
                },
                "Contact Email": {
                    "E1": {"email_id": "x@shared.example", "parenttype": "Contact", "parent": "Bob"},
                },
                "CRM Contacts": {
                    "R1": {"contact": "Bob", "parenttype": "CRM Deal", "parent": "DEAL-B"},
                },
                "Customer": {"Shop A": {"rd_company": "Acme"}, "Shop B": {"rd_company": "Beta"}},
            }
        )
        frappe = ModuleType("frappe")
        frappe._ = lambda text: text
        frappe.PermissionError = PermissionError
        frappe.throw = Mock(side_effect=lambda msg, exc=Exception: (_ for _ in ()).throw(exc(msg)))
        frappe.session = SimpleNamespace(user="a@acme.example")
        frappe.db = self.db
        frappe.get_all = self.db.get_all
        frappe.get_installed_apps = Mock(return_value=["frappe", "crm", "reckon_saas_platform"])
        self.frappe = frappe

        self.assignments = {"a@acme.example": "Acme", "b@beta.example": "Beta"}
        security = ModuleType("reckon_saas_platform.tenant_security")
        security.TenantResolutionError = TenantResolutionError
        security.user_can_bypass_tenant = lambda user: user == "Administrator"

        def require_tenant(user):
            if user not in self.assignments:
                raise TenantResolutionError(user)
            return SimpleNamespace(user=user, company=self.assignments[user])

        security.require_tenant = require_tenant
        platform = ModuleType("reckon_saas_platform")
        platform.tenant_security = security
        self.modules = {
            "frappe": frappe,
            "reckon_saas_platform": platform,
            "reckon_saas_platform.tenant_security": security,
        }
        patcher = patch.dict(sys.modules, self.modules)
        patcher.start()
        self.addCleanup(patcher.stop)
        spec = importlib.util.spec_from_file_location(
            "reckon_sales_agent.crm_tenancy", APP / "crm_tenancy.py"
        )
        self.t = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.t)

    def as_user(self, user):
        self.frappe.session.user = user

    # List and link-search filtering

    def test_tenant_query_is_limited_to_own_company(self):
        self.assertEqual(
            self.t.get_query_conditions("a@acme.example", "CRM Lead"),
            "`tabCRM Lead`.`rsa_company` = 'Acme'",
        )

    def test_unassigned_user_sees_nothing(self):
        self.assertEqual(self.t.get_query_conditions("stray@x.example", "CRM Deal"), "1=0")

    def test_administrator_is_not_filtered(self):
        self.assertEqual(self.t.get_query_conditions("Administrator", "CRM Lead"), "")

    def test_scoping_is_off_without_saas_platform(self):
        self.frappe.get_installed_apps.return_value = ["frappe", "crm"]
        self.assertEqual(self.t.get_query_conditions("a@acme.example", "CRM Lead"), "")
        self.assertTrue(self.t.has_permission(Doc("CRM Lead", "LEAD-B"), "a@acme.example", "read"))

    # Document permission

    def test_cannot_read_other_company_record(self):
        doc = Doc("CRM Lead", "LEAD-B", rsa_company="Beta")
        self.assertFalse(self.t.has_permission(doc, "a@acme.example", "read"))
        self.assertTrue(self.t.has_permission(Doc("CRM Lead", "LEAD-A", rsa_company="Acme"),
                                              "a@acme.example", "read"))

    def test_cannot_move_own_record_to_other_company(self):
        doc = Doc("CRM Lead", "LEAD-A", rsa_company="Beta")
        self.assertFalse(self.t.has_permission(doc, "a@acme.example", "write"))

    def test_new_record_for_other_company_is_refused(self):
        self.assertFalse(self.t.has_permission(Doc("CRM Lead", new=True, rsa_company="Beta"),
                                               "a@acme.example", "create"))
        self.assertTrue(self.t.has_permission(Doc("CRM Lead", new=True), "a@acme.example", "create"))

    # Binding on insert

    def test_new_record_gets_creators_company(self):
        doc = Doc("CRM Lead", new=True)
        self.t.bind_company(doc)
        self.assertEqual(doc.rsa_company, "Acme")

    def test_tenant_cannot_create_for_other_company(self):
        with self.assertRaises(PermissionError):
            self.t.bind_company(Doc("CRM Lead", new=True, rsa_company="Beta"))

    def test_unassigned_user_cannot_create(self):
        self.as_user("stray@x.example")
        with self.assertRaises(PermissionError):
            self.t.bind_company(Doc("CRM Lead", new=True))

    def test_system_created_task_inherits_reference_company(self):
        self.as_user("Administrator")
        task = Doc("CRM Task", new=True, reference_doctype="CRM Lead", reference_docname="LEAD-B")
        self.t.bind_company(task)
        self.assertEqual(task.rsa_company, "Beta")

    def test_system_created_lead_without_parent_stays_unowned(self):
        self.as_user("Administrator")
        lead = Doc("CRM Lead", new=True)
        self.t.bind_company(lead)
        self.assertIsNone(lead.rsa_company)

    # Validation

    def test_company_is_immutable(self):
        doc = Doc("CRM Lead", "LEAD-A", rsa_company="Beta")
        with self.assertRaises(PermissionError):
            self.t.validate_company(doc)

    def test_deal_cannot_link_other_company_organization(self):
        deal = Doc("CRM Deal", new=True, rsa_company="Acme", organization="Globex")
        with self.assertRaises(PermissionError):
            self.t.validate_company(deal)

    def test_task_cannot_reference_other_company_lead(self):
        task = Doc("CRM Task", new=True, rsa_company="Acme",
                   reference_doctype="CRM Lead", reference_docname="LEAD-B")
        with self.assertRaises(PermissionError):
            self.t.validate_company(task)

    def test_same_company_links_are_valid(self):
        task = Doc("CRM Task", new=True, rsa_company="Acme",
                   reference_doctype="CRM Lead", reference_docname="LEAD-A")
        self.t.validate_company(task)

    # Organizations

    def test_organization_lookup_ignores_other_companies(self):
        self.assertIsNone(self.t.find_organization("Globex", "Acme"))
        self.assertEqual(self.t.find_organization("Globex", "Beta"), "Globex")

    def test_same_organization_name_in_second_company_gets_qualified_name(self):
        self.assertEqual(self.t.unique_organization_name("Globex", "Acme"), "Globex - AC")
        self.db.tables["CRM Organization"]["Globex - AC"] = {"rsa_company": "Acme"}
        self.assertEqual(self.t.unique_organization_name("Globex", "Acme"), "Globex - AC-2")
        self.assertEqual(self.t.unique_organization_name("Initech", "Acme"), "Initech")

    # Notes, call logs and contacts

    def test_webhook_call_log_inherits_reference_company(self):
        self.as_user("Guest")
        log = Doc("CRM Call Log", new=True, reference_doctype="CRM Deal", reference_docname="DEAL-B")
        self.t.bind_company(log)
        self.assertEqual(log.rsa_company, "Beta")

    def test_note_cannot_reference_other_company_deal(self):
        note = Doc("FCRM Note", new=True, rsa_company="Acme",
                   reference_doctype="CRM Deal", reference_docname="DEAL-B")
        with self.assertRaises(PermissionError):
            self.t.validate_company(note)

    def test_call_log_cannot_attach_other_company_note(self):
        log = Doc("CRM Call Log", new=True, rsa_company="Acme", note="NOTE-B")
        with self.assertRaises(PermissionError):
            self.t.validate_company(log)

    def test_contact_cannot_link_other_company_customer(self):
        links = [{"link_doctype": "Customer", "link_name": "Shop B"}]
        contact = Doc("Contact", new=True, rsa_company="Acme", links=links)
        with self.assertRaises(PermissionError):
            self.t.validate_company(contact)
        contact.links = [{"link_doctype": "Customer", "link_name": "Shop A"}]
        self.t.validate_company(contact)

    def test_customer_links_are_ignored_without_distribution(self):
        self.db.missing_columns.add(("Customer", "rd_company"))
        links = [{"link_doctype": "Customer", "link_name": "Shop B"}]
        self.t.validate_company(Doc("Contact", new=True, rsa_company="Acme", links=links))

    def test_system_contact_inherits_customer_company(self):
        self.as_user("Administrator")
        links = [{"link_doctype": "Customer", "link_name": "Shop A"}]
        contact = Doc("Contact", new=True, links=links)
        self.t.bind_company(contact)
        self.assertEqual(contact.rsa_company, "Acme")

    def test_existing_contact_inherits_company_of_its_deal(self):
        self.assertEqual(self.t.inherited_company(Doc("Contact", "Bob")), "Beta")

    def test_deal_cannot_add_other_company_contact(self):
        deal = Doc("CRM Deal", new=True, rsa_company="Acme", contacts=[{"contact": "Bob"}])
        with self.assertRaises(PermissionError):
            self.t.validate_company(deal)

    def test_tenant_cannot_claim_unowned_contact(self):
        deal = Doc("CRM Deal", new=True, rsa_company="Acme", contacts=[{"contact": "Sys"}])
        with self.assertRaises(PermissionError):
            self.t.validate_company(deal)
        self.assertNotIn("rsa_company", self.db.tables["Contact"]["Sys"])

    def test_system_conversion_adopts_its_new_unowned_contact(self):
        self.as_user("Administrator")
        deal = Doc("CRM Deal", new=True, rsa_company="Acme", contacts=[{"contact": "Sys"}])
        self.t.validate_company(deal)
        self.assertEqual(self.db.tables["Contact"]["Sys"]["rsa_company"], "Acme")

    def test_contact_email_lookup_is_company_scoped(self):
        self.assertIsNone(self.t.find_contact_by_email("x@shared.example", "Acme"))
        self.assertEqual(self.t.find_contact_by_email("x@shared.example", "Beta"), "Bob")


class HooksTests(unittest.TestCase):
    def test_hooks_cover_every_scoped_doctype(self):
        source = (APP / "crm_tenancy.py").read_text(encoding="utf-8")
        hooks = {}
        exec((APP / "hooks.py").read_text(encoding="utf-8"), hooks)
        for doctype in hooks["SCOPED_DOCTYPES"]:
            self.assertIn(f'"{doctype}"', source)
            self.assertIn(doctype, hooks["permission_query_conditions"])
            self.assertIn(doctype, hooks["has_permission"])
            self.assertEqual(set(hooks["doc_events"][doctype]), {"before_insert", "validate"})


if __name__ == "__main__":
    unittest.main()

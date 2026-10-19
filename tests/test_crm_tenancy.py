"""Company ownership of CRM records (runs without a database)."""
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
        self.singles = {"System Settings"}
        self.company_column = {"Sales Invoice"}

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
        if doctype in self.singles:
            raise RuntimeError(f"tab{doctype} does not exist")
        if column == "company":
            return doctype in self.company_column
        return (doctype, column) not in self.missing_columns

    def get_all(self, doctype, filters=None, pluck=None):
        return [self.tables[doctype][n].get(pluck, n) for n in self._match(doctype, filters or {})]

    def set_value(self, doctype, name, field, value, update_modified=True):
        self.tables[doctype][name][field] = value

    @staticmethod
    def escape(value):
        return f"'{value}'"


# Link structure of the DocTypes used below: links, dynamic links, child tables.
META = {
    "CRM Lead": {"links": {"source": "CRM Lead Source", "lead_owner": "User"}},
    "CRM Deal": {
        "links": {"organization": "CRM Organization", "lead": "CRM Lead"},
        "tables": {"contacts": "CRM Contacts", "products": "CRM Products"},
    },
    "CRM Contacts": {"links": {"contact": "Contact"}},
    "CRM Products": {"links": {"product_code": "CRM Product"}},
    "CRM Task": {"dynamic": {"reference_docname": "reference_doctype"}},
    "FCRM Note": {"dynamic": {"reference_docname": "reference_doctype"}},
    "CRM Call Log": {
        "links": {"note": "FCRM Note", "caller": "User"},
        "dynamic": {"reference_docname": "reference_doctype"},
    },
    "Contact": {"links": {"user": "User"}, "tables": {"links": "Dynamic Link"}},
    "Address": {"tables": {"links": "Dynamic Link"}},
    "Dynamic Link": {"dynamic": {"link_name": "link_doctype"}},
    "Comment": {"dynamic": {"reference_name": "reference_doctype"}},
    "CRM Territory": {"links": {"parent_crm_territory": "CRM Territory"}},
}


def _field(name, options):
    return SimpleNamespace(fieldname=name, options=options)


class FakeMeta:
    def __init__(self, doctype):
        spec = META.get(doctype, {})
        self._links = [_field(k, v) for k, v in spec.get("links", {}).items()]
        self._dynamic = [_field(k, v) for k, v in spec.get("dynamic", {}).items()]
        self._tables = [_field(k, v) for k, v in spec.get("tables", {}).items()]

    def get_link_fields(self):
        return self._links

    def get_dynamic_link_fields(self):
        return self._dynamic

    def get_table_fields(self):
        return self._tables


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
                "Sales Invoice": {"SINV-B": {"company": "Beta"}},
                "CRM Lead Source": {
                    "Website": {},
                    "Fair - AC": {"rsa_company": "Acme"},
                    "Fair - BT": {"rsa_company": "Beta"},
                },
                "CRM Product": {"P-A": {"rsa_company": "Acme"}, "P-B": {"rsa_company": "Beta"}},
                "File": {
                    "Home": {"is_folder": 1},
                    "F-B": {"rsa_company": "Beta", "is_folder": 0},
                },
                "Comment": {"C1": {}},
            }
        )
        frappe = ModuleType("frappe")
        frappe._ = lambda text: text
        frappe.PermissionError = PermissionError
        frappe.throw = Mock(side_effect=lambda msg, exc=Exception: (_ for _ in ()).throw(exc(msg)))
        frappe.session = SimpleNamespace(user="a@acme.example")
        frappe.db = self.db
        frappe.get_all = self.db.get_all
        frappe.get_meta = FakeMeta
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

    def test_deal_cannot_include_other_company_product(self):
        deal = Doc("CRM Deal", new=True, rsa_company="Acme", products=[{"product_code": "P-B"}])
        with self.assertRaises(PermissionError):
            self.t.validate_company(deal)

    # Organizations and naming

    def test_organization_lookup_ignores_other_companies(self):
        self.assertIsNone(self.t.find_organization("Globex", "Acme"))
        self.assertEqual(self.t.find_organization("Globex", "Beta"), "Globex")

    def test_same_name_in_second_company_gets_qualified_name(self):
        org = Doc("CRM Organization", new=True, organization_name="Globex", rsa_company="Acme")
        self.t.set_tenant_name(org)
        self.assertEqual(org.name, "Globex - AC")
        self.db.tables["CRM Organization"]["Globex - AC"] = {"rsa_company": "Acme"}
        self.t.set_tenant_name(org)
        self.assertEqual(org.name, "Globex - AC-2")
        fresh = Doc("CRM Organization", new=True, organization_name="Initech", rsa_company="Acme")
        self.t.set_tenant_name(fresh)
        self.assertEqual(fresh.name, "Initech")

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

    # Master lists

    def test_master_query_includes_shared_defaults(self):
        self.assertEqual(
            self.t.get_query_conditions("a@acme.example", "CRM Lead Source"),
            "(`tabCRM Lead Source`.`rsa_company` = 'Acme' or "
            "(ifnull(`tabCRM Lead Source`.`rsa_company`, '') = '' and 1=1))",
        )

    def test_shared_default_is_read_only_for_tenants(self):
        default = Doc("CRM Lead Source", "Website")
        self.assertTrue(self.t.has_permission(default, "a@acme.example", "read"))
        self.assertFalse(self.t.has_permission(default, "a@acme.example", "write"))
        self.assertTrue(self.t.has_permission(default, "Administrator", "write"))

    def test_tenant_master_is_private(self):
        own = Doc("CRM Lead Source", "Fair - AC", rsa_company="Acme")
        other = Doc("CRM Lead Source", "Fair - BT", rsa_company="Beta")
        self.assertTrue(self.t.has_permission(own, "a@acme.example", "write"))
        self.assertFalse(self.t.has_permission(other, "a@acme.example", "read"))

    def test_system_created_master_entry_is_shared(self):
        self.as_user("Administrator")
        source = Doc("CRM Lead Source", new=True)
        self.t.bind_company(source)
        self.assertIsNone(source.get("rsa_company"))

    def test_lead_may_use_shared_or_own_master_but_not_others(self):
        self.t.validate_company(Doc("CRM Lead", new=True, rsa_company="Acme", source="Website"))
        self.t.validate_company(Doc("CRM Lead", new=True, rsa_company="Acme", source="Fair - AC"))
        with self.assertRaises(PermissionError):
            self.t.validate_company(Doc("CRM Lead", new=True, rsa_company="Acme", source="Fair - BT"))

    def test_master_entry_does_not_confer_company(self):
        self.as_user("Administrator")
        lead = Doc("CRM Lead", new=True, source="Fair - BT")
        self.t.bind_company(lead)
        self.assertIsNone(lead.rsa_company)

    # Site configuration

    def test_site_config_is_read_only_for_tenants(self):
        settings = Doc("FCRM Settings", "FCRM Settings")
        self.assertTrue(self.t.has_config_permission(settings, "a@acme.example", "read"))
        self.assertFalse(self.t.has_config_permission(settings, "a@acme.example", "write"))
        self.assertFalse(self.t.has_config_permission(settings, "a@acme.example", "create"))
        self.assertTrue(self.t.has_config_permission(settings, "Administrator", "write"))

    # Frappe core records

    def test_file_folders_are_shared_read_only(self):
        folder = Doc("File", "Home", is_folder=1)
        self.assertTrue(self.t.has_permission(folder, "a@acme.example", "read"))
        self.assertFalse(self.t.has_permission(folder, "a@acme.example", "write"))
        self.assertFalse(self.t.has_permission(Doc("File", "F-B", rsa_company="Beta"),
                                               "a@acme.example", "read"))
        self.assertIn("is_folder = 1", self.t.get_query_conditions("a@acme.example", "File"))

    def test_system_attachment_inherits_attached_record_company(self):
        self.as_user("Administrator")
        file = Doc("File", new=True, attached_to_doctype="CRM Deal", attached_to_name="DEAL-B")
        self.t.bind_company(file)
        self.assertEqual(file.rsa_company, "Beta")

    def test_tenant_cannot_attach_file_to_other_company_record(self):
        file = Doc("File", new=True, rsa_company="Acme",
                   attached_to_doctype="CRM Lead", attached_to_name="LEAD-B")
        with self.assertRaises(PermissionError):
            self.t.validate_company(file)

    def test_comment_on_erpnext_document_follows_its_company(self):
        comment = Doc("Comment", new=True, rsa_company="Acme",
                      reference_doctype="Sales Invoice", reference_name="SINV-B")
        with self.assertRaises(PermissionError):
            self.t.validate_company(comment)
        self.as_user("Administrator")
        system = Doc("Comment", new=True, reference_doctype="Sales Invoice", reference_name="SINV-B")
        self.t.bind_company(system)
        self.assertEqual(system.rsa_company, "Beta")

    def test_record_linked_after_insert_inherits_on_save(self):
        self.as_user("Administrator")
        comment = Doc("Comment", "C1", reference_doctype="CRM Deal", reference_name="DEAL-B")
        self.t.validate_company(comment)
        self.assertEqual(comment.rsa_company, "Beta")

    def test_company_address_belongs_to_that_company(self):
        self.as_user("Administrator")
        address = Doc("Address", new=True, links=[{"link_doctype": "Company", "link_name": "Acme"}])
        self.t.bind_company(address)
        self.assertEqual(address.rsa_company, "Acme")

    def test_reference_to_single_doctype_is_not_company_owned(self):
        self.assertIsNone(self.t.get_record_company("System Settings", "System Settings"))
        comment = Doc("Comment", new=True, rsa_company="Acme",
                      reference_doctype="System Settings", reference_name="System Settings")
        self.t.validate_company(comment)

    # Hooks

    def test_hooks_match_the_tenancy_registry(self):
        sys.path.insert(0, str(APP.parent))
        self.addCleanup(sys.path.remove, str(APP.parent))
        hooks = {}
        exec((APP / "hooks.py").read_text(encoding="utf-8"), hooks)
        self.assertEqual(set(hooks["_CRM_SCOPED"]), set(self.t.SCOPED_DOCTYPES))
        self.assertEqual(set(hooks["_CRM_CONFIG"]), set(self.t.VENDOR_CONFIG_DOCTYPES))
        self.assertEqual(set(hooks["_NAMED_BY_FIELD"]), set(self.t.NAME_FIELDS))
        for doctype in self.t.SCOPED_DOCTYPES:
            self.assertTrue(hooks["permission_query_conditions"][doctype].endswith("crm_tenancy.get_query_conditions"))
            self.assertTrue(hooks["has_permission"][doctype].endswith("crm_tenancy.has_permission"))
            events = hooks["doc_events"][doctype]
            self.assertTrue(events["before_insert"].endswith("bind_company"))
            self.assertTrue(events["validate"].endswith("validate_company"))
            self.assertEqual("autoname" in events, doctype in self.t.NAME_FIELDS)
        for doctype in self.t.VENDOR_CONFIG_DOCTYPES:
            self.assertTrue(hooks["has_permission"][doctype].endswith("has_config_permission"))
        public = [k for k in hooks if not k.startswith("_") and k.isupper()]
        self.assertEqual(public, [], "hooks.py must not expose constants as hooks")


if __name__ == "__main__":
    unittest.main()

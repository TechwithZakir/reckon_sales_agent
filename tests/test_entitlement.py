"""SaaS entitlement: subscriptions, internal (vendor) companies, fail-closed behaviour."""
import importlib.util
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).parents[1]


class EntitlementTests(unittest.TestCase):
    def setUp(self):
        frappe = ModuleType("frappe")
        frappe._ = lambda text: text
        frappe.ValidationError = type("ValidationError", (Exception,), {})
        frappe.PermissionError = type("PermissionError", (Exception,), {})
        frappe.throw = Mock(side_effect=lambda msg, exc=Exception: (_ for _ in ()).throw(exc(msg)))
        frappe.log_error = Mock()
        utils = ModuleType("frappe.utils")
        utils.nowdate = lambda: "2026-10-26"
        frappe.utils = utils
        self.platform = {"internal_companies": ""}
        frappe.get_cached_doc = Mock(side_effect=lambda doctype: SimpleNamespace(get=self.platform.get))
        frappe.db = Mock()
        frappe.db.exists = Mock(return_value=True)
        frappe.get_doc = Mock(return_value=SimpleNamespace(enabled=1))
        self.active = {"Tenant Ltd": True}
        saas = ModuleType("reckon_saas_platform.saas")
        saas.is_subscription_active = Mock(side_effect=lambda company, saas_module=None: self.active.get(company, False))
        self.saas = saas
        modules = {"frappe": frappe, "frappe.utils": utils, "reckon_saas_platform": ModuleType("reckon_saas_platform"),
                   "reckon_saas_platform.saas": saas}
        patcher = patch.dict(sys.modules, modules)
        patcher.start()
        self.addCleanup(patcher.stop)
        sys.path.insert(0, str(ROOT))
        self.addCleanup(sys.path.remove, str(ROOT))
        spec = importlib.util.spec_from_file_location("reckon_sales_agent.usage", ROOT / "reckon_sales_agent" / "usage.py")
        self.usage = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.usage)

    def test_subscribed_tenant_is_entitled(self):
        self.usage.assert_entitled("Tenant Ltd")

    def test_unsubscribed_company_is_refused_with_a_hint(self):
        with self.assertRaises(self.usage.NotEntitled) as ctx:
            self.usage.assert_entitled("Reckon Technologies Ltd.")
        self.assertIn("Internal Companies", str(ctx.exception))

    def test_internal_company_needs_no_subscription(self):
        self.platform["internal_companies"] = "Other Co\n  reckon technologies ltd.  \n"
        self.usage.assert_entitled("Reckon Technologies Ltd.")
        self.saas.is_subscription_active.assert_not_called()

    def test_internal_list_is_exact_per_line(self):
        self.assertFalse(self.usage.is_internal_company("Reckon", "Reckon Technologies Ltd."))
        self.assertFalse(self.usage.is_internal_company("", "\n"))
        self.assertTrue(self.usage.is_internal_company("A Co", "B Co\nA Co"))

    def test_subscription_service_error_fails_closed(self):
        self.saas.is_subscription_active.side_effect = RuntimeError("platform down")
        with self.assertRaises(self.usage.NotEntitled):
            self.usage.assert_entitled("Tenant Ltd")


if __name__ == "__main__":
    unittest.main()

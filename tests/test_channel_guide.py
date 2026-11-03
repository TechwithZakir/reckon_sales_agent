"""AI-guided setup help: the checklist is the truth, the AI only explains it, platform help is vendor-only (no bench)."""
import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from reckon_sales_agent.agents.channel_guide import (  # noqa: E402
    FALLBACK_DETAIL,
    PLATFORM_KEYS,
    QUICK_HELP,
    REFERENCES,
    ai_guide,
    cache_key,
    rules_guide,
)

APP = Path(__file__).parents[1] / "reckon_sales_agent"


class RulesGuideTests(unittest.TestCase):
    def test_counts_and_marks_each_step(self):
        guide = rules_guide([("Account SID", True), ("Auth token", False)])
        self.assertEqual(guide["source"], "rules")
        self.assertEqual(guide["summary"], "1 of 2 steps done.")
        self.assertEqual([s["done"] for s in guide["steps"]], [True, False])
        self.assertEqual(guide["steps"][0]["detail"], "Done.")
        self.assertEqual(guide["steps"][1]["detail"], FALLBACK_DETAIL)

    def test_no_steps(self):
        self.assertEqual(rules_guide([])["summary"], "No setup steps for this integration.")


class AiGuideTests(unittest.TestCase):
    def test_ai_never_marks_a_step_done(self):
        checks = [("Account SID", True), ("Auth token", False)]
        data = {"summary": "Add the token.", "items": [
            {"item": "Account SID", "how": "Ignored, already done."},
            {"item": "Auth token", "how": "Copy it from the Twilio console."}], "watch_out": []}
        guide = ai_guide(checks, data)
        self.assertEqual(guide["source"], "ai")
        self.assertEqual(guide["steps"][0]["detail"], "Done.")
        self.assertEqual(guide["steps"][1]["detail"], "Copy it from the Twilio console.")
        self.assertFalse(guide["steps"][1]["done"])

    def test_limits_are_enforced(self):
        checks = [(f"Step {i}", False) for i in range(15)]
        data = {"summary": "x" * 500, "items": [], "watch_out": ["w"] * 5}
        guide = ai_guide(checks, data)
        self.assertEqual(len(guide["steps"]), 12)
        self.assertEqual(len(guide["watch_out"]), 3)
        self.assertLessEqual(len(guide["summary"]), 300)

    def test_bad_items_are_ignored(self):
        guide = ai_guide([("A", False)], {"items": ["not a dict", None], "watch_out": None})
        self.assertEqual(guide["steps"][0]["detail"], FALLBACK_DETAIL)
        self.assertEqual(guide["watch_out"], [])


class CacheKeyTests(unittest.TestCase):
    def test_changes_with_setup_state_and_company(self):
        before = cache_key("Acme", "twilio", [("Account SID", False)])
        after = cache_key("Acme", "twilio", [("Account SID", True)])
        other = cache_key("Other", "twilio", [("Account SID", False)])
        self.assertNotEqual(before, after)
        self.assertNotEqual(before, other)
        self.assertEqual(before, cache_key("Acme", "twilio", [("Account SID", False)]))
        self.assertTrue(before.startswith("reckon_sales_agent:guide:Acme:twilio:"))


class ReferenceTests(unittest.TestCase):
    def test_every_reference_is_https(self):
        for key, links in REFERENCES.items():
            for label, url in links:
                self.assertTrue(url.startswith("https://"), (key, label))

    def test_every_integration_has_quick_help(self):
        self.assertLessEqual(set(REFERENCES), set(QUICK_HELP))
        for key, help_ in QUICK_HELP.items():
            self.assertTrue(help_["what"], key)
            self.assertTrue(help_["steps"], key)

    def test_embedded_signup_setup_is_in_the_help(self):
        from reckon_sales_agent.agents.channel_guide import CONFIG
        meta = " ".join(CONFIG["platform_meta"])
        self.assertIn("Embedded Signup configuration", meta)
        self.assertIn("Platform Settings", meta)
        self.assertIn("Tech Provider", meta)

    def test_platform_keys_are_the_platform_tiles(self):
        self.assertTrue(PLATFORM_KEYS)
        self.assertTrue(all(key.startswith("platform_") for key in PLATFORM_KEYS))

    def test_guide_endpoint_is_vendor_only_for_platform_keys(self):
        source = (APP / "api_channels.py").read_text(encoding="utf-8")
        guide = ast.parse(source)
        body = next(n for n in guide.body if isinstance(n, ast.FunctionDef) and n.name == "guide")
        text = ast.get_source_segment(source, body)
        self.assertIn("key in PLATFORM_KEYS and not _is_vendor()", text)
        self.assertIn("build_guide(current_company(), key,", text)


if __name__ == "__main__":
    unittest.main()

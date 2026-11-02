"""The CI smoke test checks that two Companies stay separate (no bench here; CI runs it on a real site)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

SMOKE = Path(__file__).parents[1] / "reckon_sales_agent" / "ci_smoke.py"


class IsolationSmokeTests(unittest.TestCase):
    def test_smoke_test_checks_another_company_cannot_see_or_open_a_lead(self):
        source = SMOKE.read_text(encoding="utf-8")
        self.assertIn('check("Companies stay separate", isolation)', source)
        self.assertIn("another Company's lead is listed", source)
        self.assertIn("another Company's lead opened", source)


if __name__ == "__main__":
    unittest.main()

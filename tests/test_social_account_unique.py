"""One Page or Instagram account belongs to one Company (no bench): Meta routes events by account ID."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

DOCTYPE = Path(__file__).parents[1] / "reckon_sales_agent" / "reckon_sales_agent" / "doctype" / "sales_social_account"


class SocialAccountUniquenessTests(unittest.TestCase):
    def test_a_page_cannot_be_enabled_for_two_companies(self):
        source = (DOCTYPE / "sales_social_account.py").read_text(encoding="utf-8")
        validate = source.split("def validate(")[1]
        self.assertIn('if not self.enabled or not self.account_id:', validate)
        self.assertIn('"platform": self.platform, "account_id": self.account_id, "enabled": 1', validate)
        self.assertIn('filters["name"] = ["!=", self.name]', validate)  # an account does not clash with itself
        self.assertIn("already connected to another Company", validate)


if __name__ == "__main__":
    unittest.main()

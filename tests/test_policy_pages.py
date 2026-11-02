"""The public privacy policy and terms pages that the Meta app asks for (no bench)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

WWW = Path(__file__).parents[1] / "reckon_sales_agent" / "www"


class PolicyPageTests(unittest.TestCase):
    def test_both_pages_are_served_at_the_urls_meta_expects(self):
        self.assertTrue((WWW / "privacy.html").is_file())
        self.assertTrue((WWW / "terms.html").is_file())

    def test_privacy_covers_meta_data_and_deletion(self):
        page = (WWW / "privacy.html").read_text(encoding="utf-8")
        self.assertIn('id="data-deletion"', page)  # the Meta data deletion instructions anchor
        self.assertIn("Data from Meta", page)
        self.assertIn("Data deletion", page)

    def test_terms_link_to_the_privacy_policy(self):
        self.assertIn('href="/privacy"', (WWW / "terms.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

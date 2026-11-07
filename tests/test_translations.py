"""The Bangla translation file stays well-formed and keeps its placeholders."""

import csv
import re
import unittest
from pathlib import Path

CSV = Path(__file__).resolve().parents[1] / "reckon_sales_agent" / "translations" / "bn.csv"
BRACES = re.compile(r"\{[^}]*\}")


def rows():
    with open(CSV, encoding="utf-8", newline="") as fh:
        return [r for r in csv.reader(fh)]


class BanglaTranslationTests(unittest.TestCase):
    def test_every_row_has_source_and_translation(self):
        for r in rows():
            self.assertGreaterEqual(len(r), 2, r)
            self.assertTrue(r[0].strip() and r[1].strip(), r)

    def test_no_duplicate_sources(self):
        keys = [r[0] for r in rows()]
        self.assertEqual(len(keys), len(set(keys)))

    def test_placeholders_are_kept(self):
        for r in rows():
            self.assertEqual(sorted(BRACES.findall(r[0])), sorted(BRACES.findall(r[1])), r)

    def test_reasonable_coverage(self):
        self.assertGreater(len(rows()), 2000)

    def test_translations_contain_bangla(self):
        bangla = re.compile("[ঀ-৿]")
        bad = [r[0] for r in rows() if not bangla.search(r[1])]
        # a few brand or code-like values may stay in Latin script
        self.assertLess(len(bad), 40, bad[:10])


if __name__ == "__main__":
    unittest.main()

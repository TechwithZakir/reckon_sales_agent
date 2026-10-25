"""Frappe 15/16 compatibility guards over the source code (no bench needed)."""
import json
import re
import unittest
from pathlib import Path

APP = Path(__file__).parents[1] / "reckon_sales_agent"

# Frappe 16 rejects SQL functions and aliases written as strings in get_all/get_list ``fields``.
STRING_AGGREGATE = re.compile(r"""["'][^"'\n]*\b(sum|count|avg|min|max|group_concat)\s*\([^"'\n]*\)[^"'\n]*["']""", re.I)
STRING_ALIAS = re.compile(r"""fields\s*=\s*\[[^\]]*["'][a-z_]+\s+as\s+[a-z_]+["']""", re.I)


class FrappeCompatTests(unittest.TestCase):
    def test_no_sql_functions_as_field_strings(self):
        offenders = []
        for path in APP.rglob("*.py"):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if "frappe.db.sql" in line or line.lstrip().startswith("#"):
                    continue
                if STRING_AGGREGATE.search(line) and ("fields" in line or "get_all" in line or "get_list" in line):
                    offenders.append(f"{path.relative_to(APP)}:{number}: {line.strip()}")
        for path in APP.rglob("*.py"):
            for match in STRING_ALIAS.finditer(path.read_text(encoding="utf-8")):
                offenders.append(f"{path.relative_to(APP)}: {match.group(0)[:80]}")
        self.assertEqual(offenders, [], "Use frappe.qb or frappe.db.count instead:\n" + "\n".join(offenders))

    def test_numeric_db_set_values_are_never_none(self):
        # db_set skips the None -> 0 cast, and Frappe 16 numeric columns are NOT NULL.
        numeric = set()
        for path in APP.rglob("doctype/*/*.json"):
            for field in json.loads(path.read_text(encoding="utf-8")).get("fields", []):
                if field.get("fieldtype") in ("Float", "Int", "Currency", "Percent", "Check", "Rating"):
                    numeric.add(field["fieldname"])
        names = "|".join(sorted(numeric))
        pattern = re.compile(r"""["'](""" + names + r""")["']\s*:\s*([^,\n}]*\.get\([^)]*\))\s*[,}\n]""")
        offenders = []
        for path in APP.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for call in re.finditer(r"(db_set|set_value)\(\{.*?\}\)", text, re.S):
                for match in pattern.finditer(call.group(0)):
                    offenders.append(f"{path.relative_to(APP)}: {match.group(1)} = {match.group(2)}")
        self.assertEqual(offenders, [], "Add `or 0`:\n" + "\n".join(offenders))


if __name__ == "__main__":
    unittest.main()

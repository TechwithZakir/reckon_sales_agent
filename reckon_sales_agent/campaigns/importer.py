"""CSV import of people: reading the file, guessing which column is what, and cleaning each row (pure).

An import is the user's statement that these people agreed to hear from them; the service stores that statement as the
consent record. Rows without a usable email or phone are skipped and counted, never guessed at.
"""

from __future__ import annotations

import csv
import io

from reckon_sales_agent.campaigns import tags as tag_rules
from reckon_sales_agent.discovery.normalize import normalize_email, normalize_phone

MAX_ROWS = 20000
MAX_CHARS = 6_000_000
IMPORT_FIELDS = ("email", "phone", "contact_name", "first_name", "last_name", "business_name", "city", "industry", "tags")
SKIP = ""

_SYNONYMS = {
    "email": ("email", "e-mail", "email address", "mail", "emailaddress", "e mail"),
    "phone": ("phone", "mobile", "cell", "telephone", "phone number", "mobile number", "whatsapp", "contact number", "tel"),
    "contact_name": ("name", "full name", "fullname", "contact name", "contact", "person"),
    "first_name": ("first name", "firstname", "first", "given name", "fname"),
    "last_name": ("last name", "lastname", "last", "surname", "family name", "lname"),
    "business_name": ("company", "company name", "business", "business name", "organization", "organisation", "firm"),
    "city": ("city", "town", "location"),
    "industry": ("industry", "sector", "category"),
    "tags": ("tags", "tag", "labels", "groups"),
}


def parse_csv(text: str) -> tuple[list[str], list[list[str]]]:
    """(headers, rows). Comma, semicolon or tab separated; a leading byte-order mark is ignored."""
    text = (text or "").lstrip("﻿")
    if len(text) > MAX_CHARS:
        raise ValueError("The file is too large. Split it into parts of 20,000 rows or fewer.")
    sample = text[:4000]
    delimiter = max(",;\t", key=sample.count) if sample.strip() else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = [[cell.strip() for cell in row] for row in reader if any(cell.strip() for cell in row)]
    if len(rows) < 2:
        raise ValueError("The file needs a header row and at least one person.")
    if len(rows) - 1 > MAX_ROWS:
        raise ValueError("That is more than 20,000 rows. Split the file into parts.")
    return rows[0], rows[1:]


def suggest_mapping(headers: list[str]) -> list[str]:
    """For each header, the field it most likely holds ('' = leave it out). A field is suggested for one column only."""
    taken: set[str] = set()
    out = []
    for header in headers:
        key = " ".join(str(header).lower().replace("_", " ").split())
        found = next((field for field, names in _SYNONYMS.items() if key in names and field not in taken), "")
        if found:
            taken.add(found)
        out.append(found)
    return out


def clean_row(row: list[str], mapping: list[str]) -> tuple[dict | None, str]:
    """(person, '') or (None, why the row is skipped)."""
    values: dict = {}
    for index, field in enumerate(mapping):
        if field in IMPORT_FIELDS and index < len(row):
            values.setdefault(field, row[index])
    email = normalize_email(values.get("email"))
    phone = normalize_phone(values.get("phone")) if values.get("phone") else ""
    if values.get("email") and not email and not phone:
        return None, "Invalid email address"
    if not email and not phone:
        return None, "No email or phone"
    first = " ".join(str(values.get("first_name") or "").split())
    last = " ".join(str(values.get("last_name") or "").split())
    name = " ".join(str(values.get("contact_name") or "").split()) or " ".join(p for p in (first, last) if p)
    business = " ".join(str(values.get("business_name") or "").split())
    return {"email": email, "phone": phone, "contact_name": name[:140], "business_name": business[:140],
            "city": " ".join(str(values.get("city") or "").split())[:80],
            "industry": " ".join(str(values.get("industry") or "").split())[:80],
            "tags": tag_rules.normalize(values.get("tags"))}, ""


def validate_mapping(mapping: list[str]) -> str:
    """'' when usable, else what to fix. Needs an email or a phone column, and no field twice."""
    chosen = [m for m in mapping if m]
    if not any(m in ("email", "phone") for m in chosen):
        return "Choose which column holds the email or the phone number."
    if any(m not in IMPORT_FIELDS for m in chosen):
        return "A column is mapped to something that is not a person field."
    dupes = {m for m in chosen if chosen.count(m) > 1}
    return f"{', '.join(sorted(dupes))}: choose one column for each field." if dupes else ""


def dedupe_rows(people: list[dict]) -> tuple[list[dict], int]:
    """One person per email or phone; later rows fill the gaps of the first. Returns (people, how many were repeats)."""
    out: list[dict] = []
    index: dict[tuple[str, str], int] = {}
    repeats = 0
    for person in people:
        keys = [("e", person["email"])] if person.get("email") else []
        if person.get("phone"):
            keys.append(("p", person["phone"]))
        found = next((index[k] for k in keys if k in index), None)
        if found is None:
            out.append(dict(person))
            found = len(out) - 1
        else:
            repeats += 1
            base = out[found]
            for field in ("email", "phone", "contact_name", "business_name", "city", "industry"):
                if not base.get(field) and person.get(field):
                    base[field] = person[field]
            base["tags"] = tag_rules.add(base.get("tags"), person.get("tags"))
        for key in keys:
            index.setdefault(key, found)
    return out, repeats

"""CSV import on the Frappe side: start a job, and run it in the background (rules: campaigns.importer).

The person who imports states that these people agreed to hear from them; that statement is stored as each person's consent
record. People who opted out before (the suppression list) are left out, never re-added, and people marked do-not-contact are
never changed.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import now_datetime

from reckon_sales_agent.campaigns import importer, person_store
from reckon_sales_agent.campaigns import tags as tag_rules
from reckon_sales_agent.campaigns.tag_service import add_tags

PROBLEM_SAMPLE = 50
PROGRESS_EVERY = 200


def preview(csv_text: str) -> dict:
    try:
        headers, rows = importer.parse_csv(csv_text)
    except ValueError as exc:
        frappe.throw(str(exc))
    return {"headers": headers, "mapping": importer.suggest_mapping(headers), "total": len(rows), "sample": rows[:5],
            "fields": list(importer.IMPORT_FIELDS)}


def start(company: str, user: str, csv_text: str, mapping: list[str], label: str, tags: str, source_label: str,
          consent_statement: str, file_name: str = "") -> str:
    """Queue an import. The consent statement is required: it is the record of how these people agreed."""
    statement = " ".join(str(consent_statement or "").split())
    if len(statement) < 10:
        frappe.throw(_("Say how these people agreed to hear from you (for example: customers who asked for our newsletter)."))
    try:
        headers, rows = importer.parse_csv(csv_text)
    except ValueError as exc:
        frappe.throw(str(exc))
    mapping = [m if m in importer.IMPORT_FIELDS else "" for m in (mapping or [])][:len(headers)]
    mapping += [""] * (len(headers) - len(mapping))
    problem = importer.validate_mapping(mapping)
    if problem:
        frappe.throw(problem)
    job = frappe.get_doc({
        "doctype": "Sales Import Job", "company": company, "label": " ".join(str(label or file_name or "Import").split())[:140],
        "status": "Queued", "file_name": (file_name or "")[:140], "tags": tag_rules.to_text(tags) or None,
        "source_label": " ".join(str(source_label or "").split())[:100] or "csv", "consent_statement": statement[:500],
        "total": len(rows), "started_by": user, "started_on": now_datetime(), "payload": csv_text, "mapping": json.dumps(mapping),
    }).insert(ignore_permissions=True)
    frappe.db.commit()
    frappe.enqueue("reckon_sales_agent.campaigns.import_service.run_job", queue="long", timeout=1800, import_job=job.name)
    return job.name


def run_job(import_job: str) -> None:
    job = frappe.get_doc("Sales Import Job", import_job)
    if job.status not in ("Queued", "Running"):
        return
    job.db_set("status", "Running")
    counts = {"created": 0, "updated": 0, "skipped": 0, "suppressed": 0, "processed": 0}
    problems: list[dict] = []
    try:
        headers, rows = importer.parse_csv(job.payload)
        mapping = json.loads(job.mapping or "[]")
        people, skipped = [], []
        for number, row in enumerate(rows, start=2):  # row 1 is the header
            person, why = importer.clean_row(row, mapping)
            if person:
                people.append(person)
            else:
                skipped.append({"row": number, "reason": why})
        people, repeats = importer.dedupe_rows(people)
        counts["skipped"] = len(skipped)
        problems = skipped[:PROBLEM_SAMPLE]
        source = f"import:{job.source_label}"
        for person in people:
            prospect, outcome = person_store.upsert(job.company, person, source_type=source,
                                                    consent_source=f"Imported: {job.consent_statement} (by {job.started_by})")
            counts["processed"] += 1
            if outcome == "suppressed":
                counts["suppressed"] += 1
                continue
            counts["created" if outcome == "created" else "updated"] += 1
            if outcome != "do_not_contact":  # tags are added one by one, so an automation that starts on a tag hears about each
                add_tags(job.company, prospect, person["tags"] + tag_rules.normalize(job.tags), source)
            if counts["processed"] % PROGRESS_EVERY == 0:
                job.db_set({**counts, "repeats": repeats})
                frappe.db.commit()
        job.db_set({**counts, "repeats": repeats, "status": "Done", "finished_on": now_datetime(),
                    "problems": json.dumps(problems), "payload": None})
        from reckon_sales_agent.campaigns.verify_service import start as start_checks

        start_checks(job.company, "unchecked")  # the new addresses are checked in the background
    except Exception:
        frappe.db.rollback()
        frappe.log_error(title="Sales Agent import failed", reference_doctype="Sales Import Job", reference_name=import_job)
        job.db_set({**counts, "status": "Failed", "finished_on": now_datetime(), "payload": None})
    frappe.db.commit()


def status(job_name: str) -> dict:
    job = frappe.get_doc("Sales Import Job", job_name)
    return {"name": job.name, "status": job.status, "total": job.total, "processed": job.processed, "created": job.created,
            "updated": job.updated, "skipped": job.skipped, "repeats": job.repeats, "suppressed": job.suppressed,
            "problems": json.loads(job.problems or "[]"), "label": job.label}

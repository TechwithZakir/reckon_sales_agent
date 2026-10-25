"""When is a scheduled discovery campaign due? (pure: no Frappe imports)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

SCHEDULES = ("Daily", "Weekly", "Monthly")


def parse_time(value) -> time | None:
    if value in (None, ""):
        return None
    if isinstance(value, time):
        return value
    if isinstance(value, timedelta):  # Frappe returns Time fields as timedelta
        seconds = int(value.total_seconds()) % 86400
        return time(seconds // 3600, (seconds % 3600) // 60)
    parts = str(value).split(":")
    return time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)


def parse_date(value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def is_due(schedule: str | None, next_run_on, run_at_time, now: datetime) -> bool:
    """Due when the run date has passed, or it is today and the run time has come."""
    if schedule not in SCHEDULES:
        return False
    run_date = parse_date(next_run_on)
    if run_date is None or run_date < now.date():
        return True
    if run_date > now.date():
        return False
    run_time = parse_time(run_at_time)
    return run_time is None or now.time() >= run_time


def next_run(schedule: str, today: date) -> date:
    if schedule == "Daily":
        return today + timedelta(days=1)
    if schedule == "Weekly":
        return today + timedelta(days=7)
    month = today.month % 12 + 1
    year = today.year + (1 if today.month == 12 else 0)
    return date(year, month, min(today.day, 28))


def first_run(run_at_time, now: datetime) -> date:
    """First scheduled date: today if the run time is still ahead (or unset), else tomorrow."""
    run_time = parse_time(run_at_time)
    if run_time is None or run_time > now.time():
        return now.date()
    return now.date() + timedelta(days=1)

"""Arithmetic for the limits panel (pure: no Frappe imports)."""

from __future__ import annotations

import math


def eta_minutes(waiting: int, finished_in_window: int, window_minutes: int = 20) -> int | None:
    """Minutes until the waiting work is done at the recent pace, or None when nothing finished lately."""
    if waiting <= 0:
        return 0
    if finished_in_window <= 0:
        return None
    return max(1, math.ceil(waiting / (finished_in_window / window_minutes)))

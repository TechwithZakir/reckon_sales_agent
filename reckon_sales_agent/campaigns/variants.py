"""A/B subject lines (pure: no Frappe imports).

A template can carry up to two alternative subject lines besides its main one. The campaign engine gives each person one of
them, and the choice is a function of the person and the step, so it is the same every time it is asked and the audience is
split close to evenly. The message remembers its letter, so opens and clicks can be compared by subject.
"""

from __future__ import annotations

import hashlib
import json

LETTERS = "ABC"
MAX_ALTERNATIVES = 2


def parse(value) -> list[str]:
    """The alternative subjects from a stored JSON list (or a list), without blanks or repeats."""
    if isinstance(value, str):
        try:
            value = json.loads(value or "[]")
        except ValueError:
            return []
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = " ".join(str(item or "").split())
        if text and text not in out:
            out.append(text)
    return out[:MAX_ALTERNATIVES]


def choose(key: str, main: str, alternatives) -> tuple[str, str]:
    """(letter, subject) for one person and step. With no alternatives the letter is empty and nothing is being tested."""
    subjects = [main] + [a for a in parse(alternatives) if a != main]
    if len(subjects) == 1:
        return "", main
    index = int(hashlib.sha256(str(key).encode("utf-8")).hexdigest(), 16) % len(subjects)
    return LETTERS[index], subjects[index]


def winner(by_variant: dict, minimum_sent: int = 30, margin: float = 5.0) -> tuple[str, float, float] | None:
    """(letter, its open rate, the weakest open rate) when one subject is clearly ahead, else None. Every subject needs
    enough sends first: a rate on a handful of messages is noise."""
    if len(by_variant) < 2 or any(int(v.get("sent") or 0) < minimum_sent for v in by_variant.values()):
        return None
    ranked = sorted(by_variant.items(), key=lambda item: -float(item[1].get("open_rate") or 0))
    best, worst = ranked[0], ranked[-1]
    gap = float(best[1].get("open_rate") or 0) - float(worst[1].get("open_rate") or 0)
    return (best[0], float(best[1].get("open_rate") or 0), float(worst[1].get("open_rate") or 0)) if gap >= margin else None

"""Approvals bound to exactly what was approved (pure: no Frappe imports).

An approval stores a fingerprint of the content, audience definition,
channels and schedule it covered. If any of them change afterwards, the
fingerprint no longer matches and the approval is void: the action is
evaluated again instead of going out under an approval it never had.
"""

from __future__ import annotations

import hashlib
import json


def fingerprint(payload) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _get(doc, field):
    return doc.get(field) if isinstance(doc, dict) else getattr(doc, field, None)


def message_payload(message) -> dict:
    """What a person approves for one outreach message."""
    return {field: _get(message, field) or "" for field in ("channel", "recipient", "subject", "body")}


def campaign_payload(campaign) -> dict:
    """What a person approves for a campaign: content, channels, audience definition and schedule."""
    steps = sorted((_get(step, "step_no") or 0, _get(step, "channel") or "Email", _get(step, "delay_days") or 0,
                    _get(step, "subject_template") or "", _get(step, "body_template") or "",
                    int(_get(step, "use_ai_personalisation") or 0))
                   for step in (_get(campaign, "steps") or []))
    return {
        "steps": [list(step) for step in steps],
        "offer": _get(campaign, "offer") or "",
        "audience": {"discovery_campaign": _get(campaign, "discovery_campaign") or "",
                     "minimum_fit_score": float(_get(campaign, "minimum_fit_score") or 0),
                     # Listed only when one is chosen, so campaigns approved before audiences keep their fingerprint.
                     **({"audience": _get(campaign, "audience")} if _get(campaign, "audience") else {}),
                     # Pilot settings decide who is contacted; listed only for pilots so other fingerprints stay stable.
                     **({"pilot": [int(_get(campaign, "holdout_percent") or 0),
                                   int(_get(campaign, "pilot_max_members") or 0)]}
                        if _get(campaign, "pilot_mode") else {})},
        "schedule": {"start_date": str(_get(campaign, "start_date") or ""),
                     "end_date": str(_get(campaign, "end_date") or ""),
                     "daily_limit": int(_get(campaign, "daily_limit") or 0)},
    }


def approval_current(stored: str | None, payload) -> bool:
    """True when nothing changed since approval. No stored fingerprint = approved before binding existed."""
    return not stored or stored == fingerprint(payload)

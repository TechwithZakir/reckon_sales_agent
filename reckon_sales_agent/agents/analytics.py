"""Analytics agent rules: attribution funnels, pilot hold-outs and lift, recommendations (pure: no Frappe imports).

Attribution follows each prospect from discovery to revenue and groups the
funnel by segment, discovery source and campaign, so the team sees which
markets and sources produce won deals, not just replies.

Pilots: a deterministic share of a campaign's eligible audience is held out
(never contacted). Comparing the contacted group's conversion with the
hold-out's shows whether the campaign itself causes deals. The verdict only
recommends: scaling up is an audience expansion that a person approves.
"""

from __future__ import annotations

import hashlib
import math

STAGES = ("prospects", "approved", "in_crm", "contacted", "replied", "positive", "meetings", "deals", "won")
MIN_TREATED = 30
MIN_HOLDOUT = 10


def pct(numerator: float, denominator: float) -> float:
    return round(100.0 * numerator / denominator, 1) if denominator else 0.0


def funnel(rows: list[dict], key: str) -> list[dict]:
    """Group prospects (one dict each, with boolean stage flags and won_value) by ``key``; best performers first."""
    groups: dict[str, dict] = {}
    for row in rows:
        label = row.get(key) or "(none)"
        group = groups.setdefault(label, {"label": label, **{stage: 0 for stage in STAGES}, "won_value": 0.0})
        group["prospects"] += 1
        for stage in STAGES[1:]:
            group[stage] += 1 if row.get(stage) else 0
        group["won_value"] += float(row.get("won_value") or 0)
    out = []
    for group in groups.values():
        group["reply_rate"] = pct(group["replied"], group["contacted"])
        group["deal_rate"] = pct(group["deals"], group["contacted"] or group["prospects"])
        group["win_rate"] = pct(group["won"], group["deals"])
        group["won_value"] = round(group["won_value"], 2)
        out.append(group)
    return sorted(out, key=lambda g: (g["won_value"], g["won"], g["deals"], g["positive"], g["prospects"]), reverse=True)


def in_holdout(seed: str, percent: int) -> bool:
    """Deterministic: the same prospect in the same campaign is always on the same side."""
    share = max(0, min(int(percent or 0), 50))
    if not share:
        return False
    return int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16) % 100 < share


def pilot_result(treated: int, treated_converted: int, holdout: int, holdout_converted: int) -> dict:
    """Conversion lift of contacting people versus the hold-out, with a two-proportion z-test."""
    p1 = treated_converted / treated if treated else 0.0
    p2 = holdout_converted / holdout if holdout else 0.0
    pooled = (treated_converted + holdout_converted) / (treated + holdout) if treated + holdout else 0.0
    se = math.sqrt(pooled * (1 - pooled) * (1 / treated + 1 / holdout)) if treated and holdout and pooled else 0.0
    z = (p1 - p2) / se if se else 0.0
    enough = treated >= MIN_TREATED and holdout >= MIN_HOLDOUT
    significant = enough and abs(z) >= 1.96
    if not enough:
        verdict, why = "too_early", (f"Need at least {MIN_TREATED} contacted and {MIN_HOLDOUT} held-out members; "
                                     f"have {treated} and {holdout}.")
    elif significant and z > 0:
        verdict, why = "scale", "Contacting people clearly raises conversion; a person can approve a larger audience."
    elif significant:
        verdict, why = "stop", "The contacted group converts worse than the hold-out; stop and rethink the campaign."
    else:
        verdict, why = "iterate", "No clear difference yet: improve the message or targeting, or keep collecting data."
    return {
        "treated": treated, "treated_converted": treated_converted, "treated_rate": round(100 * p1, 1),
        "holdout": holdout, "holdout_converted": holdout_converted, "holdout_rate": round(100 * p2, 1),
        "lift_points": round(100 * (p1 - p2), 1),
        "relative_lift": round(100 * (p1 - p2) / p2, 1) if p2 else None,
        "z": round(z, 2), "significant": significant, "verdict": verdict, "why": why,
    }


def recommendations(metrics: dict | None = None, segments: list[dict] | None = None,
                    sources: list[dict] | None = None) -> list[str]:
    """Plain, rule-based optimisation advice from campaign metrics and attribution funnels."""
    tips: list[str] = []
    m = metrics or {}
    totals = m.get("totals") or {}
    outreach = totals.get("outreach") or 0
    for channel, bucket in (m.get("by_channel") or {}).items():
        if bucket.get("outreach", 0) >= 30 and not bucket.get("positive"):
            tips.append(f"{channel}: {bucket['outreach']} messages and no positive reply. Try a different opening "
                        "or move this step to another channel.")
    if outreach >= 30 and (m.get("unsubscribe_rate") or 0) > 2:
        tips.append(f"Unsubscribe rate is {m['unsubscribe_rate']}% (above 2%): tighten targeting or soften the message.")
    if outreach >= 30 and totals.get("bounced", 0) * 100 > 5 * outreach:
        tips.append("More than 5% of emails bounce: research and verify addresses before sending.")
    steps = sorted((int(k), v) for k, v in (m.get("by_step") or {}).items() if int(k) > 0)
    if len(steps) >= 3 and steps[-1][1].get("outreach", 0) >= 30 and not steps[-1][1].get("replies"):
        tips.append(f"Step {steps[-1][0]} gets no replies: consider ending the sequence one step earlier.")
    for label, groups in (("segment", segments or []), ("source", sources or [])):
        ranked = [g for g in groups if g["contacted"] >= 20]
        if len(ranked) >= 2:
            best = max(ranked, key=lambda g: (g["deal_rate"], g["positive"]))
            worst = min(ranked, key=lambda g: (g["deal_rate"], g["positive"]))
            if best["deal_rate"] > worst["deal_rate"]:
                tips.append(f"Best {label}: {best['label']} ({best['deal_rate']}% of contacted became deals) versus "
                            f"{worst['label']} ({worst['deal_rate']}%). Shift effort towards {best['label']}.")
    if not tips:
        tips.append("Not enough data for a confident recommendation yet; keep the pilot running.")
    return tips

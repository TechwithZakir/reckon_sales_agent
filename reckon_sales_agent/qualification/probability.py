"""Deal probability: an explainable logistic model, calibrated on the Company's outcomes.

Pure (no Frappe imports). The base model weights fit, buying signal,
evidence, contactability and engagement. It is then shrunk toward the
Company's observed lead-to-deal conversion rate in the prospect's fit band,
so the estimate learns from real results as they accumulate:

    calibrated = (model_p * K + conversions_in_band) / (K + leads_in_band)

With no history the model estimate is used unchanged.
"""

from __future__ import annotations

import math

MODEL_VERSION = "logit-v1+band-calibration"
PRIOR_STRENGTH = 20  # K: how many observed leads it takes to outweigh the model
WEIGHTS = {
    "intercept": -4.2,
    "fit": 0.030,
    "buying": 0.020,
    "evidence": 0.010,
    "contactable": 0.6,
    "replied": 1.0,
    "positive_reply": 1.2,
    "meeting": 1.6,
}


def fit_band(fit: float) -> int:
    return max(0, min(int(float(fit or 0) // 20), 4))


def model_probability(features: dict) -> float:
    if features.get("unsubscribed") or features.get("do_not_contact"):
        return 0.01
    z = WEIGHTS["intercept"]
    z += WEIGHTS["fit"] * float(features.get("fit") or 0)
    z += WEIGHTS["buying"] * float(features.get("buying") or 0)
    z += WEIGHTS["evidence"] * float(features.get("evidence") or 0)
    for flag in ("contactable", "replied", "positive_reply", "meeting"):
        if features.get(flag):
            z += WEIGHTS[flag]
    return 1 / (1 + math.exp(-z))


def calibrate(history: list[tuple[float, bool]]) -> dict[int, tuple[int, int]]:
    """``history`` = [(fit_score, converted_to_deal)] -> {band: (conversions, leads)}."""
    bands: dict[int, list[int]] = {}
    for fit, converted in history:
        counts = bands.setdefault(fit_band(fit), [0, 0])
        counts[0] += 1 if converted else 0
        counts[1] += 1
    return {band: (c[0], c[1]) for band, c in bands.items()}


def deal_probability(features: dict, calibration: dict[int, tuple[int, int]] | None = None) -> tuple[float, str]:
    """(probability in percent, explanation)."""
    base = model_probability(features)
    conversions, leads = (calibration or {}).get(fit_band(features.get("fit")), (0, 0))
    calibrated = (base * PRIOR_STRENGTH + conversions) / (PRIOR_STRENGTH + leads)
    if features.get("unsubscribed") or features.get("do_not_contact"):
        calibrated = min(calibrated, 0.01)
    reasons = [f"model {base:.0%}"]
    if leads:
        reasons.append(f"{conversions}/{leads} similar leads became deals")
    engagement = [name for name in ("meeting", "positive_reply", "replied") if features.get(name)]
    if engagement:
        reasons.append("engagement: " + ", ".join(e.replace("_", " ") for e in engagement))
    return round(calibrated * 100, 1), "; ".join(reasons)


def combine(fit: float, ai_fit: float | None, ai_share_percent: float) -> float:
    """Deterministic fit blended with the AI's fit; the AI share is capped at 50%."""
    if ai_fit is None:
        return round(float(fit or 0), 1)
    share = max(0.0, min(float(ai_share_percent or 0), 50.0)) / 100
    return round((1 - share) * float(fit or 0) + share * float(ai_fit), 1)

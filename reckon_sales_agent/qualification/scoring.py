"""Deterministic, versioned prospect scoring (pure: no Frappe imports).

The same prospect, facts and profile version always give the same scores.
AI may contribute evidence-checked facts, but inferences never count and the
score itself is computed here, not by a model. Fit, buying signal, evidence
confidence and contactability are separate: a good fit may show no need.
"""

from __future__ import annotations

from reckon_sales_agent.discovery.planner import split_lines

SCORING_VERSION = "score-v1"
COMPLEXITY_WORDS = ("branch", "branches", "outlet", "outlets", "warehouse", "depot", "factory",
                    "distributor", "dealers", "nationwide", "showroom", "import", "export", "শাখা")
SIZE_WORDS = ("employees", "staff", "workers", "team of", "since 19", "since 20", "crore", "turnover")
DEFAULT_WEIGHTS = {"industry": 25, "complexity": 25, "need": 25, "scale": 15, "evidence": 10}


def _contains_any(text: str, words) -> list[str]:
    lowered = text.lower()
    return [w for w in words if w and w.lower() in lowered]


def score(prospect: dict, facts: list[dict], profile: dict | None) -> dict:
    profile = profile or {}
    evidence = [f for f in facts if not f.get("is_inference")]
    statements = " ".join(str(f.get("statement", "")) for f in evidence)
    explanation: list[str] = []
    unknowns: list[str] = []

    targets = split_lines(profile.get("target_industries"))
    industry_text = f"{prospect.get('industry') or ''} {statements}"
    if not targets:
        industry_fit = 50.0
        unknowns.append("No target industries in the profile.")
    elif _contains_any(industry_text, targets):
        industry_fit = 100.0
        explanation.append(f"Industry matches: {', '.join(_contains_any(industry_text, targets))}.")
    elif _contains_any(statements, split_lines(profile.get("fit_keywords"))):
        industry_fit = 60.0
        explanation.append("Website mentions fit keywords but the industry is not a target.")
    else:
        industry_fit = 0.0
        explanation.append("Industry is not one of the targets.")

    services = {f["statement"].lower() for f in evidence if f.get("fact_type") in ("service", "product")}
    complexity_hits = _contains_any(statements, COMPLEXITY_WORDS)
    complexity = min(100.0, 20.0 * len(services) + (40.0 if complexity_hits else 0.0))
    if complexity_hits:
        explanation.append(f"Operations: {', '.join(sorted(set(complexity_hits))[:4])}.")
    if not services and not complexity_hits:
        unknowns.append("Operational complexity unknown.")

    need_hits = [f for f in evidence if f.get("fact_type") == "need_signal"]
    need = min(100.0, 40.0 * len(need_hits))
    if need_hits:
        explanation.append(f"{len(need_hits)} need signal(s) on the website.")
    else:
        unknowns.append("No evidence of a current need.")

    size_facts = [f for f in evidence if f.get("fact_type") == "size"] or _contains_any(statements, SIZE_WORDS)
    scale = (20.0 if prospect.get("website") else 0.0) + (40.0 if size_facts else 0.0) \
        + (20.0 if complexity_hits else 0.0) + (20.0 if len(services) >= 3 else 0.0)
    reviews = int(float(prospect.get("review_count") or 0))
    if reviews >= 100:
        scale += 30.0
        explanation.append(f"{reviews} Maps reviews show an established business.")
    elif reviews >= 20:
        scale += 15.0
    scale = min(scale, 100.0)

    if evidence:
        average = sum(float(f.get("confidence") or 0) for f in evidence) / len(evidence)
        evidence_quality = round(min(1.0, len(evidence) / 8) * average * 100, 1)
    else:
        evidence_quality = 0.0
        unknowns.append("No website evidence collected.")

    weights = {
        "industry": float(profile.get("weight_industry") or DEFAULT_WEIGHTS["industry"]),
        "complexity": float(profile.get("weight_complexity") or DEFAULT_WEIGHTS["complexity"]),
        "need": float(profile.get("weight_need") or DEFAULT_WEIGHTS["need"]),
        "scale": float(profile.get("weight_scale") or DEFAULT_WEIGHTS["scale"]),
        "evidence": float(profile.get("weight_evidence") or DEFAULT_WEIGHTS["evidence"]),
    }
    total_weight = sum(weights.values()) or 1.0
    fit = (industry_fit * weights["industry"] + complexity * weights["complexity"] + need * weights["need"]
           + scale * weights["scale"] + evidence_quality * weights["evidence"]) / total_weight

    negatives = [f for f in evidence if str(f.get("statement", "")).startswith("Negative signal:")]
    if negatives:
        fit *= 0.5
        explanation.append("Negative keywords found; fit halved.")
    fit = round(fit, 1)

    if prospect.get("do_not_contact"):
        contactability = "Suppressed"
    elif prospect.get("email") or prospect.get("phone"):
        contactability = "Contactable"
    else:
        contactability = "No Contact Channel"

    qualify_at = float(profile.get("qualify_threshold") or 60)
    review_at = float(profile.get("review_threshold") or 40)
    if fit >= qualify_at and evidence_quality >= 30:
        result = "Qualified"
    elif fit >= review_at or (not evidence and industry_fit > 0):
        result = "Needs Review"
    else:
        result = "Not Qualified"

    return {
        "scoring_version": SCORING_VERSION,
        "profile_version": int(profile.get("version") or 0),
        "industry_fit": industry_fit,
        "operational_complexity": complexity,
        "need_signal": need,
        "scale": scale,
        "evidence_quality": evidence_quality,
        "fit_score": fit,
        "buying_signal_score": need,
        "evidence_confidence": evidence_quality,
        "contactability": contactability,
        "result": result,
        "explanation": " ".join(explanation),
        "unknowns": "\n".join(unknowns),
    }

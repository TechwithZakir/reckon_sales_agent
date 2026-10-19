"""Claude's evidence-grounded assessment of a prospect (one input to the combined score).

The model sees only verified research facts and the seller's offer. Its
intent score is capped when the research found no need signal, so it cannot
claim a company is buying without evidence.
"""

from __future__ import annotations

from reckon_sales_agent.providers.llm import UNTRUSTED_RULES, untrusted

PROMPT_VERSION = "assessment-v1"
NO_EVIDENCE_INTENT_CAP = 20.0

SCHEMA = {
    "type": "object",
    "properties": {
        "fit_score": {"type": "number"},
        "intent_score": {"type": "number"},
        "rationale": {"type": "string"},
        "risks": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["fit_score", "intent_score", "rationale", "risks"],
    "additionalProperties": False,
}

SYSTEM = (
    "You assess how well a Bangladeshi business fits a B2B seller's offer, for a sales team. "
    "Score fit (0-100: would this business benefit from the offer?) and intent (0-100: is there "
    "evidence of a current need?). Base both only on the numbered facts provided. If no fact shows "
    "a current need, intent must be low. Never claim a company is buying, switching or budgeting "
    "unless a fact says so. Give a short rationale citing fact numbers, and list risks or unknowns. "
    + UNTRUSTED_RULES
)


def build_prompt(seller_offer: str, prospect: dict, facts: list[dict]) -> str:
    lines = [f"[{i}] ({f.get('fact_type')}) {f.get('statement')}" for i, f in enumerate(facts, start=1)]
    return (
        untrusted("seller offer", seller_offer or "not described")
        + "\n"
        + untrusted("prospect", f"{prospect.get('business_name')} | industry: {prospect.get('industry') or '?'} | "
                                f"city: {prospect.get('city') or '?'}")
        + "\n"
        + untrusted("verified facts", "\n".join(lines) or "(no verified facts)")
    )


def sanitize(data: dict, facts: list[dict]) -> dict:
    """Clamp scores, apply the no-evidence intent cap and bound the text."""
    def clamp(value):
        try:
            return round(max(0.0, min(float(value), 100.0)), 1)
        except (TypeError, ValueError):
            return 0.0

    fit, intent = clamp(data.get("fit_score")), clamp(data.get("intent_score"))
    if not any(f.get("fact_type") == "need_signal" for f in facts):
        intent = min(intent, NO_EVIDENCE_INTENT_CAP)
    risks = [" ".join(str(r).split())[:200] for r in (data.get("risks") or [])][:6]
    return {
        "ai_fit_score": fit,
        "ai_intent_score": intent,
        "ai_rationale": " ".join(str(data.get("rationale") or "").split())[:1500],
        "ai_risks": "\n".join(risks),
    }

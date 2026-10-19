"""Evidence-backed research facts (pure: no Frappe imports).

Rule-based extraction finds what is certain (contact details, title,
description, keyword hits). AI extraction is optional and every AI fact must
quote an excerpt that is really on one of the fetched pages; facts whose
excerpt cannot be found are dropped. Inferences are kept separate from facts.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from reckon_sales_agent.discovery.planner import split_lines

FACT_TYPES = ("industry", "service", "product", "location", "size", "technology", "need_signal", "contact", "other")
PROMPT_VERSION = "research-v1"

AI_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "fact_type": {"type": "string", "enum": list(FACT_TYPES)},
                    "statement": {"type": "string"},
                    "evidence_url": {"type": "string"},
                    "evidence_excerpt": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["fact_type", "statement", "evidence_url", "evidence_excerpt", "confidence"],
                "additionalProperties": False,
            },
        },
        "inferences": {"type": "array", "items": {"type": "string"}},
        "unknowns": {"type": "array", "items": {"type": "string"}},
        "recommended_offer": {"type": "string"},
    },
    "required": ["summary", "facts", "inferences", "unknowns", "recommended_offer"],
    "additionalProperties": False,
}


@dataclass
class Fact:
    fact_type: str
    statement: str
    evidence_url: str
    evidence_excerpt: str
    confidence: float
    is_inference: int = 0

    def as_row(self) -> dict:
        return asdict(self)


def _squash(text: str) -> str:
    return " ".join((text or "").lower().split())


def excerpt_around(text: str, needle: str, width: int = 120) -> str:
    index = text.lower().find(needle.lower())
    if index < 0:
        return ""
    start = max(index - width // 2, 0)
    return text[start:start + width].strip()


def rule_facts(pages, profile_keywords: dict[str, str | None]) -> list[Fact]:
    """Deterministic facts with exact evidence; ``pages`` are ParsedPage objects."""
    facts: list[Fact] = []
    seen: set[tuple[str, str]] = set()

    def add(fact: Fact):
        key = (fact.fact_type, fact.statement.lower())
        if key not in seen:
            seen.add(key)
            facts.append(fact)

    for page in pages:
        if page.title:
            add(Fact("other", f"Website title: {page.title}", page.url, page.title, 0.9))
        if page.description:
            add(Fact("service", page.description[:300], page.url, page.description[:200], 0.8))
        for email in page.emails[:5]:
            add(Fact("contact", f"Public email: {email}", page.url, email, 1.0))
        for phone in page.phones[:5]:
            add(Fact("contact", f"Public phone: {phone}", page.url, phone, 0.9))
        for fact_type, field in (("industry", "fit_keywords"), ("need_signal", "need_keywords"),
                                 ("industry", "target_industries"), ("other", "negative_keywords")):
            for word in split_lines(profile_keywords.get(field)):
                if re.search(rf"\b{re.escape(word.lower())}\b", page.text.lower()):
                    label = {"fit_keywords": "Mentions", "need_keywords": "Need signal",
                             "target_industries": "Industry match", "negative_keywords": "Negative signal"}[field]
                    add(Fact(fact_type, f"{label}: {word}", page.url, excerpt_around(page.text, word), 0.7))
    return facts


def verified_ai_facts(data: dict, pages) -> tuple[list[Fact], list[str]]:
    """Keep only AI facts whose excerpt appears on the cited (or any) fetched page."""
    texts = {page.url: _squash(f"{page.title} {page.description} {page.text}") for page in pages}
    kept: list[Fact] = []
    dropped: list[str] = []
    for item in data.get("facts") or []:
        excerpt = _squash(item.get("evidence_excerpt"))
        fact_type = item.get("fact_type") if item.get("fact_type") in FACT_TYPES else "other"
        if len(excerpt) < 8:
            dropped.append(item.get("statement", "")[:80])
            continue
        url = item.get("evidence_url") or ""
        source = url if url in texts and excerpt in texts[url] else next(
            (u for u, t in texts.items() if excerpt in t), None)
        if not source:
            dropped.append(item.get("statement", "")[:80])
            continue
        confidence = min(max(float(item.get("confidence") or 0), 0.0), 1.0)
        kept.append(Fact(fact_type, str(item.get("statement", ""))[:500], source,
                         str(item.get("evidence_excerpt"))[:300], round(confidence, 2)))
    for inference in (data.get("inferences") or [])[:10]:
        kept.append(Fact("other", str(inference)[:500], "", "", 0.3, is_inference=1))
    return kept, dropped

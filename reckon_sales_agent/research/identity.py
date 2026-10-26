"""Identity confidence: how sure the agent is that a lead is one real business (pure: no Frappe imports).

Independent sources finding the same business (Brave Places, Google Maps via
a provider, LLM Context, web search) are strong evidence it exists. The
business's own website confirming the listing (reachable, same phone) adds
more. Fake, closed or duplicate listings tend to appear once and confirm
nothing.
"""

from __future__ import annotations

BASE = 40.0
PER_EXTRA_SOURCE = 20.0
MAX_FROM_SOURCES = 80.0
WEBSITE_CONFIRMED = 10.0
PHONE_CONFIRMED = 10.0
SEARCH_CONFIRMED = 10.0

# Source keys that are the same underlying data (one Google Maps listing through different providers).
SAME_ORIGIN = {
    "google_places_api": "google_maps", "serpapi_google_maps": "google_maps", "scrapingdog_google_maps": "google_maps",
    "scrapingbee_google_maps": "google_maps", "apify_google_maps": "google_maps",
    "google_maps_browser_experimental": "google_maps",
}


def origins(sources: list[str]) -> list[str]:
    """Distinct data origins: three Google Maps providers are one origin, not three confirmations."""
    seen: list[str] = []
    for source in sources:
        origin = SAME_ORIGIN.get(source, source)
        if source and origin not in seen:
            seen.append(origin)
    return seen


def identity_confidence(sources: list[str], *, website_confirmed: bool = False, phone_confirmed: bool = False,
                        search_confirmed: bool = False) -> tuple[float, list[str]]:
    """(0-100 confidence, reasons)."""
    distinct = origins(sources)
    if not distinct:
        return 0.0, ["No source recorded."]
    score = min(MAX_FROM_SOURCES, BASE + PER_EXTRA_SOURCE * (len(distinct) - 1))
    reasons = [f"Found by {len(distinct)} independent source(s): {', '.join(distinct)}."]
    if website_confirmed:
        score += WEBSITE_CONFIRMED
        reasons.append("Its own website was reached and read.")
    if phone_confirmed:
        score += PHONE_CONFIRMED
        reasons.append("The listed phone number appears on its website.")
    if search_confirmed:
        score += SEARCH_CONFIRMED
        reasons.append("A web search for the business returns its website.")
    return min(score, 100.0), reasons


def merge_sources(existing: str | None, *new: str) -> str:
    """Newline list of source keys, without duplicates, in first-seen order."""
    items = [line.strip() for line in (existing or "").splitlines() if line.strip()]
    for source in new:
        if source and source not in items:
            items.append(source)
    return "\n".join(items)


# Words on a business's own site that suggest it is growing or buying (English and Bangla).
DEFAULT_BUYING_SIGNALS = (
    "we are hiring", "hiring", "career", "job opening", "vacancy", "new branch", "now open", "grand opening",
    "expansion", "expanding", "new depot", "new warehouse", "delivery van", "sales representative",
    "authorized distributor", "sole distributor", "dealership", "tender", "নিয়োগ", "নতুন শাখা", "শাখা উদ্বোধন",
)


def signal_keywords(segment_signals: str | None) -> list[str]:
    """Short phrases worth looking for on a site: the defaults plus the segment's own short signals."""
    words = list(DEFAULT_BUYING_SIGNALS)
    for line in (segment_signals or "").splitlines():
        phrase = " ".join(line.split())
        if phrase and len(phrase.split()) <= 3 and phrase.lower() not in {w.lower() for w in words}:
            words.append(phrase)
    return words

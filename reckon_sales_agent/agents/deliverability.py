"""Email safety and deliverability: an allowlist for a careful first launch, domain warm-up, and a DNS check.

- Safe mode (``allowlist_only``): approved messages go only to listed addresses, @domains or phone numbers;
  everything else waits, approved, until safe mode is switched off.
- Warm-up: after the first real send, the daily email limit starts at ``warmup_start`` and grows by
  ``warmup_growth`` percent a day up to the Company's daily limit, so mailbox providers learn to trust the
  sending domain instead of filtering a sudden burst as spam.
- DNS check: SPF, DMARC and DKIM records of the sending domain (DNS over HTTPS), with plain advice.

``allowed``, ``warmup_limit`` and ``evaluate_dns`` are pure.
"""

from __future__ import annotations

from reckon_sales_agent.discovery.normalize import normalize_email, normalize_phone

DKIM_SELECTORS = ("default", "google", "selector1", "selector2", "k1", "mail", "dkim", "s1")


def allowed(recipient: str | None, channel: str, allowlist: str | None) -> bool:
    """Whether a recipient is on the allowlist (one email, @domain or phone number per line)."""
    if not recipient:
        return False
    entries = [line.strip().lower() for line in (allowlist or "").replace(",", "\n").splitlines() if line.strip()]
    if channel == "Email":
        email = normalize_email(recipient) or recipient.strip().lower()
        domain = email.split("@")[-1]
        return any(e == email or e.lstrip("@") == domain for e in entries if "@" in e or "." in e)
    phone = normalize_phone(recipient)
    return bool(phone) and any(normalize_phone(e) == phone for e in entries)


def warmup_limit(start: int, growth_percent: float, days_since_first_send: int, cap: int) -> int:
    """Today's email limit while warming up: start × (1 + growth)^days, never above the Company's cap."""
    if days_since_first_send < 0:
        days_since_first_send = 0
    value = int(round(max(1, start) * (1 + max(0.0, growth_percent) / 100.0) ** days_since_first_send))
    return max(1, min(cap, value)) if cap else max(1, value)


SPF_MECHANISMS = ("all", "include", "a", "mx", "ptr", "ip4", "ip6", "exists")
SPF_LOOKUPS = ("include", "a", "mx", "ptr", "exists", "redirect")


def spf_syntax(record: str) -> str:
    """Advice when an SPF record is broken, else ''. Live: reckon.tech's record ended in
    "~allfacebook-domain-verification=…" (a verification string glued onto it), which makes SPF fail."""
    terms = record.split()[1:]
    lookups = 0
    for term in terms:
        body = term.lstrip("+-~?")
        name = body.split(":", 1)[0].split("=", 1)[0].split("/", 1)[0].lower()
        if "=" in body and name in ("redirect", "exp"):
            lookups += name == "redirect"
            continue
        if name not in SPF_MECHANISMS:
            return (f"Your SPF record has an invalid part “{term[:60]}”. Another TXT value seems to be joined to it; "
                    "publish it as its own TXT record, so SPF ends with ~all or -all.")
        lookups += name in SPF_LOOKUPS
    if lookups > 10:
        return f"Your SPF record needs {lookups} DNS lookups (more than 10 makes SPF fail); remove unused includes."
    if terms and terms[-1].lstrip("+-~?").lower() != "all" and not any(t.startswith("redirect=") for t in terms):
        return "Your SPF record should end with ~all or -all."
    return ""


def evaluate_dns(spf: list[str], dmarc: list[str], dkim_selector: str | None) -> list[dict]:
    """Checks with plain advice. ``spf``/``dmarc`` are the TXT records found; ``dkim_selector`` the one found."""
    checks = []
    spf_records = [r for r in spf if r.lower().startswith("v=spf1")]
    spf_problem = spf_syntax(spf_records[0]) if len(spf_records) == 1 else ""
    checks.append({"name": "SPF", "ok": len(spf_records) == 1 and not spf_problem,
                   "detail": spf_records[0] if spf_records else "",
                   "advice": spf_problem if spf_problem else "" if len(spf_records) == 1 else (
                       "Publish one SPF TXT record that includes your email provider (e.g. include:_spf.google.com)."
                       if not spf_records else "Merge your SPF records into one; two SPF records make SPF fail.")})
    dmarc_records = [r for r in dmarc if r.lower().startswith("v=dmarc1")]
    policy = ""
    if dmarc_records:
        parts = dict(p.strip().split("=", 1) for p in dmarc_records[0].split(";") if "=" in p)
        policy = parts.get("p", "").lower()
    checks.append({"name": "DMARC", "ok": bool(dmarc_records),
                   "detail": dmarc_records[0] if dmarc_records else "",
                   "advice": "" if dmarc_records else
                   "Publish a DMARC record at _dmarc.<your domain>, e.g. v=DMARC1; p=none; rua=mailto:dmarc@<your domain>."
                   if not dmarc_records else ""})
    if dmarc_records and policy == "none":
        checks[-1]["advice"] = "DMARC is monitoring only (p=none); move to p=quarantine once reports look clean."
    checks.append({"name": "DKIM", "ok": bool(dkim_selector), "detail": f"selector {dkim_selector}" if dkim_selector else "",
                   "advice": "" if dkim_selector else
                   "Turn on DKIM signing at your email provider and publish its key (we looked for common selectors)."})
    return checks


# --------------------------------------------------------------------------- Frappe side


def _txt(name: str) -> list[str]:
    import requests

    try:
        response = requests.get("https://cloudflare-dns.com/dns-query", params={"name": name, "type": "TXT"},
                                headers={"accept": "application/dns-json"}, timeout=6)
        answers = response.json().get("Answer") or []
    except (requests.RequestException, ValueError):
        return []
    return ["".join(part.strip('"') for part in a.get("data", "").split('" "')) for a in answers if a.get("type") == 16]


def check_domain(domain: str, selector: str | None = None) -> dict:
    """DNS health of a sending domain: SPF, DMARC and DKIM."""
    domain = (domain or "").strip().lower().lstrip("@").split("/")[0]
    if "." not in domain:
        return {"domain": domain, "checks": [], "error": "Give a domain like yourcompany.com"}
    found_selector = None
    for candidate in ([selector] if selector else []) + list(DKIM_SELECTORS):
        if any("p=" in r for r in _txt(f"{candidate}._domainkey.{domain}")):
            found_selector = candidate
            break
    return {"domain": domain, "checks": evaluate_dns(_txt(domain), _txt(f"_dmarc.{domain}"), found_selector)}


def today_email_limit(settings) -> int:
    """The Company's email limit for today, warm-up included."""
    from frappe.utils import date_diff, nowdate

    cap = int(settings.daily_message_limit or 0)
    if not settings.get("warmup_enabled") or not settings.get("first_send_on"):
        return cap if not settings.get("warmup_enabled") else min(cap, int(settings.get("warmup_start") or 20))
    return warmup_limit(int(settings.get("warmup_start") or 20), float(settings.get("warmup_growth") or 20),
                        date_diff(nowdate(), settings.first_send_on), cap)

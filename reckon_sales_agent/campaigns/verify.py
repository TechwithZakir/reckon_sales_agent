"""Email address checking: the rules (pure: no Frappe imports, so they are unit-tested directly).

A check gives one of three answers:
* Valid: the address is well formed and its domain has a mail server.
* Risky: it will probably be delivered but may not reach the person you want: a disposable address, a shared mailbox such as
  info@, or a domain that looks like a typo of a well known one. A risky address can still be emailed.
* Invalid: it cannot be delivered (not a real address, a reserved test domain, or a domain with no mail server). An invalid
  address is never emailed by a campaign, so it cannot hurt the sender's reputation.

The built-in check needs no account: the address's syntax, a short list of rules and one DNS lookup for the domain. A
provider (ZeroBounce) can add a deeper check of the mailbox itself.
"""

from __future__ import annotations

import re

VALID, RISKY, INVALID = "Valid", "Risky", "Invalid"
STATUSES = (VALID, RISKY, INVALID)

SYNTAX = re.compile(r"^[a-z0-9._%+'-]{1,64}@([a-z0-9-]+\.)+[a-z]{2,24}$")
RESERVED_DOMAINS = frozenset({"example.com", "example.org", "example.net", "test.com", "domain.com", "email.com", "localhost"})
RESERVED_SUFFIXES = (".test", ".example", ".invalid", ".localhost", ".local")
DISPOSABLE = frozenset({
    "mailinator.com", "10minutemail.com", "guerrillamail.com", "guerrillamail.net", "tempmail.com", "temp-mail.org", "yopmail.com",
    "trashmail.com", "throwawaymail.com", "getnada.com", "maildrop.cc", "sharklasers.com", "dispostable.com", "fakeinbox.com",
    "mintemail.com", "mohmal.com", "emailondeck.com", "tempinbox.com", "mailnesia.com", "spamgourmet.com", "burnermail.io",
    "moakt.com", "discard.email", "tmpmail.org", "tempr.email", "mail.tm", "inboxkitten.com", "33mail.com", "guerrillamailblock.com",
})
ROLE_LOCALS = frozenset({
    "admin", "administrator", "info", "sales", "support", "contact", "hello", "office", "postmaster", "webmaster", "noreply",
    "no-reply", "donotreply", "do-not-reply", "billing", "accounts", "hr", "careers", "jobs", "marketing", "team", "mail",
    "enquiry", "enquiries", "inquiry", "help", "service", "abuse", "hostmaster", "root", "newsletter", "mailer-daemon",
})
TYPOS = {
    "gmial.com": "gmail.com", "gmai.com": "gmail.com", "gamil.com": "gmail.com", "gmal.com": "gmail.com", "gmail.co": "gmail.com",
    "gmail.con": "gmail.com", "gnail.com": "gmail.com", "hotmial.com": "hotmail.com", "hotmal.com": "hotmail.com",
    "hotmail.con": "hotmail.com", "hotnail.com": "hotmail.com", "yaho.com": "yahoo.com", "yahooo.com": "yahoo.com",
    "yahoo.con": "yahoo.com", "outlok.com": "outlook.com", "outlook.con": "outlook.com", "iclod.com": "icloud.com",
}


def domain_of(email: str) -> str:
    return str(email or "").strip().lower().rpartition("@")[2]


def check(email: str, mx_found: bool | None) -> dict:
    """{status, reason, suggestion} for one address. ``mx_found`` is the result of the domain lookup: True (a mail server
    exists), False (the domain has none) or None (it could not be looked up just now). With None and nothing else wrong the
    status is '' (not decided), so a network hiccup never marks a good address."""
    value = str(email or "").strip().lower()
    if not SYNTAX.match(value) or ".." in value:
        return {"status": INVALID, "reason": "Not a valid email address.", "suggestion": ""}
    domain = domain_of(value)
    if domain in RESERVED_DOMAINS or domain.endswith(RESERVED_SUFFIXES):
        return {"status": INVALID, "reason": "A reserved test domain that cannot receive mail.", "suggestion": ""}
    if domain in TYPOS:
        return {"status": RISKY, "reason": f"The domain looks like a typo of {TYPOS[domain]}.", "suggestion": value.replace(domain, TYPOS[domain])}
    if mx_found is False:
        return {"status": INVALID, "reason": "The domain has no mail server.", "suggestion": ""}
    if domain in DISPOSABLE:
        return {"status": RISKY, "reason": "A disposable address that stops working soon.", "suggestion": ""}
    local = value.partition("@")[0]
    if local in ROLE_LOCALS:
        return {"status": RISKY, "reason": f"A shared mailbox ({local}@): it may not reach a person.", "suggestion": ""}
    if mx_found is None:
        return {"status": "", "reason": "The domain could not be checked just now.", "suggestion": ""}
    return {"status": VALID, "reason": "", "suggestion": ""}


def merge(builtin: dict, provider: dict | None) -> dict:
    """Combine the built-in answer with a provider's: the worse one wins, and the provider's reason is kept when it decides."""
    if not provider or not provider.get("status"):
        return builtin
    order = {"": 0, VALID: 1, RISKY: 2, INVALID: 3}
    return provider if order[provider["status"]] > order.get(builtin.get("status", ""), 0) else (
        {**builtin, "status": builtin["status"] or provider["status"]})


def zerobounce(payload: dict) -> dict:
    """ZeroBounce's validate answer as a check result (pure, so the mapping is tested without the network)."""
    status = str((payload or {}).get("status") or "").lower()
    sub = str((payload or {}).get("sub_status") or "").lower().replace("_", " ")
    if status == "valid":
        return {"status": VALID, "reason": "", "suggestion": ""}
    if status in ("invalid", "spamtrap", "abuse", "do_not_mail"):
        reason = {"spamtrap": "A known spam trap.", "abuse": "Known to report mail as spam."}.get(status) or (
            f"The mailbox does not exist ({sub})." if sub else "The mailbox does not exist.")
        return {"status": INVALID, "reason": reason, "suggestion": ""}
    if status in ("catch-all", "unknown"):
        return {"status": RISKY, "reason": "The server accepts all mail, so the mailbox cannot be confirmed." if status == "catch-all"
                else "The mailbox could not be confirmed.", "suggestion": ""}
    return {"status": "", "reason": "", "suggestion": ""}


def breakdown(counts: dict) -> dict:
    """Shares for the bar: Valid, Risky, Invalid and Unchecked as percentages of everyone with an email (they add to 100)."""
    total = sum(int(counts.get(k) or 0) for k in (*STATUSES, "Unchecked"))
    if not total:
        return {"total": 0, "percent": {k: 0 for k in (*STATUSES, "Unchecked")}, "deliverable": 0}
    percent = {k: round(100 * int(counts.get(k) or 0) / total) for k in (*STATUSES, "Unchecked")}
    drift = 100 - sum(percent.values())
    biggest = max(percent, key=percent.get)
    percent[biggest] += drift
    checked = total - int(counts.get("Unchecked") or 0)
    return {"total": total, "percent": percent,
            "deliverable": round(100 * (int(counts.get(VALID) or 0) + int(counts.get(RISKY) or 0)) / checked) if checked else 0}

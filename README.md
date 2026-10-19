# Reckon Sales AI Agent

A Python-first sales agent for **Frappe CRM**, sold as a module of
[Reckon SaaS Platform](https://github.com/TechwithZakir/Reckon-SaaS-Platform).
It finds B2B prospects, researches their public websites, scores the fit with
evidence, puts approved prospects into the CRM, and runs email follow-up with
a human approving every message. App name: `reckon_sales_agent`. Market: Bangladesh first.

**Status: first release, unreleased. Built and unit-tested; not yet verified on a bench site.**

## What it does

1. **Discovery campaigns.** Choose keywords or industries, locations and a
   target count. The agent plans a bounded list of searches (at most 50, capped
   by your per-job limit), and you preview it before running.
2. **Sources.** Each source is a connector with a declared field-storage policy:
   - **Demo data:** offline, fictional, for training.
   - **CSV import:** your own lists.
   - **Google Places API (New):** official API only, vendor key, vendor-enabled.

   Scraping Google Maps pages is deliberately not supported.
3. **Policy and provenance.** Every stored field records its source, retrieval
   time, retention and attribution. Fields a source does not allow to keep are
   never stored. Google Places content expires after the configured retention
   (30 days by default) unless the company's own website confirms it.
4. **Deduplication.** Duplicates are matched in order on source reference,
   website domain, phone (`+880` normalised), and name plus city. Fuzzy matches
   are only flagged for review, never merged automatically. Re-running a job
   creates no duplicates.
5. **Website research.** Fetching is SSRF-safe (details under Security):
   - It reads at most 4 pages per site and respects `robots.txt`.
   - Scripts and hidden text are stripped; nothing is executed.
   - It extracts contact details and keyword evidence.
   - Optionally, **Claude** extracts structured facts. Each AI fact must quote
     an excerpt that is actually on the page, or it is dropped. Inferences are
     kept separate from facts.
6. **Qualification.** Scoring is deterministic and versioned (`score-v1`). It
   rates industry fit, operational complexity, need signal, scale and evidence
   quality, and keeps fit, buying signal, evidence confidence and
   contactability as separate dimensions. Managers can override a result with
   a recorded reason, and the override survives re-scoring.
7. **Review queue.** On the Prospect Review page, approve, reject, defer, merge
   or re-research prospects in bulk.
8. **CRM sync.** Approved prospects become a CRM Organization and a CRM Lead
   with a research note:
   - Records are created in your Company only.
   - Existing CRM data is filled where empty, never overwritten.
   - Fields only temporarily licensed from a source are not copied.
9. **Email campaigns.** Multi-step sequences use safe `{{placeholders}}`
   (never Jinja) and optional AI-personalised opening lines. Approval works in
   stages:
   - A manager approves the campaign.
   - Each message is approved when human approval is on (the default).
   - Editing the steps sends the campaign back for approval.
10. **Sending safety.** Immediately before every send, the agent re-checks:
    the kill switch, whether outbound is enabled, the subscription, campaign
    and member state, the suppression list, approval, the daily limits and the
    monthly quota. Outbound sending is **off by default**; approved messages
    are then logged as dry runs.
11. **Stop conditions.**
    - A reply stops the sequence for that contact.
    - "Unsubscribe" or "stop" in a reply, or the unsubscribe link (a POST
      confirmation, safe from link scanners), adds the contact to the
      suppression list.
    - A CRM Deal created from the lead marks the member Converted.
12. **SaaS.**
    - Registers as module `sales_agent` with a seed for new companies:
      settings, a default profile and connectors.
    - Syncs roles from Tenant User Assignment.
    - Monthly metering for discovery results, research pages, AI calls and
      sent messages.
    - Every privileged action writes an append-only audit entry.

## Autonomous agent (autopilot)

Every autonomous step can be switched off, respects the kill switch and the
Company's plan limits, and is recorded in the audit trail.

- **Targeting master setup** (*Sales Targeting Profile*) defines:
  - who to find: market (B2B/B2B2C/B2G), company size, industries, B2B
    segments (distributors, wholesalers, factories, ...), keywords
    (English/Bangla), interests and needs, and exclusions;
  - where: a table of city, area, division and country.

  Discovery campaigns built from a profile search every term × location
  within the bounded budget, and drop results that match an exclusion.
- **AI search planner.** *Suggest with AI* asks Claude for search phrases,
  Bangla variants, buyer segments, related industries and exclusions, based on
  what you sell. Suggestions are stored for review; *Apply AI Suggestions*
  merges them in. A campaign can also *Expand Searches with AI* at plan time.
- **Scheduled discovery.** Set a campaign to run Daily, Weekly or Monthly.
  Each run re-plans from the targeting profile and starts automatically.
  Deduplication keeps re-runs from creating duplicates.
- **Lead crawler** (`permitted_directory` connector):
  - Crawls listing pages of directories or member lists the tenant confirms
    it may use. Start URLs accept `{keyword}`/`{location}` placeholders.
  - Reads schema.org JSON-LD business data first, then listing links that
    point to company websites, and follows pagination under an allowed path.
  - Every request is SSRF-safe and obeys `robots.txt`, with at least a 1 s
    delay and a page cap of 50.
  - No logins or evasion. Google Maps pages are refused; use the Places API
    connector.
- **AI lead scoring.** The deterministic, versioned score stays the base.
  Claude adds an assessment (fit, intent, rationale, risks) built only from
  verified facts:
  - Intent is capped at 20 unless the research found a need signal.
  - The *combined score* blends the AI in at a configurable share, never
    more than 50%.
- **Deal probability.** An explainable logistic model over fit, buying
  signal, evidence, contactability and engagement (replies, positive
  replies, meetings).
  - It is calibrated per Company against its own lead-to-deal history and
    re-run weekly, so it learns from outcomes.
  - It fills a CRM Deal's probability only when nobody has set one.
- **Auto-approval.** With *Auto-Approve Strong Prospects* on, a prospect is
  approved, and optionally made a CRM Lead, only when every rule holds:
  qualified; minimum fit, evidence and deal probability; a contact channel;
  not suppressed; not a possible duplicate; under the daily cap.
- **Omni-channel campaigns.** Each step has a channel:
  - **Email.**
  - **SMS**, via the platform's BulkSMSBD gateway.
  - **WhatsApp**, via the `frappe_whatsapp` app.
  - **Call Task / LinkedIn Task:** a CRM Task for a person.

  SMS and WhatsApp go only to prospects with recorded consent; a public phone
  number is never treated as permission. A step a member can't be reached on
  is skipped. Internal task steps need no approval; outreach steps keep every
  pre-send check.
- **AI reply handling.** Replies by email, and by WhatsApp when installed,
  are classified as: interested, meeting request, question, not now, not
  interested, wrong person, unsubscribe, out of office.
  - Rules act immediately: opt-outs are suppressed and the sequence stops.
    Out-of-office pauses for 5 days.
  - Claude then refines the class in the background.
  - Positive replies get a high-priority CRM Task for the lead owner and a
    note on the lead's timeline in `/crm`, and raise the deal probability.
    "Not now" gets a reminder task in 30 days.
- **Campaign analytics.** The *Campaign Analytics* page shows, by channel and
  by step: members, sent, reply rate, positive rate, meetings, deals,
  conversion, pipeline value and unsubscribe rate. *Analyze with AI*, also
  run weekly, sends Claude only aggregated numbers (no names or contact
  details) and stores its summary and recommendations as a *Sales Campaign
  Insight*.

## Separating Frappe CRM by Company

Tenants are Companies on one shared site, but Frappe CRM records carry no
Company. `crm_tenancy.py` adds a read-only `rsa_company` field and enforces it:

| Group | DocTypes | Rule |
| --- | --- | --- |
| Data | CRM Lead, Deal, Organization, Task, Call Log, Notification, Product, Sales Hierarchy, Telephony Agent, Invitation, FCRM Note; Frappe Contact, Address, Communication, Comment, ToDo, File | Strictly per Company. Records with no Company are hidden from every tenant. |
| Master lists | CRM Territory, Industry, Lead Source, Lost Reason, Holiday List, Service Level Agreement, Dashboard, View Settings | Each Company has its own entries. Unowned entries (CRM's defaults) are shared and read-only. |
| Site configuration | FCRM Settings, CRM Global Settings, Fields Layout, Form Script, Lead/Deal/Communication Status, Twilio, Exotel, ERPNext CRM Settings | Tenants can read it; only vendor administrators can change it. |
| Child tables | CRM Contacts, Products, Status Change Log and the rest | Follow their parent. |

How the rules are enforced:
- **Company stamping.** New records get the creator's Company. System and
  webhook records inherit the Company of what they are attached to.
- **Permission hooks** filter lists, search and document access.
- **Link checks.** Every Link and Dynamic Link (child tables included) must
  stay within one Company.
- **Conversion lookups.** Lead conversion only reuses organizations and
  contacts from the lead's Company.
- **Name clashes.** A name used by another Company gets `<name> - <abbr>`.
- **Backfill.** Install and migrate fill in the Company on existing records.

The Sales Agent's own 15 DocTypes have a standard `company` field and use the
platform's `tenant_security` hooks. Server-managed fields (scores, review and
approval state, plan limits) cannot be set through forms or the API.

## Install

```bash
R="python apps/reckon_saas_platform/scripts/reckon_bench.py"
$R get-app https://github.com/frappe/crm            # upstream Frappe CRM
$R get-app <reckon-sales-agent-repo-url>
bench --site <site> install-app crm reckon_sales_agent
bench --site <site> migrate
bench restart
```

Requires `frappe`, `erpnext`, `crm` and `reckon_saas_platform`, plus the Python
package `anthropic>=1.0`, which bench installs from `pyproject.toml`.

The first migrate adds a Company column to Communication, Comment, ToDo and
File. That can take a while on large sites.

## Configure

1. **Vendor setup** (`/app/sales-agent-platform-settings`, vendor only):
   - **Claude:** Anthropic API key, model (default `claude-opus-5-5`), effort.
     AI stays off until enabled here **and** in a Company's settings.
   - **Google Places:** API key, plus confirmation that the Maps Platform
     terms were reviewed, plus the retention window (1–30 days).
   - **Crawler:** user agent, timeouts, page size and page count.
   - **Plan limits:** default monthly limits. Per-company overrides are
     vendor-only.
2. **SaaS plans.** In **SaaS Platform → Modules**, check that **Sales AI
   Agent** (`sales_agent`) is available for sale. Then create SaaS Plans with
   *Module = sales_agent* and share `/reckonerp-signup?module=sales_agent`.
3. **Each Company's Sales Agent Settings:**
   - Describe what you sell; this is used for fit and drafting.
   - Set the sender name and postal address (shown in the email footer).
   - Set the daily limit.
   - Turn on **Outbound Sending Enabled** only after testing with dry runs.
4. **Outgoing email.** Configure Frappe's default outgoing Email Account.
   Replies thread back to the outreach message and stop the sequence.

## Use

1. Open **Sales Agent** (`/desk/sales-agent`) and create a Discovery Campaign.
   Start with the *Demo data* connector.
2. Click **Preview Plan**, then **Start Discovery**. The job runs in the
   background (watch it on the job form, which can also **Cancel Job**) and
   researches new prospects automatically.
3. Review prospects in **Prospect Review** (bulk approve, defer, reject,
   research again) or on each prospect: **Review → Merge Into…**,
   **Research Website**, **Score Again**, **Create CRM Lead**. Approved
   prospects appear in `/crm/leads`.
4. Create a **Sales Campaign**. It starts with a two-step template.
   1. **Submit for Approval**; a manager clicks **Approve and Start**.
   2. Approve drafts from the message list (bulk **Approve**) or the form.
   3. Sending runs hourly, or use **Actions → Send Approved Now**.
   4. **Stop Sequence** on a member stops follow-up, for example after a
      phone reply.
5. Managers can **Override Result** on a qualification, with a reason.

## Tests

The unit tests need no bench. They stub Frappe and use Frappe's own
HTTP and HTML dependencies:

```bash
pip install beautifulsoup4 requests urllib3 certifi "anthropic>=1.0"
python -m unittest discover -s tests -v
```

They cover:
- connectors and source policy;
- normalisation and deduplication fingerprints;
- SSRF defences, including redirects to private addresses, size and content
  limits, and redirect caps;
- HTML parsing and hidden prompt-injection text;
- AI evidence verification;
- scoring determinism and versioning;
- template safety (no Jinja);
- the Claude request shape and refusal handling;
- CRM Company isolation;
- DocType definitions and safe defaults.

### End-to-end tests (Playwright)

These run against a **test or staging** bench site with background workers
running. They log in as two tenant Companies and check:
- isolation of CRM and Sales Agent data;
- read-only site settings and plan limits;
- the Desk guard;
- the full pipeline: demo discovery → deduplication → review → CRM lead →
  campaign approval → dry-run send → unsubscribe confirmation.

```bash
bench --site sales-agent-test.localhost execute reckon_sales_agent.e2e.setup_fixtures --kwargs "{'password': '<test password>'}"
cd apps/reckon_sales_agent/e2e
npm install
npx playwright install chromium
SITE_URL=http://sales-agent-test.localhost:8000 E2E_PASSWORD='<test password>' npx playwright test
```

`setup_fixtures` refuses to run unless the site name contains `test`,
`staging`, `e2e` or `.localhost`. It creates two Companies, *SA E2E Alpha*
and *SA E2E Beta*, on a free trial plan, each with a Company Admin user.

## Security notes

- **Credentials.** Keys are stored in Frappe Password fields on a vendor-only
  Single and are never returned to tenants or logged.
- **SSRF-safe fetching:**
  - only http/https on standard ports;
  - DNS is resolved and every address must be public (no private, loopback,
    link-local, carrier-grade NAT, reserved, multicast or metadata);
  - the connection goes to the checked IP with TLS verified against the
    hostname, which defeats DNS rebinding;
  - every redirect is re-validated;
  - bytes, time and redirect count are bounded.
- **Prompt injection.** Website text reaches Claude only inside an
  untrusted-data wrapper. The model has no tools, can only return
  schema-validated JSON, and its facts must cite on-page excerpts.
- **Limits.** Quotas, concurrency caps and entitlement are checked on the
  server. The subscription check fails closed.
- **Personal data.** Lists show suppression values masked and matching uses
  hashes, but the normalised values are stored, so access controls and
  retention apply to them too.

## Known limitations

- **Not yet run on a bench.** Expect fixes after the first install
  (DocType sync, page rendering, CRM SPA behaviour).
- **Connectors.** Demo data, CSV import, Google Places API and the
  permitted-directory crawler are implemented. Licensed data providers are not.
  The crawler's extraction depends on each directory's markup; check results
  per source.
- **WhatsApp.** It needs the `frappe_whatsapp` app. Free-form messages only
  work inside WhatsApp's 24-hour service window, and template messages are
  not wired yet.
- **SMS.** Delivery reports are not imported, and inbound SMS replies are not
  captured because BulkSMSBD is one-way.
- **Replies.** They are tracked when they reach Frappe's incoming Email
  Account; replies sent elsewhere must be marked manually (stop the member).
- **Shared core DocTypes.** Contact, Address, Communication, Comment, ToDo and
  File are shared with ERPNext and Distribution, so the Company separation
  applies there too. Accounts SaaS also scopes Contact/Address with
  `rd_company`; both checks apply.
- **CRM gaps.**
  - Lead/Deal statuses, SLAs and telephony are site-wide.
  - Some upstream CRM endpoints use `frappe.get_all`, which skips permissions
    (dashboard counts, group-by options). They need an audit on a real site.
  - Email-to-lead creates unowned leads.
  - `TenantCRMLead` assumes no other app overrides the CRM Lead class.
- **Database.** Bulk backfill SQL uses MariaDB `update ... join` syntax.
- **Legal review.** Check current Bangladesh data-protection and BTRC
  telemarketing rules, and your Google Maps Platform contract, before
  enabling outbound sending or Places in production.

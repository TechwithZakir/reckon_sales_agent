# Reckon Sales AI Agent

A Python-first sales agent for **Frappe CRM**, sold as a module of
[Reckon SaaS Platform](https://github.com/TechwithZakir/Reckon-SaaS-Platform).
It finds B2B prospects, researches their public websites, scores the fit with
evidence, puts approved prospects into the CRM, and runs email follow-up with
a human approving every message. App name: `reckon_sales_agent`. 

**Status: first release, unreleased. Built and unit-tested; not yet verified on a bench site.**

## What it does

1. **Discovery campaigns.** Choose keywords or industries, locations and a
   target count. The agent plans a bounded list of searches (at most 50, capped
   by your per-job limit), and you preview it before running.
2. **Sources.** Each source is a connector with a declared field-storage policy:
   - **Demo data:** offline, fictional, for training.
   - **CSV import:** your own lists.
   - **Google Maps lead sources** (see *Google Maps lead generation* below):
     Google Places API, SerpAPI, Scrapingdog, Apify, and an experimental
     Playwright headless browser.
   - **Permitted-directory crawler**, with an optional Claude extraction
     fallback.
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

## Google Maps lead generation

The pipeline: **search trigger** (manual or scheduled discovery from a
targeting profile) → **Maps data source** → **website crawling and
enrichment** → **scoring** → **CRM storage**.

| Connector | How it gets Maps data | Needs |
| --- | --- | --- |
| `google_places_api` | Official Google Places API (New) | Places key; terms reviewed |
| `serpapi_google_maps` | SerpAPI Google Maps engine (JSON) | SerpAPI key |
| `scrapingdog_google_maps` | Scrapingdog Google Maps API (JSON; Bangladesh city coordinates built in) | Scrapingdog key |
| `scrapingbee_google_maps` | ScrapingBee Google API with `search_type=maps` (JSON; key sent in the Authorization header) | ScrapingBee key |
| `apify_google_maps` | Apify actor `compass~crawler-google-places` (run-sync, dataset items) | Apify token |
| `google_maps_browser_experimental` | **Experimental.** Headless Chromium (Playwright) scrolls the Maps results feed and opens each place | In the bench folder: `./env/bin/pip install playwright`; as the bench user (no sudo) `./env/bin/playwright install chromium`; once as root `sudo ./env/bin/playwright install-deps chromium` |

**Rules for every Maps source:**
- **Off until enabled.** The vendor enables each source in *Sales Agent
  Platform Settings* and ticks *I Accept Responsibility for Google Maps Data
  Use*. Google's Terms of Service restrict scraping Maps; review them with
  your lawyer.
- **Opt-in per tenant.** Each tenant connector also needs *Source Policy
  Reviewed*.
- **Retention.** Maps-derived fields are attributed to Google Maps and kept
  for *Maps Data Retention (Days)* (default 30), unless the company's own
  website confirms them. They are not copied into the CRM until then.
  Retention 0 keeps them; that is the vendor's decision.
- **Extra fields.** Rating and review count are kept, and review volume
  raises the *scale* part of the lead score.

**The experimental browser does not evade blocking.** It uses the browser's
own user agent, with no proxy rotation, stealth plugins or CAPTCHA solving.
Google's cookie consent page is a privacy choice, not bot detection: the bot
clicks *Reject all* once and carries on (the job stops with code `consent`
if it cannot). A CAPTCHA or "unusual traffic" page is bot detection: the run
stops with code `captcha` and the bot never tries to pass it. There is a
minimum 2-second delay between places and a hard cap of 100 places per
search. Google changes its page often; when it does, the connector returns
fewer or no results rather than wrong data.

### Agents and governance

Four agents work for each Company. The **Research** agent handles discovery,
company research and scoring. The **Content** agent writes drafts, localises
them and checks facts. The **Engagement** agent handles replies, follow-ups
and routing. The **Analytics** agent tracks conversions and attribution and
suggests optimisations. Before any of them acts, the policy engine
(`agents/policy.py`) applies the autonomy matrix:

| Action | Default |
| --- | --- |
| Research a company; score a lead with evidence; create a CRM lead (deduplicated); draft content; analyse a campaign | Automatic |
| Send already-approved content to an eligible audience; publish approved scheduled content | Automatic within limits |
| Answer a routine question from approved facts | Automatic where the channel's rules allow |
| Launch a campaign or expand its audience materially; change prices, discounts or terms; delete records; handle complaints, legal requests or uncertain claims | Human approval |
| Contact someone without valid permission; ignore an unsubscribe or suppression entry | Blocked |

**Approval is a permission boundary, not a confidence threshold.** No AI
score can override a consent denial, a suppression entry, the kill switch
or a missing approval. Unknown actions need a person.

**Approvals are bound to what was approved.** A campaign approval stores a
fingerprint of its steps (content and channel), offer, audience definition
and schedule. A message approval stores a fingerprint of its channel,
recipient, subject and body. Any later change voids the approval: the
campaign returns to *Pending Approval*, or the message returns to *Draft*.
The send path checks again before every send. An audience that grows by half
again (and by at least 10) after approval also needs a fresh approval.
Every audit-trail entry (*Sales Agent Activity*) names the agent that acted
and the policy outcome.

**Research agent: verification and identity.** Smart Sources records every
source that found the same business (*Found By Sources*). Several Google
Maps providers count as one origin, since they read the same listing.
**Identity confidence** starts at 40 for one source and adds 20 for each
further independent source (up to 80), plus 10 each when the business's own
website was read, when its listed phone appears on that site, and when a web
search returns that site. A lead without a website, or found by only one
source, gets a verification web search through the routed provider (Brave by
default). The search finds the missing website or confirms the existing one;
leads already corroborated skip it to save cost. Research looks for buying
signals on the site: common ones such as hiring, a new branch, a depot, a
dealership or a tender, in English and Bangla, plus the segment's own short
signals from the market brief. Every outcome keeps a research record, even
*Skipped* (no website, or research off), and still goes on to scoring.
Syncing to the CRM links an existing CRM Lead for the same business (email,
phone, website or organisation) instead of creating a duplicate. It only
fills empty fields, never replacing what a person entered, and keeps
agent-owned fields up to date: fit score, deal probability, identity
confidence and research summary.

**Content agent: approved facts only.** The *Knowledge Library* (Sales
Knowledge Item) holds the wording agents may use: product, service,
pricing, offer, FAQ, proof, policy and brand items. An item is used only
once it is approved and while it is still valid. Editing an approved item
sends it back for approval, and only *Pricing* and *Offer* items can put a
price, discount or offer into a message. The business profile adds a brand
voice and a *Never Say* list. On a campaign, **Write with AI** has Claude
write the sequence for the chosen segment, in English or Bangla, across
Email, WhatsApp and SMS. The plan is fixed (for example Email, then WhatsApp
3 days later, then Email), and the writing uses only approved knowledge.
The new steps replace the old ones, so the campaign needs approval again.
**Every save runs the content check**, which flags:

- absolute or banned claims ("guaranteed", "100%", "best in Bangladesh",
  "lowest price", the Bangla equivalents, and the Never Say list);
- figures (taka, percent, clients, years…) that no approved item contains;
- discounts or offers that no approved Pricing or Offer item makes;
- unknown placeholders;
- channel length limits.

**Check Content** adds Claude's check for claims the approved knowledge does
not support. A campaign with issues can be approved only by a person who
confirms they have reviewed them: uncertain claims and commercial terms are
human decisions.

**Engagement agent: replies, answers and delivery events.**

- **Duplicate events are ignored.** Each inbound reply is handled once,
  keyed by the provider's message id.
- **Reply intents.** Replies are classified as *interested*, *meeting
  request*, *question*, *objection*, *not now*, *not interested*, *wrong
  person*, *complaint*, *unsubscribe*, *out of office*, *irrelevant* or
  *other*, in English and Bangla.
- **Opt-outs and complaints found by the rules are final.** The AI cannot
  overturn them. A complaint suppresses the sender and creates a
  high-priority task for a person.
- **Irrelevant replies leave the sequence on schedule.**
- **Questions are answered only from the approved Knowledge Library.**
  Pricing exceptions, contract terms, complaints, legal matters and anything
  the library does not cover go to a person as a task. Each answer is
  content-checked. It goes out automatically only when *Answer Routine
  Questions Automatically* is on (off by default) and the channel allows it;
  otherwise it waits as a draft for approval. It is sent through the normal
  send path, which re-checks consent, suppression, the kill switch and
  limits.
- **WhatsApp service window.** Free-form WhatsApp messages go out only
  within 24 hours of the customer's last message. Outside that window a step
  must name an approved template (*WhatsApp Template* and *Template
  Parameters*, sent through frappe_whatsapp); otherwise that step is skipped
  with the reason recorded.
- **Bounces and complaints.** Email providers POST them to
  `/api/method/reckon_sales_agent.api.email_events`, signed with an
  `X-Reckon-Signature` header: an HMAC-SHA256 of the raw body using
  *Webhook Signing Secret*. The body is `{"events": [{"id", "type":
  bounce|complaint|delivered, "bounce_type": hard|soft, "email",
  "message_id"}]}`. Unsigned requests are refused and repeated event ids are
  ignored.
  - A hard bounce or a complaint suppresses the address and stops the
    sequence. A soft bounce is only recorded.
  - Frappe's own bounce detection (a Communication marked *Bounced*) is
    handled the same way.

**Analytics agent: attribution, pilots and optimisation.**

- **Attribution.** Campaign Analytics starts with "From discovery to
  revenue". Each prospect discovered in the period is followed through the
  funnel: approved, in the CRM, contacted, replied, positive, meeting, deal,
  won, and won value. The funnel is grouped by **segment** (the market
  brief's targeting profile), **source** (Brave Places, LLM Context, Google
  Maps provider…) and **campaign**, so you see which markets and sources
  produce revenue, not just replies.
- **Pilot mode.** A pilot campaign holds out a deterministic share of its
  eligible audience (*Hold-out %*, at most 50) that is never contacted. It
  also caps how many are contacted (*Pilot Audience Limit*); the rest wait.
  - Deals created for hold-out members still count. The pilot result
    compares conversion in the two groups (a two-proportion z-test) and gives
    a verdict: *too early*, *iterate*, *ready to scale* or *stop*.
  - The verdict only recommends. Pilot settings are part of the campaign's
    approval, so scaling up (switching the pilot off or raising the limit)
    is an audience expansion a person approves. After that approval, waiting
    members start.
- **Optimisation.** Weekly insights always include rule-based advice:
  - channels with many sends and no positive replies;
  - unsubscribe rates above 2% and bounce rates above 5%;
  - a final step nobody replies to;
  - the best and worst segment or source by deal rate.

  Claude adds its analysis of the aggregated numbers when AI is on. Pilot
  campaigns are measured weekly, or on demand with *Measure now*.

**Search plans spread out.** Each run divides its leads over many keyword ×
location pairs, at least 5 leads per search, with consecutive searches
differing in both keyword and place. Each completed run moves the plan on,
so scheduled runs eventually search every pair.

### Market research agent and Smart Sources

**Lead Finder Studio starts with "Your business".** You describe what you
sell, which industries and business types buy it, the regions you serve,
signs of a good customer and your competitors. You can import your best
customers from won CRM deals. **Research my market** then:

1. Builds research queries from the profile: industries in your regions,
   buyers of your products, companies like your best customers, industry
   associations, market trends and competitors' customers.
2. Reads the web through the active page-context provider (Brave LLM Context
   by default) or web search, within *Requests per Market Brief*.
3. Has Claude turn the pages into a **Market Brief**: customer segments with
   priority, why each fits, search keywords that match the customer
   businesses themselves, Bangla variants, locations, buying signals and
   words to exclude. A segment may only cite pages the agent read. Without
   AI, a plan is built from the profile alone.
4. On approval, each kept segment becomes a Targeting Profile ready for
   discovery.

**Lead search routing.** Providers are grouped by capability: *places*
(Brave Places, Google Places, the Maps APIs), *page context* (Brave LLM
Context) and *web search* (Brave Web Search, the Google Search APIs). Brave
is the default for each; the vendor can pick another default in *Lead Search
Routing*. The **Smart Sources** connector runs each discovery search on every
active places and page-context provider, interleaves the results, keeps each
business once (website, phone or name and city) and applies the strictest
data policy of the sources used. Research and verification try the default
web provider first and fall back to the next active one.

**Budgets.** Every API request is counted per provider family and month in
*Sales Provider Usage*. *Monthly Provider Budgets* (Platform Settings) caps
each family; a request over budget is refused before it is sent, and the job
stops with code `provider_budget`. Browser bots are never chosen
automatically.

### Web search lead sources (Brave and Google)

These search the web for "keyword in location" (Brave's official API, or
Google through a provider or the browser bot) and turn each organic result
that is a business's own website into a lead. Social networks,
marketplaces, directories, news, government and reference sites are
skipped, and each domain counts once. The lead keeps the site's home page, a
name cleaned from the result title, and a phone number if the snippet shows
one. Website research then reads the site for emails, phones and evidence.

| Connector | How it searches | Needs |
| --- | --- | --- |
| `brave_place_search` | **Brave Place Search** (`/local/place_search`): local businesses with website, phone, email, address, rating and categories; up to 100 per request | Brave key; *Enable Brave Search* |
| `brave_llm_context` | **Brave LLM Context** (`/llm/context`): results with extracted page text, so phones and emails come from the page; local business entries too | Brave key; *Enable Brave Search* |
| `brave_web_search` | **Brave Search API** (official; own index, no scraping or CAPTCHAs; key in the `X-Subscription-Token` header; 20 results per request) | Brave key; *Enable Brave Search* (no Google responsibility tick) |
| `scrapingdog_google_search` | Scrapingdog Google Search API (JSON, 0-based `page`) | Scrapingdog key (same as Maps) |
| `scrapingbee_google_search` | ScrapingBee Google API (JSON; key in the Authorization header) | ScrapingBee key (same as Maps) |
| `serpapi_google_search` | SerpAPI `engine=google` (JSON, `start` offset) | SerpAPI key (same as Maps) |
| `google_search_browser_experimental` | **Experimental.** Headless Chromium types the search on google.com and follows *Next* | Same Playwright install as the Maps browser |

Brave is an official API, so it needs only *Enable Brave Search* and a key.
For the Google sources the same rules as Maps apply: each source is off until the vendor enables it
and ticks *I Accept Responsibility for Google Search Data Use*. Each tenant
connector needs *Source Policy Reviewed*. Search-derived fields are kept for
*Search Data Retention (Days)* unless the company's own website confirms
them. Google Search blocks automated browsers from server addresses faster
than Maps does, so use an API provider for regular runs. The browser bot
waits at least 3 seconds between result pages, caps each search at 50
results, declines Google's consent page like the Maps bot, and stops on a
CAPTCHA or "unusual traffic" page.

**Enrichment after discovery:**
- **Website finder.** When a listing has no website and ScrapingBee or
  Scrapingdog is enabled, a Google search for "business + city" finds the site. A result is
  accepted only if its domain shares a distinctive word with the business
  name; directories and social sites are skipped.
- **Website research** then extracts emails, phones, social profiles
  (Facebook, LinkedIn, Instagram, YouTube, X, TikTok, WhatsApp) and evidence
  for scoring.
- **AI extraction fallback** on the directory crawler: when a page has no
  schema.org data, Claude extracts the listings, ScrapeGraphAI/AgentQL-style
  but with the app's own Claude provider. A business is kept only if its name
  appears on the page, and a phone, email or website only if it appears there
  verbatim.

## Lead Finder Studio

`/desk/lead-finder` (sidebar: **Lead Finder Studio**; home: **Find Leads**) takes a user
from nothing to a running discovery job on one page, in four stages:

1. **Source:** icon cards for every connector, grouped by Google Maps, Web and
   Your data. Each card shows *Ready*, *Not enabled* (by your provider) or
   *Experimental*. Managers enable a source in one click after confirming they
   may use it; the directory crawler also asks for start URLs.
2. **Who to find:** saved or new targeting profiles. Keywords, buyer types (B2B
   segments), industries, needs, locations (`Area, City`) and exclusions are
   chips; press Enter to add one. **Suggest with AI** adds keywords, Bangla
   variants and buyer types for you to keep or remove.
3. **Campaign and schedule:**
   - leads per run, capped by your plan;
   - **Run now**, **Now + repeat** or **Schedule only**, Daily, Weekly or
     Monthly at a chosen time (server time; the scheduler checks hourly);
   - automatic website research, and AI-widened searches;
   - **Preview searches** shows the exact search list before anything runs.
4. **Launch and live progress:** a progress bar, searches done, new leads,
   duplicates skipped, researched leads, each search's status and the newest
   leads, refreshed every 3 seconds. If a job waits because no background
   worker is running, the page says so.

The page uses Reckon Aura's theme variables when the theme is installed and
Frappe's defaults otherwise, works in dark mode and on phones, and its text is
translatable (Bangla included). Jobs stuck in *Queued* for 30 minutes are
re-queued automatically.

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
- **Connectors.** Licensed business-data providers are not implemented yet.
  Extraction by the directory crawler and the experimental Maps browser
  depends on page markup that can change; check results per source.
- **Maps providers untested live.** SerpAPI, Scrapingdog and Apify responses
  were coded against their documentation and tested with recorded shapes,
  not against the live services.
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

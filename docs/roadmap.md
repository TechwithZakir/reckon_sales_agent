# Reckon Sales Agent: roadmap for new agents, telephony and social leads

Status: plan, October 2026. Nothing here is built yet. Facts about third-party products are as of
October 2026, with sources at the end. Re-check them before building; telecom rules in particular change.

---

## 1. More agents

Today the app runs five agents (Research, Content, Governance, Engagement, Analytics) under one orchestrator.
Every new agent below plugs into the same orchestrator and autonomy matrix (`agents/policy.py`).
It plans "do" steps it may run alone and "ask" steps for the Needs-you inbox, and it reports in the daily
digest. The table is in suggested build order.

| # | Agent | What it does | Runs alone | Needs a person | Effort |
|---|-------|--------------|------------|----------------|--------|
| 1 | **Meeting agent** | When a lead says "interested" (call or reply), it proposes demo slots from the salesperson's calendar. It books the meeting, sends reminders and follows up a no-show. | Proposing slots, reminders to your own team | Sending the invitation to the customer (an outbound message) | M |
| 2 | **Deal coach** | Watches CRM deals: flags deals stuck in a stage and suggests the next best action. Drafts the proposal from approved facts and records win and loss reasons. | Nudges, drafts, loss-reason summaries | Sending proposals; any price or discount | M |
| 3 | **Signals agent** | Re-checks approved and CRM accounts weekly for buying signals: hiring, a new depot or branch, tenders on e-GP, a new brand distributorship. It re-scores the account and starts outreach when a signal appears. | Monitoring, re-scoring | Starting a new campaign | M |
| 4 | **Customer-success / upsell agent** | Uses the Reckon Distribution and Accounts data on the same site (customers who already run Reckon) to spot upsell and renewal moments and to ask happy customers for referrals. | Spotting, drafting | Any customer message | M |
| 5 | **Voice agent** | After a recorded call (see section 2), it transcribes the call and summarizes it into the CRM. It suggests the outcome and coaches on the script. | Transcripts, summaries, suggested outcome | The outcome stays the salesperson's click | L (needs telephony) |
| 6 | **Data-quality agent** | Merges duplicates, normalizes Bangladeshi phone numbers, cleans bounced and wrong numbers, and enforces retention. | All of it (reversible) | Hard deletes (never automatic) | S |
| 7 | **Competitor agent** | Tracks named competitors (e.g. Sokrio, DATABIZ, Mediasoft) for launches, pricing and clients from public web sources. It keeps a battlecard that call scripts and emails may quote, after approval. | Research, battlecard drafts | Approving battlecard facts | S |
| 8 | **Compliance agent** | Keeps consent, opt-outs and do-not-call status consistent across email, SMS, WhatsApp and calls. It checks calling hours and audits sent messages against approved facts. | Checks, blocking | Changing a suppression | S |
| 9 | **Forecast agent** | Builds a weekly pipeline and revenue forecast from deal probabilities and history, with a confidence range. | All of it (read only) | — | S |

**Recommended next:** build the Meeting agent (1) first, because "interested" currently ends at a CRM task. Then the
Deal coach (2) and the Data-quality agent (6).

---

## 2. Telephony: SIP calls for Bangladesh and abroad

### What Frappe CRM already has

- Frappe CRM has built-in telephony for **Twilio** (in-browser calling through a TwiML app, an incoming-call webhook
  and recordings) and **Exotel**. Calls are stored as **CRM Call Logs** with notes and recordings.
  - Twilio webhooks: `/api/method/crm.integrations.twilio.api.twilio_incoming_call_handler` (incoming) and
    `/api/method/crm.integrations.twilio.api.voice` (outbound TwiML).
- A separate Frappe **Telephony** app provides a provider-neutral call log (from/to, status, duration, direction,
  recording URL, linked document).
- **There is no SIP, Asterisk or FreeSWITCH integration.** Community threads ask for it, and one developer has
  proposed an Asterisk-first VoIP app, but nothing is released.

### The Bangladesh constraint

- Domestic IP telephony is licensed by the BTRC as **IPTSP**. Only ISP licence holders may hold one, and licences are
  cancelled when the ISP licence lapses. IPTSPs issue the **09-series numbers** (for example 0966…, 0961…) and
  offer **SIP trunks** to businesses.
- International voice into Bangladesh must pass through licensed gateways (IGW and ICX). Using an unlicensed
  "grey route" to reach Bangladeshi numbers is illegal and causes call blocking. That means:
  - **Bangladeshi numbers:** call through a **local IPTSP SIP trunk**.
  - **International numbers:** call through **Twilio** (already supported by Frappe CRM) or an international SIP
    carrier.

### Proposed architecture

```
Agent Studio / CRM (browser)
   │  WebRTC softphone (JsSIP or SIP.js over WSS), click-to-call from a call task
   ▼
PBX: Asterisk (or FreeSWITCH), hosted in Bangladesh
   │  routes by prefix: +880 → local IPTSP SIP trunk (09-series caller ID)
   │                   other → international trunk (Twilio Elastic SIP or another carrier)
   │  recordings, IVR, queues, voicemail
   ▼  events (Asterisk ARI) → Frappe webhook (signed)
Frappe: CRM Call Log + Sales Agent call outcome → the agents' next step
```

- **New app or module, `reckon_telephony`:** a provider adapter that writes **CRM Call Logs** like Frappe's own Twilio
  integration does, so the CRM's call history and recordings work unchanged. Providers would be
  `asterisk_sip` (local IPTSP and international trunks), `twilio` (the CRM's own) and `phone_link` (today's tap-to-call).
- **Softphone:** a small panel in the Agent Studio's Calls card and on CRM leads. It registers per user (an extension
  for each salesperson) and handles click-to-call, mute, hold, transfer and DTMF. Calls get a screen pop on inbound.
- **Linking:** an inbound caller's number is looked up against prospects, CRM leads and contacts, and the call rings the
  assigned salesperson first. After the call, the outcome buttons appear in the call panel.

### Phases

1. **Click-to-call and logs.** Outbound calls from a call task, a CRM Call Log with the recording, outcome buttons on
   the call screen, and least-cost routing (Bangladesh versus international).
2. **Inbound.** The IPTSP number rings the PBX: caller lookup and screen pop, routing to the owner or a queue,
   voicemail to a ToDo, and a missed-call callback task.
3. **Voice agent.** Transcription (Bangla and English), an AI summary to the CRM timeline, a suggested outcome, and
   script coaching.
4. **Power dialer.** The day's call tasks dialled one after another, within calling hours (09:00–20:00 Bangladesh time)
   and respecting do-not-call lists.

### Compliance checklist

- Use a **BTRC-licensed IPTSP**; get its licence number and the number allocation in writing.
- Play a call-recording notice ("this call may be recorded") and keep recordings under the retention policy.
- Respect do-not-call and opt-outs (the suppression list already covers this) and calling hours.
- Calls to other countries follow that country's rules (for example US TCPA and EU GDPR).

### Decisions needed from you

- The IPTSP to use. Ask for a SIP trunk with a 09-series DID, the per-minute rates to mobiles, and the channel count.
- PBX hosting: a managed Asterisk/FreePBX in Bangladesh, or your own server.
- The number of salespeople calling at once (sets the trunk channels and server size).

---

## 3. Leads from LinkedIn and Meta

### Meta (Facebook and Instagram Lead Ads)

- **Frappe CRM already syncs Facebook and Instagram lead forms** (Settings → Lead Syncing, beta). It fetches pages and
  forms with a Meta access token, maps form fields to CRM Lead fields, syncs on a schedule or with "Sync Now", and
  records failures with "Retry Sync". **Use it rather than rebuilding it.**
- **Gap 1 is tenancy, and it must be fixed first.** Synced CRM Leads are created by a background job with no Company,
  so under this app's Company separation they are unowned and invisible to tenants.
  - Fix: a `Company` on each lead-sync source (a custom field), and `crm_tenancy` sets `rsa_company` on leads created
    by that source.
- **Gap 2 is speed to lead.** A synced lead should become a Sales Prospect immediately, with:
  - `consent_source` = "Meta lead form", since the person asked to be contacted;
  - research and AI triage;
  - an instant first reply (email, or WhatsApp if the form collected consent), from a template approved once;
  - a call task for the salesperson within minutes.

  Inbound leads go cold within the hour.
- **Later, real time:** Meta's `leadgen` webhook sends only the lead ID. The app then fetches the lead with
  `GET /{leadgen_id}`, or a whole form with `GET /{form_id}/leads`. This needs Meta app review for `leads_retrieval`,
  `pages_manage_ads`, `pages_manage_metadata` and related permissions, plus a long-lived Page token. Worth it once ad
  volume justifies near-instant response; until then the CRM's scheduled sync is enough.
- **Click-to-WhatsApp ads and Messenger:** conversations that start from an ad arrive through the WhatsApp Cloud API
  (the frappe_whatsapp app) with the ad referral. The engagement agent already handles WhatsApp replies and the
  24-hour window.

### LinkedIn

- **Lead Sync API** (official): `leadForms`, `leadFormResponses` and `leadNotifications`, the last being webhooks for
  new leads.
  - Lead types covered: `SPONSORED` (ads), `EVENT` (event pages) and `ORGANIZATION_PRODUCT` (product pages).
  - Reading leads needs the `r_marketing_leadgen_automation` scope, granted only after LinkedIn approves a separate
    access application.
  - The application needs a **verified Company Page**, approval by a Page super admin, and the right Campaign Manager
    or Page role for the user who connects. If it is rejected, you must re-apply with a new developer app.
- **Frappe CRM has no LinkedIn sync**, so we would build a `LinkedIn Lead Sync` connector in this app:
  - per-Company OAuth, with tokens in password fields;
  - a webhook receiver for `leadNotifications`, plus polling `leadFormResponses` as a fallback;
  - mapping into CRM Lead and Sales Prospect with the same speed-to-lead flow as Meta.
- **Not allowed, and not planned:** scraping LinkedIn or Facebook profiles, groups or search results, and automated
  connection requests or DMs. These break the platforms' terms and get accounts banned. Sales Navigator has no open
  API (partners only). Person-to-person LinkedIn outreach stays a human step: the existing "LinkedIn Task" campaign
  channel.

### Closing the loop with what exists

- The Social agent already publishes approved posts to Facebook Pages, Instagram and LinkedIn. Posts and ads that
  carry a lead form get a UTM and campaign tag, so leads they produce show up by source and campaign on the Campaign
  Analytics dashboard.

### Phases

1. **Meta via Frappe CRM's Lead Sync:** the Company fix, the Sales Prospect bridge, the speed-to-lead flow, and
   "Meta Lead Ads" as a source in analytics. *(S–M)*
2. **LinkedIn Lead Sync connector:** apply for access now, because approval takes time; build while waiting. *(M)*
3. **Meta real-time webhooks and Click-to-WhatsApp attribution.** *(M)*

---

## Sources

- Frappe CRM Twilio: https://docs.frappe.io/crm/twilio · Exotel: https://docs.frappe.io/crm/exotel ·
  Telephony app: https://cloud.frappe.io/marketplace/apps/telephony · Integrations: https://frappe.io/crm/integrations
- Frappe and Asterisk (community, not released): https://discuss.frappe.io/t/frappe-voip-asterisk/135295 ·
  https://discuss.frappe.io/t/integration-with-asterisk-pbx-server/32316
- BTRC IPTSP guideline: https://lims.btrc.gov.bd/uploads/service_guideline/IPTSP%20Guideline.pdf ·
  IPTSP licences cancelled: https://www.thedailystar.net/business/telecom/news/4-ip-telephony-service-providers-lose-licences-3426271 ·
  Example IPTSP 09-series offer (vendor claim): https://fionetix.com/services/ip-telephony/
- Frappe CRM Meta lead syncing: https://docs.frappe.io/crm/lead-syncing/meta.md · https://frappe.io/crm/lead-capture
- Meta lead webhooks: https://developers.facebook.com/docs/graph-api/webhooks/getting-started/webhooks-for-leadgen ·
  Retrieving leads: https://developers.facebook.com/docs/marketing-api/guides/lead-ads/retrieving
- LinkedIn Lead Sync: https://learn.microsoft.com/en-us/linkedin/marketing/lead-sync/leadsync ·
  Access: https://learn.microsoft.com/en-us/linkedin/marketing/lead-sync/getting-access-leadsync

# Campaign Studio

One place to plan, run and learn from email, SMS and WhatsApp campaigns. It has its own group in the Sales Agent
menu (**Campaign Studio**) and its own page (`/desk/campaign-studio`).

## The flow

1. **Template**: build the message for each channel on **Message Templates** (a block builder for email, a counter for
   SMS, Meta's components for WhatsApp). A manager approves it.
2. **Audience**: say who it goes to (see below).
3. **Campaign**: pick the audience and the approved templates, with the days to wait between steps. It is created as a
   draft.
4. **Approval**: a person submits and approves the campaign. This is the one human decision for the whole sequence.
5. **Run**: the engine drafts each step when it is due, checks every safety rule, sends, and records what happens.
6. **Learn**: opens, clicks, replies, bounces and opt-outs flow into the funnel, each person's timeline and the copilot's
   suggestions.

## Audiences

| Kind | Who is in it | Filters |
|---|---|---|
| Prospects | Approved Sales Prospects | fit score, city, industry, source |
| CRM Leads | Leads in Frappe CRM | status, source, owner |
| CRM Contacts | Contacts in Frappe CRM | none |
| Customers | The person behind a won deal | none |
| Specific people | A list you pick | records from any of the above, or just a name with an email or phone |

* Rule-based audiences are read again each time they are used, so **Add new people** on a campaign picks up anyone who
  now matches.
* People are merged by email and phone, so nobody is contacted twice.
* Everyone becomes a **Sales Prospect**, so consent, opt-outs and the suppression list work the same for all of them.
  A person who is not a prospect yet becomes one (approved, because a person chose them). An existing prospect is never
  re-approved, and one marked do-not-contact is never changed.
* Every query is limited to the Company. A record of another Company is ignored, even when picked by hand.
* **SMS and WhatsApp permission** is never assumed. If the people agreed (for example at an event), tick the boxes on
  the audience and say how they agreed; that statement is stored on each prospect and logged. Without it, SMS and
  WhatsApp steps skip them.

## Tracking

* **Email**: every link is replaced by a short tracked link, and a 1x1 image records opens.
* **SMS and WhatsApp (free text)**: every link is replaced by a short tracked link. A WhatsApp *template*'s wording is
  fixed by Meta, so its links are not tracked.
* The message stored in the database is never changed; only the copy that goes out is. What a person approved is what is
  stored.
* A tracked link only ever leads to the address stored with it (it is not an open redirect), and the code carries no
  personal data.
* WhatsApp **delivered** and **read** receipts are recorded when the `frappe_whatsapp` webhook reports them.
* Email **bounces, spam reports and unsubscribes** come from the provider's webhook (SendGrid, Brevo) and stop the
  sequence and add the address to the do-not-contact list.
* **Opens are approximate.** Some mail apps load images in advance (Apple Mail), and some security tools open links.
  Visits that identify themselves as scanners, previews or scripts are counted apart and never become events. Clicks and
  replies are the stronger signals; the engagement score counts them more.
* Every event is stored against the message, the campaign and the person, so any campaign can be traced back from a
  prospect (**Campaign history** on the prospect form, or **Recipients** in the Studio).

### Engagement score

Per person, 0 to 100: an open adds 2 (up to 3 opens), a click 5 (up to 3), a read 2, a reply 10, an interested reply 15,
a meeting request 20. A bounce takes off 10, an unsubscribe 20, a spam report 30. **Hot** is 15 or more, **Warm** is 5
or more, and anyone who unsubscribed or complained is **Opted out**.

## Copilot and autopilot

The **copilot** reads the numbers and suggests: a campaign with too many bounces, low opens, opens without clicks, people
who are showing real interest, the hours people open, an SMS that needs too many parts, and approved prospects that are
not in any campaign. It does not change anything. Small samples are not judged.

The **autopilot** has three levels, per Company, set in the Studio by a manager (default **Off**):

| Level | What the agent may do |
|---|---|
| Off | Nothing on its own. A person approves every message. |
| Assist | Suggests, and creates an internal call task for a person who clicked more than once. A person approves every message. |
| Auto-send | After a person approves a campaign, its messages go out without a second click. |

Auto-send only applies when the campaign is **Active**, was approved by a person, and its **content check passed**. It
never overrides: opt-outs and the suppression list, missing consent, the kill switch, the outbound switch, the daily
limits, the sending window, the WhatsApp 24-hour rule, or a change to the campaign after approval (which needs approval
again). Every auto-approval is written to the audit trail.

The **sending window** (for example `09:00-20:00`, server time) is optional. Outside it, approved messages wait.

## Deploying

Run `scripts/deploy.sh` as usual. The migration adds the new doctypes and settings. Three things change on a live site:

* **Tracking starts on** for existing Companies (the two switches default on). Switch them off in the Studio, under
  Copilot & Autopilot, if you do not want it.
* The route `/l/<code>` is new, so clear the cache (the script does).
* The sidebar is regrouped: Message Templates, Campaign Analytics, Campaigns, Messages, Members, Events, Insights and
  the Suppression List now sit in the **Campaign Studio** group.

## Not built yet

* A/B testing of subject lines and content.
* Branching journeys (a different next step for people who clicked, or did not open).
* One-off scheduled sends outside a campaign sequence.
* Per-person send-time optimisation (the copilot only suggests a window for the whole campaign).
* SMS delivery receipts (SMS is measured by clicks and replies).
* Messenger and Instagram campaigns: Meta only allows replies inside its 24-hour window, so these stay conversations.
* WhatChimp template sending, and Brevo opens and clicks (Reckon tracks those itself, whichever provider sends).
* The campaign history panel inside the `/crm` app (it is on the prospect form and in the Studio).

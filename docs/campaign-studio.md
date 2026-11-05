# Campaign Studio

One place to plan, run and learn from email, SMS and WhatsApp campaigns. It has its own group in the Sales Agent
menu (**Campaign Studio**) and its own page (`/desk/campaign-studio`).

## The flow

1. **Template**: build the message for each channel in the template builder (see below). A manager approves it.
2. **Audience**: say who it goes to (see below).
3. **Campaign**: the campaign wizard has four steps: **Setup** (name, goal, language, offer), **Audience**, **Content**
   (an approved template for each step, with the days to wait, and each template's pre-send checks) and **Schedule and
   review** (start date, daily limit, an optional pilot). It is created as a draft, or created and submitted for approval.
4. **Approval**: a person submits and approves the campaign. This is the one human decision for the whole sequence.
5. **Run**: the engine drafts each step when it is due, checks every safety rule, sends, and records what happens.
6. **Learn**: opens, clicks, replies, bounces and opt-outs flow into the funnel, each person's timeline and the copilot's
   suggestions.

## Template builder

**Message Templates** is a library of templates and a builder with three panes: **Blocks, Fields and Templates** on the
left, the editor in the middle, and the AI panel, agent actions and pre-send checks on the right.

* **Channels.** Email, SMS, WhatsApp and LinkedIn, each with its own editor and phone or email preview.
* **Email blocks.** Heading, text, image, button, columns, divider, product card, dynamic content, signature and social
  links. Drag them in, or click; move, duplicate, rewrite with AI or delete the selected block; save a block as a section to
  reuse. The email is plain, email-safe HTML with a plain-text version.
* **Fields with fallbacks.** `{{first_name|there}}`: the word after the bar is used when a person has no value, so nobody gets
  a blank greeting. Fields: business name, city, industry, website, first name, full name, sender, record owner, company,
  offer and the AI opening line. A pre-send check lists any field without a fallback.
* **Dynamic content.** A block that shows one paragraph to people matching a rule (for example industry contains pharma) and
  another to everyone else. The rules never reach the customer; every alternative is content-checked.
* **SMS.** GSM-7 or Unicode part counting, an opt-out line, sending hours, and a phone preview.
* **WhatsApp.** Category, header (none, text, image or document), body with Meta's rules, sample values for each variable,
  footer and buttons (quick replies, or a link and a phone). Approving submits it to Meta through `frappe_whatsapp` with the
  numbered variables, header, footer, samples and buttons. A sample image or document still has to be attached on the
  WhatsApp Template in Frappe, and the page says so.
* **LinkedIn.** A message a person sends: as a campaign step it becomes a task, never an automatic message.
* **A/B subject lines.** Up to two alternative subjects. The campaign gives each person one (the same one every time), and
  the campaign page shows opens, clicks and replies per subject. The copilot says when one is clearly ahead.
* **AI drafting.** A brief, a goal and a tone become a first draft for the channel, from approved knowledge only, with three
  subject suggestions for email. Rewrite a block, or make an SMS or WhatsApp message shorter or Bangla. Undo restores the
  previous content. Nothing is saved or sent by the AI.
* **Autosave and approval.** Changes are checked as you type and saved a moment later. A template is a draft until a manager
  approves it; editing an approved template sends it back to draft.
* **Preview and test.** Preview in a sandbox with sample values (desktop or mobile). **Send test** emails the template to the
  signed-in person only.
* **Checks.** What stops approval (a missing subject, a link that is not https, a rule with no value, a placeholder such as
  `[BOOKING LINK]` still to fill) is listed above the editor. Advice before a send (footer address, subject length, fallbacks,
  alt text, a button) is the pre-send list.
* **Agent actions.** Only *personalize each message from CRM data* is a switch, because it is the one that works today.
  Interested replies always create a task for the owner. Best-time sending and automatic follow-ups are shown as not
  available yet.

Older templates open in the builder too: their text becomes one block.

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

* A/B testing of anything except the subject line, and picking a winner automatically.
* Branching journeys (a different next step for people who clicked, or did not open).
* One-off scheduled sends outside a campaign sequence.
* Per-person send-time optimisation (the copilot only suggests a window for the whole campaign).
* SMS delivery receipts (SMS is measured by clicks and replies).
* Messenger and Instagram campaigns: Meta only allows replies inside its 24-hour window, so these stay conversations.
* WhatChimp template sending, and Brevo opens and clicks (Reckon tracks those itself, whichever provider sends).
* The campaign history panel inside the `/crm` app (it is on the prospect form and in the Studio).

## Sending pace, spam protection and Brevo

Bulk mail that leaves in a burst looks like spam, so every Company's Email, SMS and WhatsApp go out at a pace
(Integrations, **Email** and **Brevo** panels, "Sending pace"):

- **Seconds between messages** (default 45) with **variation** (default 40%): each message waits its own, repeatable
  length, so the rhythm is not mechanical. 0 turns the gap off.
- **Messages per hour, per channel** (default 30; 0 = no hourly cap). The daily limit, warm-up, sending window and
  allowlist still apply on top.
- A job runs every ten minutes, one per Company, and sends approved messages one at a time at that pace. A message that
  is too soon, or in a full hour, simply waits (approved) for the next run. Dry runs, internal tasks and replies to
  people who wrote to us are never delayed.

Every campaign email carries `List-Unsubscribe` and `List-Unsubscribe-Post: List-Unsubscribe=One-Click` (RFC 8058), as
Gmail and Yahoo expect from bulk senders. Brevo and SendGrid get them in the API request; mail through the site's own
Email Account gets them added in the Email Queue. A POST to the link unsubscribes without a page.

**Brevo free plan.** Each business signs up for its own free account (300 emails a day), verifies its sender address and
pastes the API key. "Emails per day" in the Brevo panel (default 300) lowers the Company's daily email limit to match
the plan; raise it after upgrading in Brevo, or set 0 for no cap. Accounts and limits are never shared between businesses.

### Live test plan (3 to 5 addresses you own)

1. Use a campaign with approved messages to your own addresses and turn on a gap of 20 seconds.
2. Watch the messages' `sent_on`: roughly 14 to 28 seconds apart, never in one second.
3. In the received email, open "Show original" and check `List-Unsubscribe` and `List-Unsubscribe-Post`; in Gmail
   the "Unsubscribe" link shows beside the sender.
4. Open the email and click a link: the open and click appear on the recipient's timeline and the campaign funnel.
5. Reply and unsubscribe from one address: the member stops, the address is suppressed, nothing more is sent to it.

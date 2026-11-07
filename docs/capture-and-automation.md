# Capture Studio and Automation Studio

Three things on top of Campaign Studio: **lead capture** (signup forms), **segments, tags and CSV import**, and a visual
**automation** editor. All of them work for a Company's own people only, and none of them can message anyone the campaign
rules would not.

## Signup forms (Capture Studio → Forms)

A form is embedded in a website, shown as a popup, or shared as a page of its own at `/f/<key>`.

* **Fields:** email (always), first and last name, phone, company, city, industry. Labels and "required" are yours.
* **Agreement:** a tick box with your own wording. SMS and WhatsApp opt-ins are separate boxes, offered only if you turn them on.
* **Double opt-in (default):** the person gets one confirmation email and is *not* emailed by any campaign until they click it.
  The link opens a page with a button; only the button confirms, because mail scanners open links in advance.
* **Consent record:** every signup stores "Signup form '<name>' (<key>) on <date>" on the person.
* **Tags:** each form adds the tags you list, so segments and automations can start from them.
* **Embed:** paste `<script src="https://YOUR-SITE/assets/reckon_sales_agent/js/rsa_form.js" data-form="KEY" defer></script>`.
  The form is drawn in a shadow root, so it never breaks or changes the website's styles. A popup opens after a delay, on
  scroll or on exit intent. The address in the snippet is the domain you opened Capture Studio on.
* **Safety:** visitors are untrusted. Values are trimmed and length-limited, a hidden field catches bots, signups are limited per
  form and per address, and a person who opted out before gets the same "thank you", so a form cannot reveal who opted out.
  "Websites that may show this form" limits which sites can use it (empty: any).

## Segments, tags and import

* **Segment:** saved rules, "match ALL / ANY": joined, opened, clicked, replied or was sent something (in the last / not in the
  last / never), tag, city, industry, source, fit score, has email or phone, agreed to SMS or WhatsApp, email confirmed,
  engagement (Hot, Warm, Cold). A segment is checked every time it is used, so it is always current. It can be a campaign
  audience (audience type "Segment") and can start an automation. "Tag everyone in it" tags a segment in one go.
* **Tags:** short lowercase labels on a person (`vip`, `renewal-2026`). Added by forms, imports, automations, segments or by hand.
* **Import:** a CSV (comma, semicolon or tab separated) with columns mapped by you. You must state how these people agreed to
  hear from you; the statement is stored on each person. People on the suppression list are left out, people marked
  do-not-contact are never changed, existing people are only filled in, and repeats in the file are merged. The job runs in the
  background with progress, and the file is removed when it is done.

## Automations (Automation Studio)

A flow of steps people move through. Start from a ready-made flow (welcome series, re-engage quiet readers, nurture then hand to
sales) or from a blank trigger. Click **+** between steps to add one; the editor has zoom, fit, a top-to-bottom or left-to-right
layout, live problem checking, a simulator (follow one person through the flow, nothing is sent) and per-step numbers.

| Step | What it does |
|---|---|
| **Trigger** | Someone signs up on a form (optionally one form) · a tag is added · someone joins a segment · a CRM deal changes stage · someone replies · your system calls the API · you enrol people by hand |
| **Send** | An approved Email, SMS or WhatsApp template |
| **Wait** | Minutes, hours or days |
| **Condition** | Yes or No: opened, clicked or replied to a message in the flow (it waits up to N days for the event before saying No), has a tag, is in a segment, has confirmed their email |
| **Action** | Add or remove a tag · create a CRM task · notify the owner · set the city or industry · stop |
| **Webhook** | POST the person's id, email, phone, name and tags to an https address (signed with the automation's secret, header `X-Reckon-Signature`) |

**How it stays safe**

* An automation owns a hidden campaign, so a *Send* step goes through exactly the campaign path: approval, suppression and
  consent, the sending window, daily and hourly limits, pacing, unsubscribe link and headers, and tracking. The message is first
  written as a draft; autopilot decides whether a person approves it.
* **Switching on is the approval** of everything the automation will send (like approving a campaign) and needs a manager.
  **Changing the flow switches it off** until it is checked and switched on again.
* A person who opts out, is marked do-not-contact, unsubscribes or bounces leaves the flow. A reply stops the person too, unless
  "Stop for anyone who replies" is turned off (then a Condition can branch on the reply).
* A step a person cannot receive (no SMS opt-in, no confirmed email) is skipped, like in a campaign.
* Webhooks go to public addresses only, never follow redirects, and a failed call never stops the person.
* An automation that starts on a segment checks it every half hour; waits and message sends are checked every five minutes.

**Start it from your own system:** call `reckon_sales_agent.api_automation.trigger` with an API key and secret of a Sales Agent
manager: `automation`, `email` or `phone`, `name`, and `consent_statement` (how the person agreed; stored on the person).

## Live test plan

1. Capture Studio → Forms → New form (keep double opt-in) → Publish → open `/f/<key>`, sign up with an address you own.
2. You get one confirmation email; before clicking it the person shows "Unconfirmed" and receives nothing else. Click, then the
   page says you are confirmed, and the person has the form's tags.
3. Segments → New segment "Signed up this month" (joined in the last 30 days) → the count includes you.
4. Import a CSV of three addresses you own (state the agreement) → numbers match; import it again → "already known".
5. Automation Studio → "Welcome series": choose an approved email template in both Send steps → fix any problems shown → Simulate
   both ways → Switch on. Sign up again with another address you own: the first email appears as a draft in Messages. Approve
   it; it is sent at the pace you set, and the person moves on after the wait.

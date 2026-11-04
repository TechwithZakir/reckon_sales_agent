# Go-live checklist: the first pilot

This checklist takes the Sales Agent from dry run to a controlled pilot on distribution.reckon.tech.
- **Pilot:** CAMP-00472 (pharma distributors), phone-first, with email follow-ups, for two weeks.
- **Rule for every phase:** finish it before the next one; nothing in a later phase is safe without the earlier
  ones.
- **Owners:**
  - **You:** the system provider or the Company admin.
  - **Sales:** the salesperson who takes the calls.
- **Settings paths:** "Settings" means Sales Agent Settings for the Company. "Integrations" means
  `/desk/sales-channels`.

---

## Phase 0: before you start

| ✓ | Step | Owner | Done when |
|---|------|-------|-----------|
| ☐ | The latest code is deployed: pull, `bench migrate`, `bench build`, `sudo supervisorctl restart all` | You | The Integrations page and Agent Studio load without errors |
| ☐ | CI is green on the deployed commit (GitHub → Actions) | You | Every job passed, including "Install, migrate and smoke-test on Frappe v16" |
| ☐ | Take a database backup: `bench --site distribution.reckon.tech backup --with-files` | You | The backup files exist under `sites/…/private/backups` |
| ☐ | Rotate the ScrapingBee key that was shared in chat earlier | You | The old key is revoked in ScrapingBee, and the new key is in its Lead Source |
| ☐ | AI works | You | Agent Studio shows "AI on", and the "AI is paused" card does not appear |

## Phase 1: who you are and who answers

| ✓ | Step | Owner | Done when |
|---|------|-------|-----------|
| ☐ | Get started page (`/desk/sales-setup`) is at 100% | You | Business profile, approved facts, segments and team are all ticked |
| ☐ | **Approved knowledge** covers what leads ask: products, delivery areas, how to order, prices you are willing to quote (category Pricing or Offer) | You | 10 or more approved items; the AI only ever states these |
| ☐ | Settings → **Sender Name** and **Postal Address for Email Footer** are set | You | A test email (Phase 4) shows both |
| ☐ | Agent Studio → autopilot settings → **Give calls and follow-ups to** the salesperson | You | The salesperson's email is saved |
| ☐ | Integrations → **AI autopilot & team** → people who answer conversations, and "share automatically" on | You | The salesperson is listed |
| ☐ | Settings → **Calling hours** = `09:00-20:00` | You | Saved |
| ☐ | The salesperson has a Frappe user, the Sales Agent User role and a mobile number in their profile | You | They can open Agent Studio and Conversations |

## Phase 2: email that lands in the inbox

| ✓ | Step | Owner | Done when |
|---|------|-------|-----------|
| ☐ | **Fix SPF** for reckon.tech: one SPF TXT record ending in `~all` or `-all`, with at most 10 DNS lookups. The Facebook verification string moves to its own TXT record. | You (DNS) | Integrations → Email → Check email health shows SPF ✓ |
| ☐ | **DKIM** for the sending service is published | You (DNS) | Email health shows DKIM ✓ |
| ☐ | **DMARC** exists. Keep `p=none` for the pilot and add a `rua=` address to receive reports. | You (DNS) | Email health shows DMARC ✓ |
| ☐ | **Sending:** an outgoing Email Account in Frappe (default outgoing), or Integrations → Twilio SendGrid with an API key, a verified from address and the signed Event Webhook | You | The Integrations Email tile is green |
| ☐ | Settings → **Warm up the sending domain** on: 20 on day one, +20% a day | You | Saved. Leave it on for the whole pilot. |

## Phase 3: channels for the pilot

Keep the first pilot small: **calls + email + website chat**. Add the others when Phase 7 says so.

| ✓ | Step | Owner | Done when |
|---|------|-------|-----------|
| ☐ | **Calls.** Either keep "Phone (tap to call)", or set up Integrations → Twilio (calls) or Office phone (Asterisk) | You | Pressing "Call via office phone" on a test task rings the salesperson (Phase 4) |
| ☐ | If calls are recorded: play a recording notice, and the system provider turns on Call transcription | You | A test call shows a "Call summary" note on its CRM call log |
| ☐ | **Website chat.** Integrations → Website chat: turn it on, list `https://reckon.tech` (and `www.`), and paste the script tag into the site | You | The chat bubble shows on reckon.tech |
| ☐ | Optional: **SMS** (Integrations → SMS, with your gateway key and approved sender ID) | You | A test SMS arrives (Phase 4) |
| ☐ | Later (long lead time): **Meta app** business verification and app review; LinkedIn Community Management and Lead Sync access | You | Start now; connect only after approval |

## Phase 4: dress rehearsal (real sending, only to yourselves)

Turn on **safe mode**: real sending, but only to the addresses you list.

| ✓ | Step | Owner | Done when |
|---|------|-------|-----------|
| ☐ | Settings → **Only send to the allowlist** ON. **Allowlist**: your own and the salesperson's emails and phones (one per line; `@yourdomain` allowed) | You | Saved |
| ☐ | Settings → **Outbound Sending Enabled** ON. **Human Approval Required** stays ON. | You | The Agent Studio pill no longer says "Dry run" |
| ☐ | Create a test lead with your own email and phone. Approve one email and one reply from Conversations. | You | Both arrive, with sender name, postal address and a working unsubscribe link |
| ☐ | Click the **unsubscribe** link in the test email | You | The lead is marked do-not-contact, and later drafts are cancelled |
| ☐ | Text **STOP** to the SMS number (Twilio only) | You | The number goes on the do-not-contact list |
| ☐ | Write on the **website chat** from a phone | You | The conversation appears in Conversations, is assigned to the salesperson, and the AI draft waits for approval |
| ☐ | **Call** the test lead from a call task, then log an outcome | Sales | The outcome creates the next step (callback task, CRM lead, or stop) |
| ☐ | Press **Send me today's digest** in Agent Studio | You | The digest email arrives |
| ☐ | Delete nothing: **cancel** the test messages and leads, or set them aside | You | The pilot numbers start clean |

## Phase 5: launch the pilot

| ✓ | Step | Owner | Done when |
|---|------|-------|-----------|
| ☐ | Open **CAMP-00472**. Check **pilot mode**, **hold-out %** (10–20%), **pilot max members**, **daily limit** (15–20) and **end date** (two weeks) | You | The values are set |
| ☐ | Read every step of the sequence. The content check shows no issues, and no price or claim is missing from approved knowledge. | You | The content check says "Passed" |
| ☐ | The pilot needs **at least 30 contacted and 10 held out** for a verdict. If it is smaller, add approved leads first. | You | Member counts meet this |
| ☐ | Settings → **Only send to the allowlist** OFF (real leads now). Keep the **daily message limit** at 50 or less. | You | Saved |
| ☐ | Approve and launch CAMP-00472 in Agent Studio | You | The campaign is Active and the first call tasks appear |
| ☐ | **Autopilot** stays OFF for week 1. In Conversations, the AI mode is "AI suggests, we send". | You | The Agent Studio pill says "Autopilot off" |

## Phase 6: daily routine during the pilot

| ✓ | When | Step | Owner |
|---|------|------|-------|
| ☐ | 08:00 | Read the **daily digest**: what the agents did, and what waits for you | You |
| ☐ | Morning | Agent Studio **Needs you**: approve messages, review leads, check the AI's suggestions | You |
| ☐ | Morning | **Calls and follow-ups**: use "Start calling" (power dialer) or the tap-to-call links, and log every outcome | Sales |
| ☐ | All day | **Conversations**: reply within 15 minutes (reminders fire after that), and resolve finished threads | Sales |
| ☐ | Evening | Check that bounces and complaints are at zero (Campaign Analytics) | You |

## Phase 7: weekly review and go/no-go

Review on Campaign Analytics, the pilot card on CAMP-00472, and the Channels card.

| Measure | Healthy | Stop and fix |
|---|---|---|
| Email bounce rate | under 2% | over 5%: pause; clean the data (Data Quality agent) |
| Spam complaints | 0 | any: pause, read the message, tighten the content |
| Unsubscribes | under 1% | over 2%: rewrite the offer or the segment |
| Calls reached | over 40% | under 20%: check numbers and calling times |
| Positive replies or interested calls | rising each week | none after week 1: change the segment or the offer |
| Median time to answer a chat | under 15 minutes | over 60 minutes: add a second person or turn on autopilot |
| Pilot verdict (Analytics agent) | "scale" with confidence | "stop": pause the campaign |

**Turn more on after week 1, one at a time, only if the table is healthy:**
1. **Autopilot** (Agent Studio): the agents find, judge and approve leads, and draft campaigns. Launching and
   sending still wait for you.
2. **AI autopilot replies on chats** (Integrations → AI autopilot & team): routine answers go out at once, and the
   rest goes to a person.
3. **WhatsApp**, **SMS**, then **Meta** (comments, Messenger, lead ads) once they are approved.
4. A second campaign, or a wider audience. Scaling is an approval in Agent Studio.

## If something goes wrong

| Situation | Do this | Where |
|---|---|---|
| Anything looks wrong with outbound | **Pause All Outbound Activity** (kill switch). Approved messages wait; nothing is lost. | Settings |
| One campaign misbehaves | **Pause the campaign** | Agent Studio or the campaign form |
| A channel misbehaves | Turn the channel off on its Integrations panel | Integrations |
| The AI says something wrong | Set that conversation's AI to "Human only", and fix or retire the knowledge item | Conversations, Knowledge |
| A complaint arrives | It already suppresses the sender. A person answers it in Conversations. | Conversations |
| Back to safety | **Outbound Sending Enabled** OFF (dry run): everything is recorded, nothing is sent | Settings |

Never delete records to undo something: cancel, pause or set aside, so the audit trail stays complete.

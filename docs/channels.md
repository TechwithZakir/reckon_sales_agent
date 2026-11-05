# Channels: chats, social accounts and the AI provider

All of these use the platforms' own official APIs. Nothing is automated through a browser.

## Who sets what

| Setting | Where | Who |
|---|---|---|
| Default AI provider (Claude, OpenAI, local), keys and models | Sales Agent Platform Settings | System provider only |
| A Company's own AI provider, model, key or endpoint | That Company's Sales Agent Settings (permission level 1) | System provider only |
| Meta app and LinkedIn app | Sales Agent Platform Settings | System provider only |
| Connected Pages, Instagram and LinkedIn pages | Channels page (`/desk/sales-channels`) | The Company's admin or manager |
| Website chat | Channels page | The Company's admin or manager |

A Company's AI override applies only while "Use the AI set for each Company" is ticked in Platform Settings.

## Meta: Facebook Pages, Instagram and Messenger (system provider, once)

1. In Meta for Developers, create a **Business** app and add these products: **Facebook Login for Business**,
   **Messenger** and **Instagram** (Instagram API with Facebook Login).
2. Add this valid OAuth redirect URI:
   `https://<site>/api/method/reckon_sales_agent.api_channels.social_callback`
3. Add webhooks for the **Page** and **Instagram** objects:
   - Callback URL: `https://<site>/api/method/reckon_sales_agent.api_channels.meta_webhook`
   - Verify token: any long random text. Enter the same text in Platform Settings under "Webhook verify token".
   - Fields: `messages` and `messaging_postbacks`. For comment-to-chat, add `feed` (Page) and `comments`
     (Instagram).
4. In Platform Settings, enter the Meta app ID and app secret. The secret also verifies every webhook call
   (`X-Hub-Signature-256`).
5. Have these permissions approved in App Review, with Business Verification. Until then, only people with a
   role on the app can connect:
   - `pages_show_list`, `pages_read_engagement`, `pages_read_user_content`, `pages_manage_posts`,
     `pages_manage_metadata`, `pages_messaging`
   - `instagram_basic`, `instagram_content_publish`, `instagram_manage_messages`, `instagram_manage_comments`
   - `business_management`

When a Company clicks **Connect with Facebook**, it gets:
- every Page it manages, each with its own Page token;
- the Instagram professional account linked to each Page;
- each Page subscribed to the webhook, so messages reach Conversations.

**Messaging rules (Meta):**
- A chat always starts with the lead. The agent never messages anyone first.
- Replies go out as `RESPONSE` within 24 hours of the lead's last message. After that, the reply is cancelled
  with the reason. Call or email the lead instead.

## Fast answers (each Company, on the Channels page)

All three are off until the Company turns them on.

**Answer simple chat questions at once** (Messenger, Instagram, website chat only). The reply goes out without
approval only when all of these hold; otherwise it waits as a draft:
- the AI says every fact it used is in the approved knowledge, and that nothing needs a person (discounts,
  custom prices, credit terms, contracts, complaints, questions the knowledge does not answer);
- the content check finds no figure, offer or claim outside the approved knowledge;
- what the lead wrote is not a complaint or an opt-out;
- the lead is not suppressed and the kill switch is off.
Email and WhatsApp replies always wait for a person. While dry run is on, these answers are recorded, not sent.

**Answer buying comments with a private message.** A comment on the Company's Facebook or Instagram posts that
asks to buy or for details ("price?", "দাম কত?", "inbox plz") opens a conversation, and the AI drafts one private
reply. Meta allows one private reply per comment, within 7 days. Other comments are ignored. When the person
then writes back in Messenger, Meta gives them a different ID, so that chat may appear as a second lead; Data
Quality's duplicate check can merge them.

**Reminders.** When a chat waits longer than the set minutes (15 by default), the salesperson named in the
autopilot settings gets a notification, once per message. The Agent Studio's Conversations lane shows the
median minutes to answer a chat this week.

## LinkedIn company pages (system provider, once)

1. Create an app at LinkedIn Developers and request the **Community Management API**.
2. Use the same redirect URI as for Meta.
3. In Platform Settings, enter the client ID and client secret.

**What connecting does:**
- Scopes requested: `w_organization_social`, `r_organization_social`, `rw_organization_admin`.
- The pages connected are the ones the person administers.
- Tokens last 60 days. A daily job refreshes them when LinkedIn issued a refresh token. Otherwise the account
  shows an error a week before the token ends, asking the Company to reconnect.

## WhatsApp

WhatsApp uses the official WhatsApp Business Cloud API through the Frappe WhatsApp app (`frappe_whatsapp`).
- A message from a known lead opens a conversation, even when the lead is not in a running sequence.
- Free-form replies are possible within 24 hours of the lead's message. After that, the reply needs an approved
  template.

## Website chat (each Company)

1. On the Channels page, tick "Show the chat on our website" and list your websites.
2. Paste the script tag shown there into your website.

**How the chat behaves:**
- Visitors write and leave an email or phone number.
- With autopilot on, the AI drafts the answer at once. A person approves it, and the visitor sees it in the chat.

**Safety:**
- The widget sends no cookies.
- Its messages are rate-limited per IP address.
- It answers only on the websites you listed.
- It shows replies as plain text.

## Where it shows up

- **Conversations:** every chat, with the AI's suggested reply on the same channel.
- **Agent Studio, Conversations lane:** chats waiting for a reply and today's chats.
- **Agent Studio, Social lane:** posts to approve and accounts that stopped working.

## Inbound ad leads

**Meta lead ads in real time.** The Page webhook's `leadgen` field brings each submission within seconds. The
lead is fetched with the Page token and enters the speed-to-lead flow:
- an approved lead;
- a call task due now;
- website research;
- a first reply drafted for approval.

When Frappe CRM's scheduled Lead Syncing later imports the same lead, it is linked to that lead, not duplicated.
This needs the `leads_retrieval` and `pages_manage_ads` permissions, plus the `leadgen` webhook field.

**LinkedIn Lead Gen forms.** On the Channels page, use **Connect lead forms**. It is a separate connection
because LinkedIn grants `r_marketing_leadgen_automation` only after you apply for its Lead Sync API. New form
answers are fetched every hour into the same speed-to-lead flow. Check the request shapes against LinkedIn's
current Lead Sync API documentation once access is granted.

## Call transcription (system provider)

In Platform Settings → Call transcription, choose OpenAI or a local Whisper-compatible server and a model.
- After each recorded office-phone call, the transcript and an AI summary are saved as a note on the CRM call log.
- The note includes a suggested outcome, the next step and a coaching tip.
- Callers must hear a recording notice.

## Conversations desk

Each lead has one conversation across all channels:
- email and WhatsApp;
- SMS and RCS;
- Messenger and Instagram, including buying comments;
- website chat;
- phone calls.

**Owner.** List the people who answer conversations on the Channels page. New conversations go to whoever has
the fewest open ones. Owners are notified, and anyone can reassign a conversation in Conversations.

**Status.** A conversation stays Open until someone resolves it. A new message from the lead reopens it.

**Tags.** Type a tag in a conversation. Tags are Frappe tags, so list views can filter on them too. The tag
`needs-human` marks conversations the AI handed to a person.

**AI mode** (per conversation; "Company default" follows the Channels page):
- **AI autopilot:** routine answers from approved knowledge go out at once on chats. With the extra setting
  ticked, WhatsApp is answered too, within its 24-hour window. Anything else is handed to the owner, with the
  reason and the `needs-human` tag.
- **AI suggests, we send:** the AI drafts and a person sends.
- **Human only:** no AI. When a person writes a reply themselves, the conversation switches to Human only. Pick
  the mode again to hand the conversation back to the AI.

**Replying.** People reply from Conversations on any channel open for that lead. They can write their own reply,
or start from the AI's draft and edit it.

## SMS

In Sales Agent Settings → SMS, choose a provider:
- **Platform gateway:** the system provider's BulkSMSBD account.
- **BulkSMSBD** or **SSL Wireless:** your own key and approved sender ID.
- **Twilio (SMS and RCS):** see below.

SMS goes only to leads with recorded SMS consent. A lead who texts STOP (or বন্ধ) is put on the do-not-contact
list. Replies by SMS come in through Twilio only, because the Bangladeshi gateways have no reply webhook.

## Twilio (each Company)

In Sales Agent Settings → Twilio, enter the Account SID, auth token, phone number and, for RCS, a Messaging
Service SID. Then paste the addresses from the Channels page into Twilio:
- **Phone number → "A call comes in":** the voice address. The AI voice assistant answers if it is on;
  otherwise the call goes to the number for people.
- **Phone number or Messaging Service → "A message comes in":** the SMS address.

**What it adds:**
- **Calls:** set "Calls go through" to Twilio. Click-to-call and the power dialer ring the salesperson's mobile
  (from their user profile), then connect the lead from your Twilio number, inside your calling hours. Calls
  appear in the CRM Call Log. With recording on, each recording is transcribed and summarised. Callers must be
  told that calls are recorded.
- **AI voice assistant:** it says it is an AI, listens with Twilio speech recognition, and answers only from
  approved knowledge. It connects the caller to the number for people when they ask for someone, or when the
  answer is not in the knowledge or involves money. It stops after 6 turns. Each call is a conversation in
  Conversations.
- **SMS and RCS:** with a Messaging Service, Twilio uses RCS where the phone supports it and falls back to SMS.
- **Email through Twilio SendGrid:** set "Send email through" to Twilio SendGrid, then add an API key and a
  verified from address. To have bounces and spam reports reach the do-not-contact list, turn on SendGrid's
  Signed Event Webhook with the events address from the Channels page, and paste its public key into Sales Agent
  Settings.

Every Twilio webhook is checked against the Company's auth token (`X-Twilio-Signature`). SendGrid events are
checked against the signed-webhook key.

## Easier setup

The Channels page has the following:
- **For the system provider:** a checklist and the exact addresses to paste into Meta and LinkedIn, plus a
  button that makes a new webhook verify token.
- **For each Company:** one-click Connect buttons and every webhook address with a Copy button.


## Moving the site to another domain

Every address you paste into another service (Meta and LinkedIn callbacks, WhatsApp, Twilio, Brevo, SendGrid, the web chat
script) is shown on the Integrations page using the domain you opened the page on. Open Integrations on the new domain
and copy the addresses again; nothing in the app needs editing.

Two things live outside the page and need the new domain once:

1. The site's own address, which links in sent email (unsubscribe, open and click tracking) and the OAuth redirect are
   built from: `bench --site <site> set-config host_name https://app.reckon.tech`, then restart.
2. The addresses already pasted into Meta, LinkedIn, Twilio, Brevo and SendGrid: replace them with the new ones. Links in
   emails already sent keep the old domain, so keep the old domain redirecting to the new one for a while.

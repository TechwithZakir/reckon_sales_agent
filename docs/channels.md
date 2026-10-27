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
   - Fields: `messages` and `messaging_postbacks`.
4. In Platform Settings, enter the Meta app ID and app secret. The secret also verifies every webhook call
   (`X-Hub-Signature-256`).
5. Have these permissions approved in App Review, with Business Verification. Until then, only people with a
   role on the app can connect:
   - `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`, `pages_manage_metadata`, `pages_messaging`
   - `instagram_basic`, `instagram_content_publish`, `instagram_manage_messages`
   - `business_management`

When a Company clicks **Connect with Facebook**, it gets:
- every Page it manages, each with its own Page token;
- the Instagram professional account linked to each Page;
- each Page subscribed to the webhook, so messages reach Conversations.

**Messaging rules (Meta):**
- A chat always starts with the lead. The agent never messages anyone first.
- Replies go out as `RESPONSE` within 24 hours of the lead's last message. After that, the reply is cancelled
  with the reason. Call or email the lead instead.

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

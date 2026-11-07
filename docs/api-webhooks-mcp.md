# Clean list, API, webhooks and AI assistants

Capture Studio has two more tabs: **Clean list** and **Developers**.

## Clean list: address checking

Every address is checked before a campaign can email it.

* **Valid**: well formed, and its domain has a mail server.
* **Risky**: probably delivered, but may not reach the person you want: a disposable address, a shared mailbox (`info@`, `sales@`),
  or a domain that looks like a typo (`gmial.com`). Risky addresses can still be emailed.
* **Invalid**: cannot be delivered (not an address, a reserved test domain such as `example.com`, or a domain with no mail server).
  **An invalid address is never emailed by a campaign or an automation.**

The built-in check needs no account: syntax, a rule list and one DNS lookup (answers are kept a day, and a lookup that fails
decides nothing, so a network problem never marks a good address). In **Integrations → Email → Address checking** you can add
**ZeroBounce**, which also checks the mailbox itself (billed by ZeroBounce); the worse of the two answers wins, and the provider is
only asked about addresses the built-in check did not already reject.

New signups and imports are checked in the background, a daily job checks the rest, and the tab has "Check new addresses",
"Check everyone again" and a box to try one address. A segment can use the check ("Email address check is Invalid").

## API

For your own systems. Make an API key and secret for a Sales Agent manager (User → API Access → Generate Keys) and send

    Authorization: token API_KEY:API_SECRET

Every call is limited to that user's Company, needs an active subscription and a manager, and **cannot send or approve a
message**. Paths start with `https://YOUR-SITE/api/method/reckon_sales_agent.`

| | Call | What it does |
|---|---|---|
| GET | `api_public.ping` | Check the key works |
| POST | `api_public.person_upsert` | Add or update a person: `email` or `phone`, `name`, `business`, `city`, `industry`, `tags`, and **`consent_statement`** (how they agreed; required, stored on the person) |
| GET | `api_public.person` | One person by `email` or `phone`: tags, engagement, confirmed, address check |
| POST | `api_public.person_tags` | `email`, `add`, `remove` |
| POST | `api_public.person_unsubscribe` | Stop all campaign email to an address, for good |
| GET | `api_public.segments`, `api_public.segment_people` | Segments and who is in one (`segment`, `limit`) |
| GET | `api_public.forms`, `api_public.automations` | Your forms and automations |
| POST | `api_automation.trigger` | Start an automation for a person (`automation`, `email` or `phone`, `consent_statement`) |
| GET | `api_public.events` | What happened to messages (`since`, `type`, `limit`) |
| POST | `api_public.check_email` | Check one address |

Example:

    curl -X POST "https://YOUR-SITE/api/method/reckon_sales_agent.api_public.person_upsert" \
      -H "Authorization: token API_KEY:API_SECRET" \
      -d "email=name@company.com" -d "name=Rahim" -d "tags=website" \
      -d "consent_statement=Asked for our price list on the website"

## Webhooks

We call your address when something happens: `signup`, `confirmed`, `tag_added`, `sent`, `opened`, `clicked`, `replied`,
`bounced`, `complained`, `unsubscribed`, `automation_completed`. Make one in **Capture Studio → Developers → New webhook**; its
signing secret is shown once.

Each call is `POST` JSON `{"event": "opened", "at": "...", "data": {"person": {...}, ...}}` with the headers `X-Reckon-Event` and
`X-Reckon-Signature`: the hex HMAC-SHA256 of the raw body, keyed with your secret. Check it before you trust the call:

    import hmac, hashlib
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    ok = hmac.compare_digest(expected, request.headers["X-Reckon-Signature"])

Addresses must be public `https` addresses (never the server's own network); redirects are not followed; calls are made in the
background so they never slow a signup or a send; the last result is shown on the webhook; after **10 failures in a row** it
switches itself off (edit and save it to switch it on again).

## AI assistants (MCP)

Claude, ChatGPT, Cursor and other assistants that speak the Model Context Protocol can work in Campaign Studio:

    https://YOUR-SITE/api/method/reckon_sales_agent.api_mcp.rpc     (send the same Authorization header)

In Claude: Settings → Connectors → Add custom connector. The assistant can list and preview segments, save a segment, tag a person,
look up a person, list forms, automations and campaigns, read campaign and automation reports, simulate an automation and check
addresses. It **cannot send, approve, switch an automation on, import files or delete**: those decisions stay with a person in the
Studio. Tools that change something need a manager.

## Live test plan

1. Clean list → "Try an address": `x@example.com` is Invalid; `info@yourcompany.com` is Risky; a normal address is Valid.
2. Check new addresses → the bar fills in; an Invalid person receives nothing from a campaign (Campaign Members shows "not
   reachable").
3. Developers → New webhook with a request catcher (for example webhook.site) → Test → the call arrives with the signature; sign up
   on a form and see `signup` arrive.
4. Make an API key for yourself and run the curl above; the person appears in Capture Studio with the consent statement.
5. Connect an assistant to the MCP address and ask "how many people opened an email in the last 30 days?"

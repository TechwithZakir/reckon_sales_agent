# Language, IT notes, plain lists and the welcome tour

## Bangla (and other languages)

The app uses Frappe's own translation system, so there is no separate language switch inside Sales Agent.

* Each person picks a language in **My Settings → Language** (a whole site can default to one in **System Settings → Language**).
* `reckon_sales_agent/translations/bn.csv` holds the Bangla text (about 2,500 strings): menus, pages, buttons, messages, field labels.
* Anything not translated falls back to English, so a missing string never breaks a page.
* Technical names that people recognise (Brevo, Twilio, WhatsApp, SerpAPI) stay in English.
* After deploying run `bench --site <site> clear-cache` once so the new file is read.

Adding a language: copy `bn.csv` to `<code>.csv` (for example `hi.csv`) and replace the second column. Keep placeholders such as
`{0}` exactly as they are; `tests/test_translations.py` checks this for Bangla.

## "Ask your IT person" notes in Integrations

Every integration panel starts with a short list of what to ask the technical person for (keys, DNS records, page admin access),
and a **Copy a message for your IT person** button. The message names the integration and this site's address and is ready to
paste into email or chat. No secret is ever written into it.

## Plain lists under Advanced

Each technical list gets one sentence at the top saying what it is and when to look at it, and the system ID column is hidden.
Vendor-only entries (marked "(vendor)") are hidden from everyone except System Manager and Reckon Vendor Superuser.

## Welcome tour

A six-step tour appears the first time a person opens a main Sales Agent page. It is remembered in the browser
(`rsa_tour_done`), can be skipped, and can be replayed from **Help → Replay the welcome tour**.

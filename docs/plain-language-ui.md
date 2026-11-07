# An interface for people who are not technical

The audience is a business owner or a salesperson, not an engineer. This page records what we found, what changed, and the rules
for new screens.

## What the audit found

* A sidebar of 43 items named after the data model (Qualification Profiles, Source Connectors, Campaign Members, Events,
  Provider Usage) with the everyday tasks buried among them.
* A home page that opened with thirteen "agent" cards before the one thing a person must do today.
* Three unexplained numbers on every lead ("46 · 66% · 70").
* Raw provider errors shown to business users ("AI request failed (400): Your credit balance is too low ...").
* A lead source picker listing providers by their company names (ScrapingBee, SerpAPI, Apify ...).
* No help on any page, and words such as "pilot", "autopilot", "segment" and "double opt-in" with no explanation.
* Good already: Get started (plain steps), the empty states and plain labels in the Studios, and every page works at phone width.

## What changed

* **Sidebar:** Get started, Home, Inbox, Meetings; then Find customers, Reach out, Results, Connect and settings. Everything else
  (all the technical lists, vendor items) is still there under **Advanced**, closed by default, with plain names ("Do-not-contact
  list", "Lead scores", "Activity log", "Background tasks").
* **Home:** "Needs you today" comes first; the thirteen agents are one click away under "See what each AI agent is doing". A lead's
  numbers read **Fit 46 · Chance 66% · Match 70%** with a tooltip.
* **Plain errors:** the AI's failures read "The AI service has no credit left. Ask your administrator to add credit." The
  provider's own words are kept for logs and administrators (`LLMError.detail`).
* **Lead Finder:** the recommended source (Smart Sources) and "your own list" come first; "Show all lead sources (advanced)" shows
  the provider-named ones.
* **Help:** a Help button on every everyday page opens a short guide (what the page is for, what to do first) and a glossary of the
  words used in the app. A one-time hint tells a new person it exists. It never talks to the server and never breaks a page.
* **Accessibility:** icon-only buttons in the flow editor have names for screen readers.

## Rules for new screens

1. Name things by what the person does, not by the data behind them ("Do-not-contact list", not "Suppression Entry").
2. Put what needs the person first; put detail one click away.
3. Never show a status code, a provider name or a stack of settings as the first thing. Say what happened and what to do.
4. Every number gets a label, and a tooltip if the label is not enough.
5. An empty page says what it is for and offers the one next step.
6. Anything that reaches a customer says so, and waits for a person unless autopilot is on.
7. Test at phone width and with the keyboard; give icon-only buttons a name.

## Not done yet (the backlog)

* **Bangla.** The strings are wrapped for translation (`__()`), but no Bangla translation file exists. This is the biggest remaining
  step for Bangladeshi teams.
* The technical lists reached from Advanced still carry their data-model titles and many columns.
* Integrations: tiles are clear, but their setup panels still ask for keys and web addresses; each should open with "ask your IT
  person for ..." and a copy-ready message to send them.
* A guided tour on first login, and hiding vendor-only items from tenant users.
* A short video or screenshot guide per Studio.

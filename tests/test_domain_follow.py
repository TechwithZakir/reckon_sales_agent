"""Webhook and callback addresses follow the domain the Integrations page was opened on."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "reckon_sales_agent"
JS = (ROOT / "reckon_sales_agent" / "page" / "sales_channels" / "sales_channels.js").read_text(encoding="utf-8")


class DomainFollowTests(unittest.TestCase):
    def test_every_address_row_is_rebased_to_the_browsers_domain(self):
        row = JS.split("copy_row(label, url) {")[1].split("\n\t\t}")[0]
        self.assertIn("url = this.rebase(url);", row)
        self.assertIn("window.location.origin", JS.split("rebase(text) {")[1].split("\n\t\t}")[0])

    def test_no_address_is_pasted_without_going_through_copy_row(self):
        # Addresses reach the page only as copy_row arguments, so a new domain needs no change to any of them.
        for needle in ("brevo_notify", "meta_webhook", "redirect_uri", "whatsapp.webhook", "urls.voice", "urls.sms",
                       "urls.sendgrid_events", "api.email_events", "webchat.script"):
            for line in (ln for ln in JS.splitlines() if needle in ln and "copy_row(" not in ln):
                self.assertNotIn("<code>", line, needle)

    def test_the_old_domain_is_not_written_into_any_screen(self):
        for path in (ROOT / "reckon_sales_agent" / "page").rglob("*.js"):
            self.assertNotIn("distribution.reckon.tech", path.read_text(encoding="utf-8"), path.name)


if __name__ == "__main__":
    unittest.main()

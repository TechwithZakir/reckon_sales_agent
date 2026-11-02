"""Conversations: connected channels are listed with their sender, and Meta replies only to people who wrote in (no bench)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

APP = Path(__file__).parents[1] / "reckon_sales_agent"
INBOX = APP / "reckon_sales_agent" / "page" / "sales_inbox" / "sales_inbox.js"


class ReplyChannelTests(unittest.TestCase):
    def test_connected_pages_are_listed_before_they_are_reachable(self):
        omni = (APP / "agents" / "omni.py").read_text(encoding="utf-8")
        body = omni.split("def reply_channels(")[1].split("\ndef ")[0]
        self.assertIn("Meta lets a Page reply only after the person writes in", body)
        self.assertIn('"Sales Social Account", {', body)
        self.assertIn('"from": _sender(channel, prospect, settings, prospect.company, wrote)', body)

    def test_sender_is_the_page_the_person_wrote_to(self):
        sender = (APP / "agents" / "omni.py").read_text(encoding="utf-8").split("def _sender(")[1].split("\ndef ")[0]
        self.assertIn('"direction": "In"', sender)
        self.assertIn('"account_id", order_by="sent_at desc"', sender)

    def test_inbox_shows_the_sender_next_to_each_channel(self):
        js = INBOX.read_text(encoding="utf-8")
        self.assertIn("${ch.from ? ` · ${e(ch.from)}` : \"\"}", js)
        self.assertIn("<small>${ch.from ?", js)


if __name__ == "__main__":
    unittest.main()

"""Email in Conversations: CRM and Reckon mail on the sending account lands on the lead's thread (no bench)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

APP = Path(__file__).parents[1] / "reckon_sales_agent"


def read(*parts):
    return APP.joinpath(*parts).read_text(encoding="utf-8")


class EmailThreadTests(unittest.TestCase):
    def test_non_outreach_mail_goes_to_the_thread(self):
        handler = read("campaigns", "engine.py").split("def handle_communication(")[1].split("\ndef ")[0]
        self.assertIn('if doc.reference_doctype != "Sales Outreach Message":', handler)
        self.assertIn("file_email(doc)", handler)

    def test_only_mail_on_the_sending_account_is_filed(self):
        module = read("agents", "email_threads.py")
        self.assertIn("address in (doc.get(\"recipients\") or \"\").lower()", module)  # incoming: to our account
        self.assertIn("== address", module)  # outgoing: from our account

    def test_incoming_mail_gets_an_ai_draft_for_approval(self):
        module = read("agents", "email_threads.py")
        self.assertIn('"reckon_sales_agent.agents.chat.auto_draft"', module)

    def test_email_is_a_channel_and_the_thread_shows_both_directions(self):
        self.assertIn('"Email": "email"', read("agents", "chat.py"))
        self.assertIn("Email", read("reckon_sales_agent", "doctype", "sales_chat_message", "sales_chat_message.json"))
        timeline = read("agents", "omni.py").split("def timeline(")[1].split("\ndef ")[0]
        self.assertIn('if c.outreach_message or c.channel != "Email":', timeline)


if __name__ == "__main__":
    unittest.main()

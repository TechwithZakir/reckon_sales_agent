"""Fast chat answers, comment-to-private-reply and reply-time reminders (no bench)."""
import json
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from reckon_sales_agent.agents.chat import (  # noqa: E402
    buying_comment,
    median,
    meta_comments,
    response_minutes,
    send_params,
)
from reckon_sales_agent.agents.omni import REPLY_SCHEMA, auto_answer_decision, choose_channel  # noqa: E402
from reckon_sales_agent.agents.policy import ALLOW, BLOCKED, NEEDS_APPROVAL  # noqa: E402
from reckon_sales_agent.agents.social_connect import META_SCOPES  # noqa: E402

APP = Path(__file__).parents[1] / "reckon_sales_agent"
NOW = datetime(2026, 10, 28, 12, 0)
GOOD = {"grounded": True, "needs_person": False}


def read(*parts):
    return APP.joinpath(*parts).read_text(encoding="utf-8")


class AutoAnswerPolicyTests(unittest.TestCase):
    def test_routine_grounded_chat_answer_goes_out(self):
        decision = auto_answer_decision(True, "Messenger", GOOD, [], "question")
        self.assertEqual(decision.outcome, ALLOW)
        self.assertEqual(auto_answer_decision(True, "Web Chat", GOOD, [], "other").outcome, ALLOW)

    def test_everything_else_waits_for_a_person(self):
        cases = [
            (False, "Messenger", GOOD, [], "question"),  # the Company did not turn it on
            (True, "Email", GOOD, [], "question"),  # email always waits
            (True, "WhatsApp", GOOD, [], "question"),
            (True, "Messenger", {"grounded": False, "needs_person": False}, [], "question"),  # a fact not in knowledge
            (True, "Messenger", {"grounded": True, "needs_person": True}, [], "question"),  # a discount, a contract
            (True, "Messenger", GOOD, ['"20% off" is not in your approved knowledge.'], "question"),
            (True, "Instagram", GOOD, [], "complaint"),
            (True, "Instagram", GOOD, [], "unsubscribe"),
        ]
        for case in cases:
            self.assertEqual(auto_answer_decision(*case).outcome, NEEDS_APPROVAL, case)

    def test_suppression_and_kill_switch_block(self):
        self.assertEqual(auto_answer_decision(True, "Messenger", GOOD, [], "question", suppressed=True).outcome, BLOCKED)
        self.assertEqual(auto_answer_decision(True, "Messenger", GOOD, [], "question", kill_switch=True).outcome,
                         BLOCKED)

    def test_the_ai_reports_grounding_and_need_for_a_person(self):
        self.assertEqual(set(REPLY_SCHEMA["required"]), {"subject", "body", "why", "grounded", "needs_person"})
        draft = read("agents", "omni.py").split("def draft_reply(")[1]
        self.assertIn("auto_answer_decision(", draft)
        self.assertIn('"auto_approved_by_policy": 1', draft)
        self.assertIn("approval_fingerprint", draft)  # send_message re-checks the approval like any other

    def test_off_by_default(self):
        doc = json.loads(read("reckon_sales_agent", "doctype", "sales_agent_settings", "sales_agent_settings.json"))
        fields = {f["fieldname"]: f for f in doc["fields"]}
        self.assertEqual((fields["chat_auto_answer"]["default"], fields["comment_to_chat"]["default"]), ("0", "0"))
        self.assertEqual(fields["chat_reply_sla_minutes"]["default"], "15")


class CommentTests(unittest.TestCase):
    def page_comment(self, text="Price koto?", author="U1"):
        return {"object": "page", "entry": [{"id": "PAGE1", "changes": [{"field": "feed", "value": {
            "item": "comment", "verb": "add", "comment_id": "POST_C1", "post_id": "PAGE1_POST",
            "message": text, "from": {"id": author, "name": "Karim"}, "created_time": 1792000000}}]}]}

    def test_page_and_instagram_comments(self):
        [c] = meta_comments(self.page_comment())
        self.assertEqual((c["channel"], c["account_id"], c["contact_id"], c["external_id"], c["kind"], c["post_id"]),
                         ("Messenger", "PAGE1", "U1", "POST_C1", "Comment", "PAGE1_POST"))
        self.assertEqual(c["contact_name"], "Karim")
        ig = {"object": "instagram", "entry": [{"id": "IG1", "changes": [{"field": "comments", "value": {
            "id": "IGC1", "text": "দাম কত?", "from": {"id": "IGU", "username": "rahim.bd"}, "media": {"id": "M1"}}}]}]}
        [i] = meta_comments(ig)
        self.assertEqual((i["channel"], i["external_id"], i["contact_name"], i["post_id"]),
                         ("Instagram", "IGC1", "rahim.bd", "M1"))

    def test_own_comments_edits_and_other_changes_are_skipped(self):
        self.assertEqual(meta_comments(self.page_comment(author="PAGE1")), [])  # the Page answering publicly
        edited = self.page_comment()
        edited["entry"][0]["changes"][0]["value"]["verb"] = "edited"
        self.assertEqual(meta_comments(edited), [])
        reaction = self.page_comment()
        reaction["entry"][0]["changes"][0]["value"]["item"] = "reaction"
        self.assertEqual(meta_comments(reaction), [])

    def test_only_buying_comments(self):
        for text in ("price?", "দাম কত?", "Inbox plz", "koto taka", "wholesale available?", "ডেলিভারি হবে?"):
            self.assertTrue(buying_comment(text), text)
        for text in ("Nice product", "great 👍", "Love it!", ""):
            self.assertFalse(buying_comment(text), text)

    def test_one_private_reply_within_seven_days(self):
        self.assertEqual(send_params("comment:C1", "Hi")["recipient"], {"comment_id": "C1"})
        self.assertEqual(send_params("PSID", "Hi")["recipient"], {"id": "PSID"})
        prospect = {"email": "a@b.com"}
        comment = {"channel": "Messenger", "kind": "Comment", "at": NOW - timedelta(days=3)}
        self.assertEqual(choose_channel(prospect, None, NOW, comment)[0], "Messenger")
        old = {**comment, "at": NOW - timedelta(days=8)}
        self.assertEqual(choose_channel(prospect, None, NOW, old)[0], "Email")
        chat = read("agents", "chat.py").split("def reachable(")[1]
        self.assertIn("already has its private reply", chat)
        self.assertIn("feed", read("agents", "social_connect.py").split("subscribed_fields")[1][:60])
        self.assertIn("instagram_manage_comments", META_SCOPES)

    def test_webhook_respects_the_company_setting(self):
        webhook = read("api_channels.py").split("def meta_webhook(")[1].split("\ndef ")[0]
        self.assertIn('get_settings(owner[0]).get("comment_to_chat")', webhook)
        self.assertIn("buying_comment(", webhook)


class ResponseTimeTests(unittest.TestCase):
    def test_minutes_to_answer(self):
        t = NOW
        rows = [("In", t), ("In", t + timedelta(minutes=2)), ("Out", t + timedelta(minutes=10)),
                ("Out", t + timedelta(minutes=11)), ("In", t + timedelta(minutes=30)), ("Out", t + timedelta(minutes=34))]
        self.assertEqual(response_minutes(rows), [10.0, 4.0])
        self.assertEqual(response_minutes([("In", t)]), [])  # still waiting: not counted yet
        self.assertEqual(median([10.0, 4.0]), 7.0)
        self.assertEqual(median([3.0, 1.0, 2.0]), 2.0)
        self.assertIsNone(median([]))

    def test_reminders_run_every_five_minutes(self):
        hooks = read("hooks.py")
        self.assertIn('"*/5 * * * *": ["reckon_sales_agent.agents.chat.remind_waiting"]', hooks)
        remind = read("agents", "chat.py").split("def remind_waiting(")[1]
        self.assertIn("chat_reminded", remind)  # once per message


if __name__ == "__main__":
    unittest.main()

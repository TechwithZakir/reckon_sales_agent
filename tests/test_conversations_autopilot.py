"""Agent Studio: the Conversations agent can run on autopilot for a Company (no bench)."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

APP = Path(__file__).parents[1] / "reckon_sales_agent"


def read(*parts):
    return APP.joinpath(*parts).read_text(encoding="utf-8")


class ConversationsAutopilotTests(unittest.TestCase):
    def test_setting_exists(self):
        doc = json.loads(read("reckon_sales_agent", "doctype", "sales_agent_settings", "sales_agent_settings.json"))
        field = next(f for f in doc["fields"] if f["fieldname"] == "conversations_autopilot")
        self.assertEqual(field["fieldtype"], "Check")

    def test_threads_follow_the_switch(self):
        mode = read("agents", "conversations.py").split("def mode_for(")[1].split("\ndef ")[0]
        self.assertIn('settings.get("conversations_autopilot")', mode)
        self.assertIn('settings.get("conversations_autopilot")', read("agents", "chat.py"))  # drafts are made

    def test_agent_studio_has_a_manager_only_switch(self):
        api = read("api_agent_studio.py")
        body = api.split("def set_conversations_autopilot(")[1].split("\n@")[0]
        self.assertIn("_require_manager()", body)
        self.assertIn('"conversations_autopilot": bool(settings.get("conversations_autopilot"))', api)

    def test_the_page_shows_the_switch(self):
        js = read("reckon_sales_agent", "page", "sales_agent", "sales_agent.js")
        self.assertIn("render_conv_auto(s)", js)
        self.assertIn('"set_conversations_autopilot"', js)


if __name__ == "__main__":
    unittest.main()

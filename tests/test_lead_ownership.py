"""Team call routing: one owner per lead across calls, follow-ups, chats and the CRM lead (no bench)."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from reckon_sales_agent.agents.ownership import STICKY, TEAM, resolve_owner  # noqa: E402

APP = Path(__file__).parents[1] / "reckon_sales_agent"
TEAM_LIST = ["rahim@x.com", "karim@x.com"]


def read(*parts):
    return APP.joinpath(*parts).read_text(encoding="utf-8")


class ResolveOwnerTests(unittest.TestCase):
    def test_an_owner_sticks(self):
        self.assertEqual(resolve_owner("karim@x.com", "boss@x.com", "rahim@x.com", TEAM_LIST, {}, TEAM, "named@x.com"),
                         ("karim@x.com", "owner"))

    def test_crm_owner_then_conversation_owner(self):
        self.assertEqual(resolve_owner(None, "boss@x.com", "rahim@x.com", TEAM_LIST, {}, TEAM, None),
                         ("boss@x.com", "crm"))
        self.assertEqual(resolve_owner(None, None, "rahim@x.com", TEAM_LIST, {}, TEAM, None),
                         ("rahim@x.com", "conversation"))

    def test_team_routing_picks_the_least_busy(self):
        counts = {"rahim@x.com": 7, "karim@x.com": 2}
        self.assertEqual(resolve_owner(None, None, None, TEAM_LIST, counts, TEAM, "named@x.com"),
                         ("karim@x.com", "team"))
        self.assertEqual(resolve_owner(None, None, None, TEAM_LIST, {}, TEAM, None), ("rahim@x.com", "team"))

    def test_one_salesperson_by_default(self):
        self.assertEqual(resolve_owner(None, None, None, TEAM_LIST, {}, "One salesperson", "named@x.com"),
                         ("named@x.com", "named"))
        self.assertEqual(resolve_owner(None, None, None, [], {}, TEAM, "named@x.com"), ("named@x.com", "named"))
        self.assertEqual(resolve_owner(None, None, None, [], {}, None, None), (None, "none"))

    def test_only_a_chosen_owner_sticks(self):
        self.assertNotIn("named", STICKY)  # changing the named salesperson later still moves new leads
        self.assertIn("team", STICKY)


class WiringTests(unittest.TestCase):
    def test_tasks_chats_and_crm_use_the_owner(self):
        channels = read("providers", "channels.py")
        self.assertIn("owner_for(prospect_name, settings)", channels.split("def _assignee(")[1])
        self.assertIn("owner = _assignee(prospect_name, settings)", channels.split("def create_task(")[1])
        self.assertIn('"lead_owner": owner_for(prospect.name, fallback=False)', read("crm_sync.py"))
        convo = read("agents", "conversations.py")
        self.assertIn("sticky_only=True", convo.split("def touch_inbound(")[1].split("\ndef ")[0])
        self.assertIn("set_owner(prospect, owner)", convo.split("def touch_inbound(")[1].split("\ndef ")[0])

    def test_reassigning_moves_the_whole_lead(self):
        api = read("api_conversations.py").split("def assign(")[1].split("\ndef ")[0]
        self.assertIn("reassign(doc.company, doc.name, user)", api)
        moves = read("agents", "ownership.py").split("def reassign(")[1]
        for what in ('"ToDo"', '"CRM Task"', '"lead_owner"', '"Sales Conversation"'):
            self.assertIn(what, moves)

    def test_schema(self):
        settings = json.loads(read("reckon_sales_agent", "doctype", "sales_agent_settings", "sales_agent_settings.json"))
        routing = next(f for f in settings["fields"] if f["fieldname"] == "call_routing")
        self.assertEqual((routing["options"], routing["default"]), ("One salesperson\nShare across the team",
                                                                   "One salesperson"))
        prospect = json.loads(read("reckon_sales_agent", "doctype", "sales_prospect", "sales_prospect.json"))
        owner = next(f for f in prospect["fields"] if f["fieldname"] == "sales_owner")
        self.assertEqual((owner["fieldtype"], owner["options"]), ("Link", "User"))

    def test_studio_shows_each_person_their_own(self):
        js = read("reckon_sales_agent", "page", "sales_agent", "sales_agent.js")
        self.assertIn("this.onlyMine = !this.data.can_manage", js)
        self.assertIn('item["me"] = frappe.session.user', read("api_agent_studio.py"))


if __name__ == "__main__":
    unittest.main()

"""The Agent Studio agent cards: filter chips, cards or list, a details dialog, and a way to each agent's work."""

import pathlib
import re
import unittest

APP = pathlib.Path(__file__).resolve().parents[1] / "reckon_sales_agent"
PAGES = APP / "reckon_sales_agent" / "page"
SCRIPT = (PAGES / "sales_agent" / "sales_agent.js").read_text(encoding="utf-8")


class AgentCardTests(unittest.TestCase):
    def test_every_agent_has_a_link_and_a_description(self):
        api = (APP / "api_agent_studio.py").read_text(encoding="utf-8")
        agents = re.search(r"AGENTS = \(([^)]*)\)", api, re.S).group(1)
        names = re.findall(r'"([^"]+)"', agents)
        links = SCRIPT.split("const AGENT_LINKS = {")[1].split("};")[0]
        about = SCRIPT.split("const AGENT_ABOUT = {")[1].split("};")[0]
        for name in names:
            key = f'"{name}"' if " " in name else name
            self.assertIn(f"{key}: [[", links, name)
            self.assertIn(f"{key}: \"", about, name)

    def test_links_point_at_pages_that_exist(self):
        links = SCRIPT.split("const AGENT_LINKS = {")[1].split("};")[0]
        for page in set(re.findall(r'"([a-z]+(?:-[a-z]+)+)"\]', links)):
            self.assertTrue((PAGES / page.replace("-", "_")).is_dir(), page)

    def test_cards_filter_open_and_jump(self):
        for needle in ("chips: [[\"all\"", "views: true", "agent_dialog(", "show_asks(", "ags-lane-go", "role=\"button\" tabindex=\"0\""):
            self.assertIn(needle, SCRIPT)


if __name__ == "__main__":
    unittest.main()

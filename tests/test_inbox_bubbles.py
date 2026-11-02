"""Conversations: the thread reads like a messenger, bubbles on each side in time order (no bench)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

PAGE = Path(__file__).parents[1] / "reckon_sales_agent" / "reckon_sales_agent" / "page" / "sales_inbox"


class BubbleTests(unittest.TestCase):
    def test_thread_uses_bubbles_on_each_side(self):
        js = (PAGE / "sales_inbox.js").read_text(encoding="utf-8")
        method = js.split("timeline_html(items, name) {")[1].split("\n\t\trender_thread(")[0]
        self.assertIn('const out = i.direction === "out";', method)
        self.assertIn('class="sin-bubble ${out ? "out" : "in"}"', method)
        self.assertIn('class="sin-av"', method)  # the lead's initial beside their messages
        self.assertIn('class="sin-day"', method)  # a date separator when the day changes

    def test_bubble_styles_exist(self):
        css = (PAGE / "sales_inbox.css").read_text(encoding="utf-8")
        for cls in (".sin-bubble.in", ".sin-bubble.out", ".sin-day", ".sin-av", ".sin-note-line"):
            self.assertIn(cls, css, cls)


if __name__ == "__main__":
    unittest.main()

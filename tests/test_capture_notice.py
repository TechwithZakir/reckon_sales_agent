"""The lead capture finished note: pure text, and where it is wired in (no bench needed)."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))

from reckon_sales_agent.agents.capture_notice import compose  # noqa: E402

APP = pathlib.Path(__file__).parents[1] / "reckon_sales_agent"


def read(*parts):
    return APP.joinpath(*parts).read_text(encoding="utf-8")


class ComposeTests(unittest.TestCase):
    def test_the_note_has_the_counts_and_a_link_and_says_nothing_was_sent(self):
        subject, html = compose("Garments", 19, 13, 4, 2, "https://x.example/desk/sales-agent/sales-review")
        self.assertEqual(subject, "Lead capture finished: Garments, 19 new lead(s)")
        for needle in ("<b>19</b> new lead(s)", "<b>13</b> website(s) researched", "4 website(s) could not be read",
                       "<b>2</b> lead(s) look like a fit", 'href="https://x.example/desk/sales-agent/sales-review"',
                       "Nothing has been sent"):
            self.assertIn(needle, html)

    def test_lines_for_nothing_are_left_out_and_names_are_escaped(self):
        _subject, html = compose("<b>x</b> & Co", 0, 0, 0, 0, "https://x.example/")
        self.assertNotIn("could not be read", html)
        self.assertNotIn("look like a fit", html)
        self.assertIn("&lt;b&gt;x&lt;/b&gt; &amp; Co", html)
        self.assertNotIn("<b>x</b>", html)


class WiringTests(unittest.TestCase):
    notice = read("agents", "capture_notice.py")

    def test_it_waits_for_research_announces_each_job_once_and_respects_the_digest_switch(self):
        self.assertIn('"research_status": "Queued"', self.notice)
        self.assertIn('"action": "capture_notified"', self.notice)
        self.assertIn('settings.get("daily_digest")', self.notice)
        self.assertIn("managers(company, settings)", self.notice)

    def test_a_failure_to_announce_never_breaks_discovery_or_research(self):
        self.assertIn("def safely_notify(", self.notice)
        self.assertIn("except Exception:", self.notice.split("def safely_notify(")[1])
        self.assertIn("safely_notify(job.company)", read("discovery", "runner.py"))
        self.assertIn("safely_notify(company)", read("jobs.py"))

    def test_only_a_completed_job_is_announced(self):
        self.assertIn('"status": "Completed"', self.notice)
        self.assertIn('if status == "Completed":', read("discovery", "runner.py"))


if __name__ == "__main__":
    unittest.main()

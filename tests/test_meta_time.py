"""Meta sends UTC timestamps; the conversation must show the moment they were sent (no bench)."""
import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from reckon_sales_agent.agents.chat import meta_events  # noqa: E402


def page_message(stamp_ms):
    return {"object": "page", "entry": [{"id": "1", "messaging": [{
        "sender": {"id": "2"}, "recipient": {"id": "1"}, "timestamp": stamp_ms,
        "message": {"mid": "m.1", "text": "Hello"}}]}]}


class MetaTimeTests(unittest.TestCase):
    def test_timestamp_is_the_moment_it_was_sent(self):
        # 1700000000 seconds after the epoch is 14 Nov 2023, 22:13:20 UTC. Outside a site the time stays UTC.
        [event] = meta_events(page_message(1700000000000))
        self.assertEqual(event["at"], datetime(2023, 11, 14, 22, 13, 20))


if __name__ == "__main__":
    unittest.main()

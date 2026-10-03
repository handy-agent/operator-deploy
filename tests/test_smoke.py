import unittest
import urllib.error

from common import smoke


class SmokeTest(unittest.TestCase):
    def test_passes_on_health_and_ignored_event(self):
        calls = []

        def request(url, body=None):
            calls.append((url, body))
            if url.endswith("/health"):
                return 200, {"ok": True}
            return 200, {"handled": False, "reason": "not a message event"}

        smoke.check("https://x", request=request, delay=0)
        self.assertEqual(calls[0], ("https://x/health", None))
        self.assertEqual(calls[1], ("https://x/webhooks/thumbtack", smoke.SMOKE_EVENT))

    def test_smoke_event_is_not_a_message_event(self):
        self.assertNotEqual(smoke.SMOKE_EVENT["event"]["eventType"], "MessageCreatedV4")

    def test_fails_when_webhook_is_handled(self):
        def request(url, body=None):
            return (200, {}) if body is None else (200, {"handled": True})

        with self.assertRaisesRegex(RuntimeError, "smoke webhook"):
            smoke.check("https://x", request=request, delay=0)

    def test_retries_until_healthy(self):
        answers = iter([urllib.error.URLError("down"), urllib.error.URLError("down"), (200, {})])

        def request(url, body=None):
            answer = next(answers)
            if isinstance(answer, Exception):
                raise answer
            return answer

        smoke.wait_healthy("https://x", attempts=3, delay=0, request=request)

    def test_gives_up(self):
        def request(url, body=None):
            raise urllib.error.URLError("down")

        with self.assertRaisesRegex(RuntimeError, "not healthy after 2"):
            smoke.wait_healthy("https://x", attempts=2, delay=0, request=request)


if __name__ == "__main__":
    unittest.main()

# What it does: Smoke test for a running stage: GET /health must answer 200, and a harmless webhook
#   (an event type Operator ignores, so no lead is created and nothing is sent to Thumbtack) must be
#   accepted with "not a message event". Retries while the app is still starting.
# When it runs: At the end of every deploy (local and AWS).
# What calls it: ops.py (deploy); tests/test_smoke.py.
import json
import time
import urllib.error
import urllib.request

# app/webhooks.py message_from_event() ignores every event type except MessageCreatedV4.
SMOKE_EVENT = {"event": {"eventType": "OperatorDeploySmokeTest", "description": "operator-deploy smoke test"},
               "data": {}}


def _request(url: str, body: dict | None = None, timeout: float = 10) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="GET" if body is None else "POST",
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read() or b"{}")


def wait_healthy(base_url: str, attempts: int = 30, delay: float = 3, request=_request) -> None:
    last = ""
    for _ in range(attempts):
        try:
            status, _ = request(f"{base_url}/health")
            if status == 200:
                return
            last = f"status {status}"
        except (urllib.error.URLError, OSError, ValueError) as exc:
            last = repr(exc)
        time.sleep(delay)
    raise RuntimeError(f"{base_url}/health not healthy after {attempts} tries: {last}")


def check(base_url: str, request=_request, **wait) -> None:
    wait_healthy(base_url, request=request, **wait)
    status, body = request(f"{base_url}/webhooks/thumbtack", SMOKE_EVENT)
    if status != 200 or body.get("reason") != "not a message event":
        raise RuntimeError(f"smoke webhook: unexpected answer {status} {body}")
    print(f"smoke ok: {base_url}")

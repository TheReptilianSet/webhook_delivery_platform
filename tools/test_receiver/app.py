from __future__ import annotations

import hashlib
import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock

STATE = {"mode": "success", "remaining_failures": 0, "records": [], "signing_secret": None}
LOCK = Lock()


class Handler(BaseHTTPRequestHandler):
    server_version = "WebhookTestReceiver/0.1"

    def log_message(self, format: str, *args: object) -> None:
        return

    def _json(self, status: int, payload: object, headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json(200, {"status": "ok"})
            return
        if self.path == "/records":
            with LOCK:
                records = list(STATE["records"])
            self._json(200, {"items": records})
            return
        self._json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        if self.path == "/control":
            payload = json.loads(body)
            with LOCK:
                STATE["mode"] = payload.get("mode", "success")
                STATE["remaining_failures"] = int(payload.get("remaining_failures", 0))
                if "signing_secret" in payload:
                    STATE["signing_secret"] = payload["signing_secret"]
                if payload.get("clear"):
                    STATE["records"] = []
            self._json(200, {"status": "updated"})
            return
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict) and "challenge" in payload:
            self._json(
                200,
                {"verified": True},
                {"Webhook-Verification": str(payload["challenge"])},
            )
            return
        signature = self.headers.get("Webhook-Signature", "")
        signing_secret = STATE["signing_secret"]
        material = b".".join(
            [
                self.headers.get("Webhook-Timestamp", "").encode(),
                self.headers.get("Webhook-Event-Id", "").encode(),
                self.headers.get("Webhook-Delivery-Id", "").encode(),
                body,
            ]
        )
        expected = (
            "v1=" + hmac.new(str(signing_secret).encode(), material, hashlib.sha256).hexdigest()
            if signing_secret
            else ""
        )
        signature_valid = bool(expected) and hmac.compare_digest(signature, expected)
        record = {
            "event_id": self.headers.get("Webhook-Event-Id"),
            "delivery_id": self.headers.get("Webhook-Delivery-Id"),
            "attempt": self.headers.get("Webhook-Attempt"),
            "signature_valid": signature_valid,
            "body": body.decode(errors="replace")[:1024],
        }
        with LOCK:
            STATE["records"].append(record)
            should_fail = (
                not signature_valid
                or STATE["mode"] == "failure"
                or int(STATE["remaining_failures"]) > 0
            )
            if int(STATE["remaining_failures"]) > 0:
                STATE["remaining_failures"] = int(STATE["remaining_failures"]) - 1
        self._json(503 if should_fail else 200, {} if should_fail else {"received": True})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()

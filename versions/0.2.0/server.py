"""ScopePay AI local server with optional PayPal sandbox REST integration."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


VERSION = "0.2.0"
ROOT = Path(__file__).resolve().parent
MAX_BODY = 32 * 1024
FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
ORDER_ID_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")
ORDER_STATUS_RE = re.compile(r"^[A-Z_]{3,32}$")
SANDBOX_BASE = "https://api-m.sandbox.paypal.com"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class ApiError(RuntimeError):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code


def parse_amount(value: Any) -> str:
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise ApiError(400, "invalid_amount", "Amount must be a valid USD number.")
    if amount < Decimal("1.00") or amount > Decimal("10000.00"):
        raise ApiError(400, "invalid_amount", "Amount must be between USD 1.00 and 10,000.00.")
    return f"{amount:.2f}"


def api_base() -> str:
    configured = os.environ.get("PAYPAL_API_BASE", "").rstrip("/")
    if not configured:
        return SANDBOX_BASE
    if os.environ.get("SCOPEPAY_ALLOW_TEST_BASE") == "1" and re.match(r"^http://(?:127\.0\.0\.1|localhost):\d+$", configured):
        return configured
    raise RuntimeError("PAYPAL_API_BASE overrides are allowed only for an explicit loopback test server.")


class PayPalSandbox:
    def __init__(self, client_id: str, client_secret: str):
        if not client_id or not client_secret:
            raise ValueError("Both PayPal sandbox credentials are required")
        self.client_id = client_id
        self.client_secret = client_secret
        self.base = api_base()

    def _json_request(self, path: str, *, data: bytes | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
        request = urllib.request.Request(self.base + path, data=data, method="POST", headers=headers or {})
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                payload = json.load(exc)
                name = str(payload.get("name") or "paypal_error")
            except Exception:
                name = "paypal_error"
            raise ApiError(502, name, "PayPal sandbox rejected the request.") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ApiError(502, "paypal_unavailable", "PayPal sandbox is temporarily unavailable.") from exc

    def token(self) -> str:
        credentials = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode("ascii")
        payload = self._json_request(
            "/v1/oauth2/token",
            data=urllib.parse.urlencode({"grant_type": "client_credentials"}).encode(),
            headers={"Authorization": f"Basic {credentials}", "Content-Type": "application/x-www-form-urlencoded"},
        )
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise ApiError(502, "paypal_token_missing", "PayPal sandbox did not return an access token.")
        return token

    def create_order(self, amount: str, fingerprint: str) -> dict[str, Any]:
        token = self.token()
        body = json.dumps({
            "intent": "CAPTURE",
            "purchase_units": [{
                "reference_id": "scopepay-agreement",
                "description": f"ScopePay agreement {fingerprint[:12]}",
                "custom_id": fingerprint,
                "amount": {"currency_code": "USD", "value": amount},
            }],
            "application_context": {"shipping_preference": "NO_SHIPPING", "user_action": "PAY_NOW"},
        }).encode("utf-8")
        payload = self._json_request(
            "/v2/checkout/orders", data=body,
            headers={
                "Authorization": f"Bearer {token}", "Content-Type": "application/json",
                "PayPal-Request-Id": f"scopepay-{fingerprint[:32]}", "Prefer": "return=representation",
            },
        )
        return normalize_order(payload, "sandbox")

    def capture_order(self, order_id: str) -> dict[str, Any]:
        token = self.token()
        payload = self._json_request(
            f"/v2/checkout/orders/{urllib.parse.quote(order_id, safe='')}/capture", data=b"{}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Prefer": "return=representation"},
        )
        return normalize_order(payload, "sandbox")


def normalize_order(payload: dict[str, Any], mode: str) -> dict[str, Any]:
    order_id = payload.get("id")
    status = payload.get("status")
    if (
        not isinstance(order_id, str)
        or not ORDER_ID_RE.fullmatch(order_id)
        or not isinstance(status, str)
        or not ORDER_STATUS_RE.fullmatch(status)
    ):
        raise ApiError(502, "paypal_response_invalid", "PayPal sandbox returned an incomplete order.")
    approve_url = next((link.get("href") for link in payload.get("links", []) if isinstance(link, dict) and link.get("rel") in {"approve", "payer-action"}), None)
    if approve_url is not None:
        if not isinstance(approve_url, str):
            raise ApiError(502, "paypal_response_invalid", "PayPal sandbox returned an invalid approval URL.")
        parsed = urllib.parse.urlparse(approve_url)
        if parsed.scheme != "https" or parsed.hostname != "www.sandbox.paypal.com":
            raise ApiError(502, "paypal_response_invalid", "PayPal sandbox returned an untrusted approval URL.")
    return {"id": order_id, "status": status, "approve_url": approve_url, "mode": mode}


class ScopePayState:
    def __init__(self):
        client_id = os.environ.get("PAYPAL_CLIENT_ID", "").strip()
        client_secret = os.environ.get("PAYPAL_CLIENT_SECRET", "").strip()
        if bool(client_id) != bool(client_secret):
            raise RuntimeError("Set both PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET, or neither.")
        self.paypal = PayPalSandbox(client_id, client_secret) if client_id else None
        self.demo_orders: dict[str, dict[str, str]] = {}

    @property
    def mode(self) -> str:
        return "sandbox" if self.paypal else "demo"

    def create(self, amount: str, fingerprint: str) -> dict[str, Any]:
        if self.paypal:
            return self.paypal.create_order(amount, fingerprint)
        order_id = "DEMO-" + secrets.token_hex(8).upper()
        self.demo_orders[order_id] = {"amount": amount, "fingerprint": fingerprint, "status": "CREATED"}
        return {"id": order_id, "status": "CREATED", "approve_url": None, "mode": "demo"}

    def capture(self, order_id: str) -> dict[str, Any]:
        if self.paypal:
            return self.paypal.capture_order(order_id)
        order = self.demo_orders.get(order_id)
        if not order:
            raise ApiError(404, "order_not_found", "Demo order was not found in this server session.")
        order["status"] = "COMPLETED"
        return {"id": order_id, "status": "COMPLETED", "approve_url": None, "mode": "demo"}


class ScopePayHandler(BaseHTTPRequestHandler):
    state: ScopePayState

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ApiError(400, "invalid_length", "Invalid request length.")
        if length <= 0 or length > MAX_BODY:
            raise ApiError(413, "invalid_size", "JSON body must be between 1 byte and 32 KB.")
        try:
            payload = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApiError(400, "invalid_json", "Request body must be valid JSON.")
        if not isinstance(payload, dict):
            raise ApiError(400, "invalid_json", "Request body must be a JSON object.")
        return payload

    def do_GET(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/status":
            self._json(200, {"version": VERSION, "mode": self.state.mode, "real_money": False, "configured": bool(self.state.paypal)})
            return
        if path in {"/", "/index.html"}:
            data = (ROOT / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(data)
            return
        self._json(404, {"error": "not_found", "message": "Route not found."})

    def do_POST(self) -> None:
        try:
            path = urllib.parse.urlparse(self.path).path
            if path == "/api/orders":
                payload = self._read_json()
                amount = parse_amount(payload.get("amount"))
                fingerprint = str(payload.get("fingerprint") or "").lower()
                if not FINGERPRINT_RE.fullmatch(fingerprint):
                    raise ApiError(400, "invalid_fingerprint", "Agreement fingerprint must be 64 lowercase hex characters.")
                self._json(201, self.state.create(amount, fingerprint))
                return
            match = re.fullmatch(r"/api/orders/([^/]+)/capture", path)
            if match:
                order_id = urllib.parse.unquote(match.group(1))
                if not ORDER_ID_RE.fullmatch(order_id):
                    raise ApiError(400, "invalid_order_id", "Order ID format is invalid.")
                self._read_json()
                self._json(200, self.state.capture(order_id))
                return
            raise ApiError(404, "not_found", "Route not found.")
        except ApiError as exc:
            self._json(exc.status, {"error": exc.code, "message": str(exc)})
        except Exception:
            self._json(500, {"error": "internal_error", "message": "Unexpected server error."})


def make_server(host: str, port: int) -> ThreadingHTTPServer:
    if host not in LOOPBACK_HOSTS and os.environ.get("SCOPEPAY_ALLOW_REMOTE") != "1":
        raise RuntimeError("Remote binding is disabled. Use a loopback host or explicitly set SCOPEPAY_ALLOW_REMOTE=1.")
    state = ScopePayState()
    handler = type("ConfiguredScopePayHandler", (ScopePayHandler,), {"state": state})
    return ThreadingHTTPServer((host, port), handler)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run ScopePay AI 0.2.0 locally")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    server = make_server(args.host, args.port)
    print(json.dumps({"url": f"http://{args.host}:{server.server_port}/", "mode": server.RequestHandlerClass.state.mode, "real_money": False}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

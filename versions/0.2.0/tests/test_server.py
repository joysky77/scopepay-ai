from __future__ import annotations

import base64
import io
import json
import os
import unittest
from unittest.mock import patch

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class ScopePayServerTests(unittest.TestCase):
    def test_amount_boundaries(self):
        self.assertEqual(server.parse_amount("12"), "12.00")
        self.assertEqual(server.parse_amount("1.005"), "1.00")
        for value in ("0", "10000.01", "abc", None):
            with self.assertRaises(server.ApiError):
                server.parse_amount(value)

    def test_demo_create_and_capture_are_session_bound(self):
        with patch.dict(os.environ, {}, clear=True):
            state = server.ScopePayState()
        fingerprint = "a" * 64
        created = state.create("12.00", fingerprint)
        self.assertEqual(created["mode"], "demo")
        self.assertEqual(created["status"], "CREATED")
        self.assertTrue(created["id"].startswith("DEMO-"))
        self.assertEqual(state.capture(created["id"])["status"], "COMPLETED")
        with self.assertRaises(server.ApiError):
            state.capture("DEMO-0000000000000000")

    def test_sandbox_requests_keep_secret_in_basic_auth_and_brief_out(self):
        calls = []

        def fake_urlopen(request, timeout):
            calls.append((request, timeout))
            if request.full_url.endswith("/v1/oauth2/token"):
                return FakeResponse(json.dumps({"access_token": "test-token"}).encode())
            if request.full_url.endswith("/v2/checkout/orders"):
                return FakeResponse(json.dumps({"id": "ORDER-12345678", "status": "CREATED", "links": [{"rel": "approve", "href": "https://www.sandbox.paypal.com/approve"}]}).encode())
            if request.full_url.endswith("/capture"):
                return FakeResponse(json.dumps({"id": "ORDER-12345678", "status": "COMPLETED", "links": []}).encode())
            raise AssertionError(request.full_url)

        with patch.dict(os.environ, {}, clear=True), patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client = server.PayPalSandbox("client-id", "client-secret")
            created = client.create_order("12.00", "b" * 64)
            captured = client.capture_order(created["id"])
        self.assertEqual(created["approve_url"], "https://www.sandbox.paypal.com/approve")
        self.assertEqual(captured["status"], "COMPLETED")
        token_request, order_request, capture_token_request, capture_request = [item[0] for item in calls]
        expected = base64.b64encode(b"client-id:client-secret").decode()
        self.assertEqual(token_request.headers["Authorization"], f"Basic {expected}")
        self.assertEqual(capture_token_request.headers["Authorization"], f"Basic {expected}")
        order_payload = json.loads(order_request.data)
        serialized = json.dumps(order_payload)
        self.assertNotIn("client-secret", serialized)
        self.assertNotIn("brief", serialized.lower())
        self.assertEqual(order_payload["purchase_units"][0]["amount"], {"currency_code": "USD", "value": "12.00"})
        self.assertEqual(order_request.headers["Paypal-request-id"], "scopepay-" + "b" * 32)
        self.assertTrue(capture_request.full_url.endswith("/v2/checkout/orders/ORDER-12345678/capture"))

    def test_partial_credentials_and_non_loopback_override_fail_closed(self):
        with patch.dict(os.environ, {"PAYPAL_CLIENT_ID": "only-id"}, clear=True):
            with self.assertRaises(RuntimeError):
                server.ScopePayState()
        with patch.dict(os.environ, {"PAYPAL_API_BASE": "https://example.com"}, clear=True):
            with self.assertRaises(RuntimeError):
                server.api_base()

    def test_untrusted_paypal_response_and_remote_bind_fail_closed(self):
        with self.assertRaises(server.ApiError):
            server.normalize_order({"id": "<script>alert(1)</script>", "status": "CREATED", "links": []}, "sandbox")
        with self.assertRaises(server.ApiError):
            server.normalize_order({
                "id": "ORDER-12345678", "status": "CREATED",
                "links": [{"rel": "approve", "href": "https://evil.example/checkout"}],
            }, "sandbox")
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                server.make_server("0.0.0.0", 0)


if __name__ == "__main__":
    unittest.main()

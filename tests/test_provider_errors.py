from contextlib import redirect_stdout
from io import BytesIO, StringIO
import json
from pathlib import Path
import socket
import ssl
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from vancecode.provider import OpenAICompatibleProvider, ProviderError
from vancecode.evaluation import evaluate, main
from vancecode.benchmarks import BENCHMARKS


class ProviderDiagnosticTests(unittest.TestCase):
    def test_network_errors_are_classified_without_leaking_details(self):
        cases = [(URLError(socket.gaierror(-2, "secret-url")), "dns_error"),
                 (URLError(ssl.SSLCertVerificationError(1, "secret-cert")), "tls_certificate_error"),
                 (URLError(ssl.SSLError(1, "secret-handshake")), "tls_error"),
                 (URLError(TimeoutError("secret-timeout")), "timeout"),
                 (TimeoutError("secret-timeout"), "timeout"),
                 (URLError(OSError("secret-connection")), "connection_error")]
        provider = OpenAICompatibleProvider("secret-key", "test-model")
        for error, kind in cases:
            with self.subTest(kind=kind), patch("vancecode.provider.urlopen", side_effect=error):
                with self.assertRaises(ProviderError) as caught:
                    provider.complete([], [])
                self.assertEqual(caught.exception.diagnostic(), {"kind": kind, "http_status": None})
                self.assertNotIn("secret", str(caught.exception))

    def test_http_status_is_preserved_but_body_is_not(self):
        self.assertEqual(ProviderError("hidden", kind="secret", http_status="secret").diagnostic(),
                         {"kind": "provider_error", "http_status": None})
        provider = OpenAICompatibleProvider("secret-key", "test-model")
        for status in (400, 401, 403, 404, 429, 503):
            error = HTTPError("https://private-url", status, "secret-reason", {}, BytesIO(b"secret-body"))
            with patch("vancecode.provider.urlopen", side_effect=error):
                with self.assertRaises(ProviderError) as caught:
                    provider.complete([], [])
            self.assertEqual(caught.exception.diagnostic(), {"kind": "http_error", "http_status": status})
            self.assertNotIn("secret", str(caught.exception))

    def test_incomplete_and_invalid_responses_are_distinct(self):
        provider = OpenAICompatibleProvider("key", "model")
        for payload, kind in (({"choices": [{"finish_reason": "secret-reason"}]}, "incomplete_response"),
                              ({}, "invalid_response")):
            with patch("vancecode.provider.urlopen", return_value=BytesIO(json.dumps(payload).encode())):
                with self.assertRaises(ProviderError) as caught:
                    provider.complete([], [])
            self.assertEqual(caught.exception.kind, kind)
            self.assertNotIn("secret", str(caught.exception))

    def test_diagnostic_reaches_report_without_raw_message(self):
        class Broken:
            def complete(self, messages, tools):
                raise ProviderError("secret-body", kind="http_error", http_status=429)
        report = evaluate(lambda _: Broken(), mode="live", cases=BENCHMARKS[:1])
        self.assertEqual(report["runs"][0]["provider_error"], {"kind": "http_error", "http_status": 429})
        self.assertNotIn("secret-body", json.dumps(report))

    def test_cli_prints_safe_diagnostic(self):
        report = {"mode": "live", "summary": {"passed": 0, "runs": 1, "failed": 1},
                  "runs": [{"case": "shipping_discount", "provider_error": {
                      "kind": "tls_certificate_error", "http_status": None}}]}
        with tempfile.TemporaryDirectory() as directory, patch(
                "vancecode.evaluation.evaluate", return_value=report), redirect_stdout(StringIO()) as stdout:
            code = main(["--output", str(Path(directory) / "report.json")])
        self.assertEqual(code, 1)
        self.assertIn("shipping_discount: tls_certificate_error", stdout.getvalue())

    def test_google_http_error_extracts_codes_without_exposing_message(self):
        provider = OpenAICompatibleProvider("secret-key", "test-model")
        payload = {"error": {"status": "INVALID_ARGUMENT", "message": "API key not valid: secret-key",
                             "details": [{"reason": "API_KEY_INVALID", "metadata": {"secret": "private"}}]}}
        error = HTTPError("https://private", 400, "hidden", {}, BytesIO(json.dumps(payload).encode()))
        with patch("vancecode.provider.urlopen", side_effect=error):
            with self.assertRaises(ProviderError) as caught:
                provider.complete([], [])
        diagnostic = caught.exception.diagnostic()
        self.assertEqual(diagnostic["provider_reason"], "API_KEY_INVALID")
        self.assertEqual(diagnostic["request_issue"], "invalid_api_key")
        self.assertNotIn("secret", json.dumps(diagnostic))
        self.assertNotIn("private", json.dumps(diagnostic))

    def test_google_schema_errors_and_unknown_codes_are_filtered(self):
        from vancecode.provider import http_diagnostic
        for message, issue in (("parameters.properties: should be non-empty for OBJECT type", "empty_object_schema"),
                               ('Unknown name "additionalProperties"', "unsupported_schema_field")):
            result = http_diagnostic(json.dumps([{"error": {"message": message}}]).encode())
            self.assertEqual(result["request_issue"], issue)
            self.assertEqual(result["provider_message"], message)
        self.assertEqual(http_diagnostic(b'{"error":{"status":"secret","details":[{"reason":"secret"}]}}'), {})
        self.assertEqual(http_diagnostic(b'not json'), {})

    def test_error_message_is_redacted_bounded_and_printed(self):
        from vancecode.provider import http_diagnostic, safe_provider_message
        secret = "not-a-standard-key-value"
        text = "Invalid request: " + secret + " https://example.com/?key=private Bearer hidden-token\n" + "x" * 2000
        diagnostic = http_diagnostic(json.dumps({"error": {"message": text}}).encode(), secret)
        message = diagnostic["provider_message"]
        self.assertNotIn(secret, message)
        self.assertNotIn("hidden-token", message)
        self.assertNotIn("example.com", message)
        self.assertLessEqual(len(message), 1200)
        self.assertNotIn("\n", message)
        self.assertNotIn("private", safe_provider_message("api_key=private"))
        report = {"mode": "live", "summary": {"passed": 0, "runs": 1, "failed": 1},
                  "runs": [{"case": "shipping_discount", "provider_error": {
                      "kind": "http_error", "http_status": 400, "provider_message": "Unknown field minimum"}}]}
        with tempfile.TemporaryDirectory() as directory, patch(
                "vancecode.evaluation.evaluate", return_value=report), redirect_stdout(StringIO()) as output:
            main(["--output", str(Path(directory) / "report.json")])
        self.assertIn("Unknown field minimum", output.getvalue())

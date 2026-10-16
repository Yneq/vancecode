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

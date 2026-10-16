"""The loop depends on a Protocol, not an API client."""
import json
import socket
import ssl
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

STATUSES = {"INVALID_ARGUMENT", "UNAUTHENTICATED", "PERMISSION_DENIED", "NOT_FOUND",
            "RESOURCE_EXHAUSTED", "FAILED_PRECONDITION", "INTERNAL", "UNAVAILABLE"}
REASONS = {"API_KEY_INVALID", "API_KEY_EXPIRED", "API_KEY_BLOCKED", "API_KEY_SERVICE_BLOCKED",
           "API_KEY_HTTP_REFERRER_BLOCKED", "API_KEY_IP_ADDRESS_BLOCKED", "SERVICE_DISABLED",
           "BILLING_DISABLED", "CONSUMER_INVALID", "ACCESS_TOKEN_EXPIRED", "RATE_LIMIT_EXCEEDED"}
ISSUES = {"unsupported_schema_field", "empty_object_schema", "invalid_api_key", "blocked_api_key"}


def http_diagnostic(body: bytes) -> dict:
    """Extract allowlisted codes only; never return provider message text."""
    try:
        data = json.loads(body)
        if isinstance(data, list):
            data = data[0]
        error = data.get("error", {})
        if not isinstance(error, dict):
            return {}
        result = {}
        if error.get("status") in STATUSES:
            result["provider_status"] = error["status"]
        for detail in error.get("details", []) or []:
            if isinstance(detail, dict) and detail.get("reason") in REASONS:
                result["provider_reason"] = detail["reason"]
                break
        message = str(error.get("message", "")).lower()
        if "api key not valid" in message or "api key expired" in message:
            result["request_issue"] = "invalid_api_key"
        elif "key" in message and "leaked" in message:
            result["request_issue"] = "blocked_api_key"
        elif "should be non-empty" in message and "properties" in message:
            result["request_issue"] = "empty_object_schema"
        elif "unknown name" in message and any(s in message for s in ("additionalproperties", "additional_properties", "minimum")):
            result["request_issue"] = "unsupported_schema_field"
        return result
    except (ValueError, TypeError, AttributeError, IndexError):
        return {}


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, kind: str = "provider_error", http_status: int | None = None,
                 provider_status=None, provider_reason=None, request_issue=None):
        super().__init__(message)
        allowed = {"provider_error", "http_error", "dns_error", "tls_certificate_error",
                   "tls_error", "timeout", "connection_error", "invalid_response", "incomplete_response"}
        self.kind = kind if kind in allowed else "provider_error"
        self.http_status = http_status if type(http_status) is int and 100 <= http_status <= 599 else None
        self.details = {k: v for k, v, allowed_values in (
            ("provider_status", provider_status, STATUSES), ("provider_reason", provider_reason, REASONS),
            ("request_issue", request_issue, ISSUES)) if isinstance(v, str) and v in allowed_values}

    def diagnostic(self) -> dict:
        # Only locally generated enums and numeric status codes, never an
        # exception string, request URL, provider body or credential.
        return {"kind": self.kind, "http_status": self.http_status, **self.details}


class Provider(Protocol):
    def complete(self, messages: list[dict], tools: list[dict]) -> dict: ...


class OpenAICompatibleProvider:
    def __init__(self, api_key: str, model: str,
                 base_url: str = "https://api.openai.com/v1", timeout: float = 60):
        if not api_key or not model:
            raise ValueError("Set OPENAI_API_KEY and VANCECODE_MODEL in environment or .env")
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("Provider URL must be HTTPS without embedded credentials")
        self.api_key, self.model = api_key, model
        self.url, self.timeout = base_url.rstrip("/") + "/chat/completions", timeout

    def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        body = json.dumps({"model": self.model, "messages": messages,
                           "tools": tools, "tool_choice": "auto"}).encode()
        request = Request(self.url, data=body, headers={
            "Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.load(response)
            choice = payload["choices"][0]
            if choice.get("finish_reason") not in ("stop", "tool_calls"):
                raise ProviderError("Model response incomplete", kind="incomplete_response")
            message = choice["message"]
            if message.get("role") != "assistant":
                raise ValueError("Expected assistant message")
            return {k: message[k] for k in ("role", "content", "tool_calls") if k in message}
        except HTTPError as exc:
            status = exc.code
            try:
                details = http_diagnostic(exc.read(16_384))
            except OSError:
                details = {}
            finally:
                exc.close()
            raise ProviderError(f"Provider HTTP {status}; check endpoint, model and credentials",
                                kind="http_error", http_status=status, **details) from None
        except (URLError, TimeoutError, OSError) as exc:
            reason = exc.reason if isinstance(exc, URLError) else exc
            if isinstance(reason, socket.gaierror):
                kind = "dns_error"
            elif isinstance(reason, ssl.SSLCertVerificationError):
                kind = "tls_certificate_error"
            elif isinstance(reason, ssl.SSLError):
                kind = "tls_error"
            elif isinstance(reason, TimeoutError):
                kind = "timeout"
            else:
                kind = "connection_error"
            raise ProviderError(f"Provider connection failed: {kind}", kind=kind) from None
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError("Invalid provider response", kind="invalid_response") from None

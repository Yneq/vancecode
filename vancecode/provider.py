"""The loop depends on a Protocol, not an API client."""
import json
import socket
import ssl
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, kind: str = "provider_error", http_status: int | None = None):
        super().__init__(message)
        allowed = {"provider_error", "http_error", "dns_error", "tls_certificate_error",
                   "tls_error", "timeout", "connection_error", "invalid_response", "incomplete_response"}
        self.kind = kind if kind in allowed else "provider_error"
        self.http_status = http_status if type(http_status) is int and 100 <= http_status <= 599 else None

    def diagnostic(self) -> dict:
        # Only locally generated enums and numeric status codes, never an
        # exception string, request URL, provider body or credential.
        return {"kind": self.kind, "http_status": self.http_status}


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
            exc.close()
            raise ProviderError(f"Provider HTTP {status}; check endpoint, model and credentials",
                                kind="http_error", http_status=status) from None
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

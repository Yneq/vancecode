"""The loop depends on a Protocol, not an API client."""
import json
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class ProviderError(RuntimeError):
    pass


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
                raise ProviderError("Model response incomplete: " + str(choice.get("finish_reason")))
            message = choice["message"]
            if message.get("role") != "assistant":
                raise ValueError("Expected assistant message")
            return {k: message[k] for k in ("role", "content", "tool_calls") if k in message}
        except HTTPError as exc:
            raise ProviderError(f"Provider HTTP {exc.code}; check endpoint, model and credentials") from None
        except (URLError, TimeoutError, OSError) as exc:
            raise ProviderError(f"Provider connection failed ({type(exc).__name__})") from None
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError("Invalid provider response") from exc

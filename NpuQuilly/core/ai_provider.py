"""OpenAI-compatible chat client (non-streaming). Lazy httpx import."""
from typing import Any


class AIProvider:
    def __init__(self, timeout: float = 600.0):
        self.base_url: str | None = None
        self.api_key: str = ""
        self.model = "grammar-fast"
        self.timeout = timeout
        self._client = None

    def configure(self, base_url: str, api_key: str, model: str):
        import httpx
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or ""
        self.model = model
        headers = {"Content-Type": "application/json"}
        if self.api_key and self.api_key != "dummy":
            headers["Authorization"] = f"Bearer {self.api_key}"
        elif self.api_key == "dummy":
            headers["Authorization"] = "Bearer dummy"  # local servers accept anything
        self._client = httpx.Client(base_url=self.base_url, headers=headers,
                                    timeout=httpx.Timeout(self.timeout, connect=5.0),
                                    trust_env=False)

    @property
    def configured(self) -> bool:
        return self._client is not None

    def complete(self, messages, temperature: float = 0.3, max_tokens: Any = None,
                 extra: dict | None = None, model: str | None = None) -> str:
        if not self.configured:
            raise ValueError("Provider not configured")
        payload: dict = {"model": model or self.model, "messages": messages,
                         "temperature": temperature, "stream": False}
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if extra:
            payload.update(extra)
        import httpx
        try:
            r = self._client.post("/chat/completions", json=payload)
        except httpx.ConnectError as e:
            raise RuntimeError(f"Cannot reach the model server at {self.base_url}. "
                               "Start the server or check the API settings.") from e
        except httpx.ReadTimeout as e:
            raise RuntimeError("The model request timed out. Check the server log; "
                               "the first GPU/NPU compilation may take several minutes.") from e
        if r.is_error:
            try:
                detail = r.json().get("detail", r.text)
            except (ValueError, AttributeError):
                detail = r.text
            raise RuntimeError(f"Model server returned HTTP {r.status_code}: {str(detail)[:500]}")
        data = r.json()
        try:
            choice = data["choices"][0]
            if choice.get("finish_reason") == "length":
                raise RuntimeError("The model truncated its answer. Select a shorter passage.")
            content = choice["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise RuntimeError("The model returned an empty answer; selected text was preserved.")
            return content
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError("Bad API response: missing completion fields.") from e

    def close(self):
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

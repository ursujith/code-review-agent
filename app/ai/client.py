from __future__ import annotations

import json
import httpx


class AIProviderError(Exception):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


class OpenAICompatibleClient:
    """Small adapter for providers exposing the OpenAI Chat Completions API."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        timeout: float = 90.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("AI provider API key is required")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.transport = transport

    async def complete_json(self, system_prompt: str, user_prompt: str) -> dict:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise AIProviderError("AI provider request timed out", 504) from exc
        except httpx.RequestError as exc:
            raise AIProviderError("Could not connect to AI provider", 502) from exc

        if response.status_code in (401, 403):
            raise AIProviderError("AI provider rejected the configured credentials", 502)
        if response.status_code == 429:
            raise AIProviderError("AI provider rate limit reached; retry later", 429)
        if response.status_code >= 500:
            raise AIProviderError("AI provider is temporarily unavailable", 502)
        if response.is_error:
            raise AIProviderError(f"AI provider request failed ({response.status_code})", 502)
        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            result = json.loads(content)
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise AIProviderError("AI provider returned an invalid review response") from exc
        if not isinstance(result, dict):
            raise AIProviderError("AI provider review response must be a JSON object")
        return result

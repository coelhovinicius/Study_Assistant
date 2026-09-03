"""Provedor de IA: Google Gemini (segundo elo da cascata)."""

from __future__ import annotations

from study_assistant.infrastructure.ai_providers.base import BaseAIProvider


class GeminiProvider(BaseAIProvider):
    def __init__(self, *, api_key: str, model: str, timeout_seconds: float = 90.0) -> None:
        super().__init__(model=model, timeout_seconds=timeout_seconds)
        self._api_key = api_key

    @property
    def provider_name(self) -> str:
        return "Google Gemini"

    def _call_api(self, prompt: str) -> str:
        from google import genai

        client = genai.Client(api_key=self._api_key)
        response = client.models.generate_content(model=self._model, contents=prompt)
        return response.text or ""

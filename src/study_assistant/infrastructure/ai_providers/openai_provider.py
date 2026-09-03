"""Provedor de IA: OpenAI (primeiro elo da cascata)."""

from __future__ import annotations

from study_assistant.infrastructure.ai_providers.base import BaseAIProvider


class OpenAIProvider(BaseAIProvider):
    def __init__(self, *, api_key: str, model: str, timeout_seconds: float = 90.0) -> None:
        super().__init__(model=model, timeout_seconds=timeout_seconds)
        self._api_key = api_key

    @property
    def provider_name(self) -> str:
        return "OpenAI"

    def _call_api(self, prompt: str) -> str:
        from openai import OpenAI

        client = OpenAI(api_key=self._api_key, timeout=self._timeout_seconds)
        response = client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content or ""

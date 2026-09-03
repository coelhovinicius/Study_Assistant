"""Provedor de IA: Mistral (último elo da cascata)."""

from __future__ import annotations

from study_assistant.infrastructure.ai_providers.base import BaseAIProvider


class MistralProvider(BaseAIProvider):
    def __init__(self, *, api_key: str, model: str, timeout_seconds: float = 90.0) -> None:
        super().__init__(model=model, timeout_seconds=timeout_seconds)
        self._api_key = api_key

    @property
    def provider_name(self) -> str:
        return "Mistral"

    def _call_api(self, prompt: str) -> str:
        # A biblioteca 'mistralai' mudou o caminho de import entre versões;
        # tentamos o import atual (>=1.0) e caímos para o antigo se preciso,
        # pra não travar o app inteiro por causa de uma versão de dependência.
        try:
            from mistralai import Mistral
        except ImportError:
            from mistralai.client import Mistral  # type: ignore[no-redef]

        client = Mistral(api_key=self._api_key)
        response = client.chat.complete(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content or ""

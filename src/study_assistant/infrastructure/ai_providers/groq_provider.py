"""Provedor de IA: Groq.

No fluxo original em n8n, o Groq aparece DUAS vezes na cascata (uma conta/
chave de API tenta primeiro; se falhar — geralmente por limite de uso —
uma segunda conta tenta em seguida, antes de cair para o Mistral). Por
isso esta classe aceita um ``label`` opcional: a mesma implementação é
reaproveitada para os dois elos, apenas com credenciais e um rótulo de
log diferentes — sem duplicar código.
"""

from __future__ import annotations

from study_assistant.infrastructure.ai_providers.base import BaseAIProvider


class GroqProvider(BaseAIProvider):
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        label: str = "Groq",
        timeout_seconds: float = 90.0,
    ) -> None:
        super().__init__(model=model, timeout_seconds=timeout_seconds)
        self._api_key = api_key
        self._label = label

    @property
    def provider_name(self) -> str:
        return self._label

    def _call_api(self, prompt: str) -> str:
        from groq import Groq

        client = Groq(api_key=self._api_key, timeout=self._timeout_seconds)
        response = client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content or ""

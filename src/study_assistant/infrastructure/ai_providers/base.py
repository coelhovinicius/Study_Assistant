"""Classe-base para provedores de IA concretos (Template Method).

Cada provedor concreto (OpenAI, Gemini, Groq, Mistral) só precisa
implementar ``_call_api``, que faz a chamada crua à SDK correspondente e
retorna o texto de resposta. Toda a parte comum — cronometragem, tratamento
uniforme de erro, instrução de formato JSON quando pedido, validação de
resposta vazia — fica centralizada aqui, evitando duplicação entre os
quatro provedores.
"""

from __future__ import annotations

import time

from study_assistant.domain.exceptions import AIProviderError
from study_assistant.domain.ports import AIProvider, ResponseFormat

_JSON_INSTRUCTION = (
    "\n\nIMPORTANTE SOBRE O FORMATO DA RESPOSTA:\n"
    "Responda EXCLUSIVAMENTE com um único objeto JSON válido.\n"
    "Não inclua texto antes ou depois do JSON, não use blocos de código "
    "markdown (```), não adicione comentários. Apenas o JSON puro."
)


class BaseAIProvider(AIProvider):
    """Implementação comum a todos os provedores de chat completion."""

    def __init__(self, *, model: str, timeout_seconds: float = 90.0) -> None:
        self._model = model
        self._timeout_seconds = timeout_seconds

    @property
    def model(self) -> str:
        return self._model

    def generate(self, prompt: str, *, response_format: ResponseFormat = "text") -> str:
        full_prompt = prompt
        if response_format == "json":
            full_prompt = prompt + _JSON_INSTRUCTION

        start = time.monotonic()
        try:
            raw_text = self._call_api(full_prompt)
        except AIProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 - normaliza qualquer erro de SDK externa
            raise AIProviderError(self.provider_name, str(exc)) from exc
        finally:
            self.last_call_duration_ms = (time.monotonic() - start) * 1000

        text = (raw_text or "").strip()
        if not text:
            raise AIProviderError(self.provider_name, "o modelo retornou uma resposta vazia")
        return text

    def _call_api(self, prompt: str) -> str:  # pragma: no cover - abstrato na prática
        raise NotImplementedError

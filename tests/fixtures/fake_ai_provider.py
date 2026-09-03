"""Provedor de IA falso, usado nos testes para simular sucesso/falha sem
precisar de rede nem de chaves de API reais."""

from __future__ import annotations

from study_assistant.domain.exceptions import AIProviderError
from study_assistant.domain.ports import AIProvider, ResponseFormat


class FakeAIProvider(AIProvider):
    def __init__(self, name: str, *, should_fail: bool = False, response_text: str = "{}") -> None:
        self._name = name
        self._should_fail = should_fail
        self._response_text = response_text
        self.model = "fake-model"
        self.call_count = 0

    @property
    def provider_name(self) -> str:
        return self._name

    def generate(self, prompt: str, *, response_format: ResponseFormat = "text") -> str:
        self.call_count += 1
        if self._should_fail:
            raise AIProviderError(self._name, "falha simulada para teste")
        return self._response_text

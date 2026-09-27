"""Orquestrador de cascata de fallback entre provedores de IA.

Replica em Python a lógica do fluxo em n8n mostrado pelo usuário: tenta o
primeiro provedor da lista; se ele falhar (erro de rede, limite de uso,
autenticação, resposta vazia, etc.), tenta o próximo, e assim por diante,
até um responder com sucesso ou a lista se esgotar.

É um Chain of Responsibility clássico, e ao mesmo tempo implementa o
próprio port ``AIProvider`` (padrão Composite): para quem usa a cascata,
ela se comporta como "só mais um provedor de IA" — a aplicação não precisa
tratar cascata como um conceito especial.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from study_assistant.application.ai_json_utils import parse_json_response
from study_assistant.domain.entities import ProviderAttempt
from study_assistant.domain.exceptions import AIProviderError, AllProvidersFailedError, InvalidAIResponseError
from study_assistant.domain.ports import AIProvider, ResponseFormat

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CascadeRunResult:
    """Resultado de uma chamada à cascata, com detalhes de todas as tentativas."""

    text: str
    provider_name: str
    model: str
    attempts: tuple[ProviderAttempt, ...]


def _check_required_keys(provider_name: str, text: str, required_keys: tuple[str, ...]) -> None:
    """Mesma regra dos nós "JSON ..." do workflow do n8n, pro modo Python
    direto: resposta que não é JSON, ou sem alguma chave pedida, conta
    como falha DESTE provedor — a cascata segue pro próximo."""
    try:
        data = parse_json_response(text)
    except InvalidAIResponseError as exc:
        raise AIProviderError(provider_name, str(exc)) from exc
    missing = [key for key in required_keys if key not in data]
    if missing:
        raise AIProviderError(provider_name, f"JSON sem as chaves obrigatórias: {', '.join(missing)}")


class AIProviderCascade(AIProvider):
    def __init__(self, providers: list[AIProvider]) -> None:
        if not providers:
            raise ValueError("AIProviderCascade precisa de ao menos um provedor.")
        self._providers = providers
        self.last_attempts: tuple[ProviderAttempt, ...] = ()

    @property
    def provider_name(self) -> str:
        chain = " → ".join(p.provider_name for p in self._providers)
        return f"Cascata ({chain})"

    def generate(
        self,
        prompt: str,
        *,
        response_format: ResponseFormat = "text",
        required_keys: tuple[str, ...] = (),
    ) -> str:
        return self.generate_with_details(
            prompt, response_format=response_format, required_keys=required_keys
        ).text

    def generate_with_details(
        self,
        prompt: str,
        *,
        response_format: ResponseFormat = "text",
        required_keys: tuple[str, ...] = (),
    ) -> CascadeRunResult:
        attempts: list[ProviderAttempt] = []

        for provider in self._providers:
            model_label = getattr(provider, "model", "desconhecido")
            start = time.monotonic()
            try:
                text = provider.generate(prompt, response_format=response_format, required_keys=required_keys)
                if response_format == "json" and required_keys:
                    _check_required_keys(provider.provider_name, text, required_keys)
            except AIProviderError as exc:
                duration_ms = (time.monotonic() - start) * 1000
                logger.warning(
                    "Provedor %s falhou (%.0fms): %s", provider.provider_name, duration_ms, exc
                )
                attempts.append(
                    ProviderAttempt(
                        provider_name=provider.provider_name,
                        model=model_label,
                        success=False,
                        duration_ms=duration_ms,
                        error_message=str(exc),
                    )
                )
                continue

            duration_ms = (time.monotonic() - start) * 1000
            attempts.append(
                ProviderAttempt(
                    provider_name=provider.provider_name,
                    model=model_label,
                    success=True,
                    duration_ms=duration_ms,
                )
            )
            self.last_attempts = tuple(attempts)
            logger.info(
                "Provedor %s respondeu com sucesso em %.0fms", provider.provider_name, duration_ms
            )
            return CascadeRunResult(
                text=text,
                provider_name=provider.provider_name,
                model=model_label,
                attempts=tuple(attempts),
            )

        self.last_attempts = tuple(attempts)
        summary = "\n".join(f"- {a.provider_name} ({a.model}): {a.error_message}" for a in attempts)
        raise AllProvidersFailedError(summary)

"""Chamadas à IA em lotes: sem estourar a cota das IAs gratuitas e sem
perder nada do que já foi respondido.

Mesma regra de espera/retentativa do qa_testgen (``ia_retry.py``):

  * entre duas chamadas que deram certo: um intervalo proporcional ao
    tamanho do que foi enviado, pra caber no teto de tokens POR MINUTO do
    provedor mais apertado da cascata (Groq gratuito: 8.000/min) — nunca
    menos de 5s, nunca mais de 30s;
  * quando uma chamada FALHA: espera a janela cheia do rate limit (62s) e
    tenta o MESMO lote de novo, até 3 vezes.

A diferença, a pedido do usuário ("não quero perder conteúdo, muito menos
voltar pra reanalisar coisas que já coloquei para analisar"): cada resposta
é guardada assim que chega (``AIResponseStore``, no Turso), identificada
por uma impressão digital do pedido. E um lote que falha 3 vezes não vira
um buraco no resultado — a análise PAUSA (``AnalysisPausedError``). Ao
continuar (ou ao subir os mesmos arquivos de novo, até dias depois), tudo o
que já tinha resposta volta do banco na hora, sem chamar a IA.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import time
from dataclasses import dataclass
from typing import Callable, Protocol

from study_assistant.application.ai_json_utils import parse_json_response
from study_assistant.domain.entities import ProviderAttempt, SavedAIResponse
from study_assistant.domain.exceptions import (
    AIProviderError,
    AllProvidersFailedError,
    AnalysisPausedError,
    InvalidAIResponseError,
    RepositoryError,
)
from study_assistant.domain.ports import AIResponseStore
from study_assistant.infrastructure.ai_providers.cascade import AIProviderCascade

logger = logging.getLogger(__name__)

# Teto de tokens por minuto do provedor mais apertado da cascata (Groq
# gratuito: 8.000 TPM). 7.000 pra sobrar folga pra resposta, que também
# conta no mesmo limite — mesmo valor usado no qa_testgen.
TOKENS_PER_MINUTE = 7000
MIN_WAIT_BETWEEN_CALLS_SECONDS = 5.0
MAX_WAIT_BETWEEN_CALLS_SECONDS = 30.0
WAIT_AFTER_ERROR_SECONDS = 62.0
MAX_ATTEMPTS = 3

# Muda só se o jeito de montar a impressão digital mudar — invalida as
# respostas guardadas com o formato antigo.
_FINGERPRINT_VERSION = 1


class ProgressFn(Protocol):
    """Recebe mensagens de andamento pra tela: ``done=False`` é o que está
    acontecendo agora (esperando, chamando a IA); ``done=True`` é um passo
    concluído, pra ficar registrado na lista."""

    def __call__(self, message: str, *, done: bool = False) -> None: ...


@dataclass(frozen=True)
class AICallResult:
    data: dict
    provider_name: str
    model: str
    attempts: tuple[ProviderAttempt, ...]
    from_saved: bool


def estimate_tokens(text: str) -> int:
    # 1 token ≈ 4 caracteres — a mesma estimativa do qa_testgen.
    return max(len(text) // 4, 1)


def quota_wait_seconds(prompt: str) -> float:
    """Quanto esperar depois de enviar ``prompt`` pra não estourar o teto
    de tokens por minuto: a fração do minuto que ele ocupa da cota."""
    seconds = 60.0 * estimate_tokens(prompt) / TOKENS_PER_MINUTE
    return max(MIN_WAIT_BETWEEN_CALLS_SECONDS, min(seconds, MAX_WAIT_BETWEEN_CALLS_SECONDS))


# (trecho do erro em minúsculas, resumo curto, explicação em uma frase) —
# o erro cru dos provedores vem em inglês, dentro do "detalhe" do 502 do
# n8n; sem isso a pessoa lê "Request too large ... Limit 8000" e não tem
# como saber que é só a cota gratuita, e não defeito do app ou do arquivo.
_FAILURE_CAUSES: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (
        ("tokens per minute", "request too large", "tpm"),
        "cota de IA por minuto estourada",
        "A cota por minuto da IA gratuita estourou — não é erro do seu material nem do app.",
    ),
    (
        ("rate limit", "429", "too many requests"),
        "provedor de IA em rate limit",
        "Muitas chamadas em pouco tempo na conta gratuita da IA.",
    ),
    (
        ("quota", "resource_exhausted", "insufficient_quota"),
        "cota da conta de IA esgotada",
        "A cota diária/mensal da conta de IA acabou — esperar alguns minutos não resolve; "
        "é preciso liberar cota no provedor (ou tentar mais tarde).",
    ),
    (
        ("invalid api key", "unauthorized", "401", "authentication"),
        "credencial de IA inválida",
        "Credencial de IA inválida ou expirada — confira a credencial do provedor no n8n.",
    ),
    (
        ("timeout", "timed out", "connection"),
        "a IA não respondeu a tempo",
        "A resposta não chegou a tempo — o n8n pode estar fora do ar ou lento.",
    ),
    (
        ("json sem as chaves", "não é um objeto json", "json válido", "model output doesn't fit"),
        "a IA respondeu fora do formato",
        "A IA respondeu fora do formato esperado, mesmo depois de passar por todas da cascata.",
    ),
)


def describe_ai_failure(error: str) -> str:
    """Explicação em uma frase da causa de uma falha de IA — vazia quando o
    erro não bate com nenhum padrão conhecido (nada de causa inventada)."""
    text = (error or "").lower()
    for markers, _, explanation in _FAILURE_CAUSES:
        if any(marker in text for marker in markers):
            return explanation
    return ""


def _short_cause(error: str) -> str:
    text = (error or "").lower()
    for markers, summary, _ in _FAILURE_CAUSES:
        if any(marker in text for marker in markers):
            return summary
    return "falha ao chamar a IA"


def fingerprint(prompt: str, required_keys: tuple[str, ...]) -> str:
    payload = json.dumps(
        {"v": _FINGERPRINT_VERSION, "prompt": prompt, "keys": list(required_keys)},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ResilientAICaller:
    def __init__(
        self,
        cascade: AIProviderCascade,
        store: AIResponseStore,
        *,
        saved_responses_days: int = 7,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._cascade = cascade
        self._store = store
        self._saved_responses_days = saved_responses_days
        self._sleep = sleep
        self._clock = clock
        # Primeira camada, na memória do processo: mesmo com o Turso fora
        # do ar, continuar uma análise pausada não refaz o que já veio.
        self._memory: dict[str, SavedAIResponse] = {}
        # Relógio compartilhado entre análises: a cota das IAs é global, não
        # por análise — continuar logo depois de uma pausa ainda respeita
        # a espera que estava correndo.
        self._next_call_at = 0.0
        self._last_error = ""
        self.persistence_warning: str | None = None

    def purge_expired(self) -> None:
        try:
            self._store.purge_older_than(self._saved_responses_days)
        except RepositoryError as exc:
            logger.warning("Não foi possível apagar as respostas de IA antigas: %s", exc)

    def call_json(
        self,
        prompt: str,
        *,
        required_keys: tuple[str, ...],
        label: str,
        progress: ProgressFn | None = None,
    ) -> AICallResult:
        """Devolve o JSON da resposta (já com as ``required_keys``). Levanta
        ``AnalysisPausedError`` se a IA falhar ``MAX_ATTEMPTS`` vezes."""
        key = fingerprint(prompt, required_keys)

        saved = self._load(key)
        if saved is not None:
            data = self._parse(saved.text, required_keys)
            if data is not None:
                return AICallResult(data, saved.provider_name, saved.model, (), from_saved=True)

        for attempt in range(1, MAX_ATTEMPTS + 1):
            self._wait_turn(label, progress)
            if progress:
                suffix = f" (tentativa {attempt} de {MAX_ATTEMPTS})" if attempt > 1 else ""
                progress(f"{label}{suffix}…")
            try:
                run = self._cascade.generate_with_details(
                    prompt, response_format="json", required_keys=required_keys
                )
                data = self._parse(run.text, required_keys)
                if data is None:
                    raise InvalidAIResponseError(
                        f"JSON sem as chaves obrigatórias ({', '.join(required_keys)}). "
                        f"Início da resposta: {run.text[:200]!r}"
                    )
            except (AllProvidersFailedError, AIProviderError, InvalidAIResponseError) as exc:
                # Uma chamada que falhou também gastou cota — e se falhou, a
                # cota provavelmente já estourou; só a janela cheia resolve.
                self._last_error = str(exc)
                self._next_call_at = self._clock() + WAIT_AFTER_ERROR_SECONDS
                logger.warning("%s falhou (tentativa %d de %d): %s", label, attempt, MAX_ATTEMPTS, exc)
                continue

            self._last_error = ""
            self._next_call_at = self._clock() + quota_wait_seconds(prompt)
            self._keep(key, SavedAIResponse(run.text, run.provider_name, run.model), progress)
            return AICallResult(data, run.provider_name, run.model, run.attempts, from_saved=False)

        raise AnalysisPausedError(label, describe_ai_failure(self._last_error), self._last_error)

    @staticmethod
    def _parse(text: str, required_keys: tuple[str, ...]) -> dict | None:
        try:
            data = parse_json_response(text)
        except InvalidAIResponseError:
            return None
        if any(key not in data for key in required_keys):
            return None
        return data

    def _wait_turn(self, label: str, progress: ProgressFn | None) -> None:
        # Espera em pedaços curtos (e não num sleep só) pra tela mostrar a
        # contagem regressiva em vez de parecer travada.
        while (remaining := self._next_call_at - self._clock()) > 0:
            if progress:
                seconds = math.ceil(remaining)
                if self._last_error:
                    progress(
                        f"A tentativa anterior falhou ({_short_cause(self._last_error)}). "
                        f"Tentando de novo em {seconds}s — {label}"
                    )
                else:
                    progress(
                        f"Aguardando {seconds}s pra não estourar o limite por minuto das IAs "
                        f"gratuitas — a seguir: {label}"
                    )
            self._sleep(min(remaining, 2.0))

    def _load(self, key: str) -> SavedAIResponse | None:
        if key in self._memory:
            return self._memory[key]
        try:
            saved = self._store.get(key)
        except RepositoryError as exc:
            logger.warning("Não foi possível ler respostas de IA salvas: %s", exc)
            return None
        if saved is not None:
            self._memory[key] = saved
        return saved

    def _keep(self, key: str, response: SavedAIResponse, progress: ProgressFn | None) -> None:
        self._memory[key] = response
        try:
            self._store.save(key, response)
        except RepositoryError as exc:
            logger.warning("Não foi possível salvar a resposta da IA no banco: %s", exc)
            self.persistence_warning = (
                "Não foi possível salvar o progresso no banco (Turso) agora — ele ficou só na "
                "memória do servidor. Se o servidor reiniciar antes de terminar, a parte que "
                "não foi salva precisará ser pedida à IA de novo."
            )
            if progress:
                progress(f"⚠️ {self.persistence_warning}", done=True)

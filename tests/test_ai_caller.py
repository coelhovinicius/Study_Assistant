"""Testes de application/ai_caller.py — a regra de lotes do qa_testgen
(espera pela cota por minuto, 3 tentativas com 62s entre elas) mais o
pedido do usuário: "não quero perder conteúdo, muito menos voltar pra
reanalisar coisas que já coloquei para analisar". Toda resposta é guardada
assim que chega e reaproveitada sem nova chamada à IA; um lote que falha 3
vezes pausa a análise em vez de virar um buraco no resultado.

Sem rede e sem esperar de verdade: a IA é um ``ScriptedAIProvider`` e o
tempo é um ``FakeClock``.
"""

from __future__ import annotations

import json

import pytest

from study_assistant.application.ai_caller import (
    MAX_ATTEMPTS,
    MIN_WAIT_BETWEEN_CALLS_SECONDS,
    WAIT_AFTER_ERROR_SECONDS,
    ResilientAICaller,
    describe_ai_failure,
    quota_wait_seconds,
)
from study_assistant.domain.exceptions import AIProviderError, AnalysisPausedError
from study_assistant.infrastructure.ai_providers.cascade import AIProviderCascade
from tests.fixtures.fake_ai_provider import ScriptedAIProvider
from tests.fixtures.in_memory_ai_response_store import FakeClock, InMemoryAIResponseStore

_KEYS = ("titulo", "analise", "resumo")
_GOOD = json.dumps({"titulo": "T", "analise": "A", "resumo": "R"})
_TPM_ERROR = "Request too large for model openai/gpt-oss-120b ... tokens per minute (TPM): Limit 8000"


def _caller(provider: ScriptedAIProvider, store=None, clock=None) -> tuple[ResilientAICaller, FakeClock]:
    clock = clock or FakeClock()
    caller = ResilientAICaller(
        AIProviderCascade([provider]),
        store if store is not None else InMemoryAIResponseStore(),
        sleep=clock.sleep,
        clock=clock,
    )
    return caller, clock


def test_devolve_o_json_da_resposta_e_guarda_no_banco() -> None:
    store = InMemoryAIResponseStore()
    provider = ScriptedAIProvider(lambda prompt: _GOOD)
    caller, _ = _caller(provider, store)

    result = caller.call_json("prompt do lote 1", required_keys=_KEYS, label="lote 1")

    assert result.data == {"titulo": "T", "analise": "A", "resumo": "R"}
    assert result.from_saved is False
    assert len(store.saved) == 1
    assert provider.required_keys == [_KEYS]  # as chaves chegam até o provedor (n8n valida)


def test_mesmo_pedido_de_novo_nao_chama_a_ia() -> None:
    provider = ScriptedAIProvider(lambda prompt: _GOOD)
    caller, _ = _caller(provider)

    caller.call_json("prompt do lote 1", required_keys=_KEYS, label="lote 1")
    again = caller.call_json("prompt do lote 1", required_keys=_KEYS, label="lote 1")

    assert again.from_saved is True
    assert again.data["analise"] == "A"
    assert len(provider.prompts) == 1


def test_resposta_salva_no_banco_sobrevive_a_um_servidor_reiniciado() -> None:
    """Outro ResilientAICaller (memória vazia, como depois de reiniciar o
    servidor ou fechar o navegador) com o mesmo banco: nada é pedido de novo."""
    store = InMemoryAIResponseStore()
    first_provider = ScriptedAIProvider(lambda prompt: _GOOD)
    _caller(first_provider, store)[0].call_json("prompt do lote 1", required_keys=_KEYS, label="lote 1")

    second_provider = ScriptedAIProvider(lambda prompt: _GOOD)
    result = _caller(second_provider, store)[0].call_json("prompt do lote 1", required_keys=_KEYS, label="lote 1")

    assert result.from_saved is True
    assert second_provider.prompts == []


def test_falha_passageira_espera_62s_e_tenta_o_mesmo_lote_de_novo() -> None:
    replies = iter([AIProviderError("n8n", _TPM_ERROR), _GOOD])

    def responder(prompt: str) -> str:
        reply = next(replies)
        if isinstance(reply, Exception):
            raise reply
        return reply

    provider = ScriptedAIProvider(responder)
    caller, clock = _caller(provider)

    result = caller.call_json("prompt do lote 1", required_keys=_KEYS, label="lote 1")

    assert result.data["titulo"] == "T"
    assert provider.prompts == ["prompt do lote 1", "prompt do lote 1"]
    assert clock.total_slept == pytest.approx(WAIT_AFTER_ERROR_SECONDS)


def test_tres_falhas_pausam_a_analise_com_o_motivo_em_portugues() -> None:
    def responder(prompt: str) -> str:
        raise AIProviderError("n8n", _TPM_ERROR)

    provider = ScriptedAIProvider(responder)
    caller, _ = _caller(provider)

    with pytest.raises(AnalysisPausedError) as info:
        caller.call_json("prompt do lote 2", required_keys=_KEYS, label="Apostila, parte 2 de 4")

    assert len(provider.prompts) == MAX_ATTEMPTS
    assert info.value.step_label == "Apostila, parte 2 de 4"
    assert "cota por minuto" in info.value.cause
    assert "tokens per minute" in info.value.detail


def test_resposta_sem_as_chaves_pedidas_conta_como_falha() -> None:
    replies = iter([json.dumps({"titulo": "só o título"}), _GOOD])
    provider = ScriptedAIProvider(lambda prompt: next(replies))
    caller, _ = _caller(provider)

    result = caller.call_json("prompt", required_keys=_KEYS, label="lote")

    assert result.data["resumo"] == "R"
    assert len(provider.prompts) == 2


def test_resposta_incompleta_nunca_e_guardada() -> None:
    def responder(prompt: str) -> str:
        return "desculpe, não consigo"

    store = InMemoryAIResponseStore()
    caller, _ = _caller(ScriptedAIProvider(responder), store)

    with pytest.raises(AnalysisPausedError):
        caller.call_json("prompt", required_keys=_KEYS, label="lote")

    assert store.saved == {}


def test_espaca_as_chamadas_pela_cota_por_minuto() -> None:
    provider = ScriptedAIProvider(lambda prompt: _GOOD)
    caller, clock = _caller(provider)
    big_prompt = "x" * 40_000  # ~10 mil tokens: passa do teto, espera o máximo

    caller.call_json(big_prompt, required_keys=_KEYS, label="lote 1")
    assert clock.sleeps == []  # a primeira chamada não espera
    caller.call_json("prompt do lote 2", required_keys=_KEYS, label="lote 2")

    assert clock.total_slept == pytest.approx(quota_wait_seconds(big_prompt))


def test_resposta_reaproveitada_nao_espera_a_cota() -> None:
    provider = ScriptedAIProvider(lambda prompt: _GOOD)
    caller, clock = _caller(provider)

    caller.call_json("prompt do lote 1", required_keys=_KEYS, label="lote 1")
    caller.call_json("prompt do lote 1", required_keys=_KEYS, label="lote 1")

    assert clock.sleeps == []


def test_espera_entre_chamadas_tem_piso_de_5s() -> None:
    assert quota_wait_seconds("curto") == MIN_WAIT_BETWEEN_CALLS_SECONDS


def test_banco_fora_do_ar_nao_trava_a_analise_e_avisa() -> None:
    provider = ScriptedAIProvider(lambda prompt: _GOOD)
    caller, _ = _caller(provider, InMemoryAIResponseStore(broken=True))
    messages: list[str] = []

    caller.call_json("prompt", required_keys=_KEYS, label="lote", progress=lambda m, done=False: messages.append(m))
    again = caller.call_json("prompt", required_keys=_KEYS, label="lote")

    assert caller.persistence_warning
    assert any("Turso" in m for m in messages)
    assert again.from_saved is True  # ainda reaproveita, pela memória do servidor
    assert len(provider.prompts) == 1


def test_limpeza_das_respostas_antigas_usa_os_dias_configurados() -> None:
    store = InMemoryAIResponseStore()
    caller = ResilientAICaller(AIProviderCascade([ScriptedAIProvider(lambda p: _GOOD)]), store, saved_responses_days=7)

    caller.purge_expired()

    assert store.purged_days == [7]


def test_limpeza_com_banco_fora_do_ar_nao_levanta() -> None:
    caller = ResilientAICaller(
        AIProviderCascade([ScriptedAIProvider(lambda p: _GOOD)]), InMemoryAIResponseStore(broken=True)
    )
    caller.purge_expired()  # não pode levantar


def test_motivo_desconhecido_nao_ganha_causa_inventada() -> None:
    assert describe_ai_failure("algo completamente inesperado") == ""
    assert "Muitas chamadas" in describe_ai_failure("Error 429: Too Many Requests")

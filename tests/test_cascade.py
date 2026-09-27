"""Testes da cascata de fallback entre provedores de IA."""

from __future__ import annotations

import pytest

from study_assistant.domain.exceptions import AllProvidersFailedError
from study_assistant.infrastructure.ai_providers.cascade import AIProviderCascade
from tests.fixtures.fake_ai_provider import FakeAIProvider


def test_usa_o_primeiro_provedor_quando_ele_funciona() -> None:
    provider_a = FakeAIProvider("A", response_text='{"ok": true}')
    provider_b = FakeAIProvider("B", response_text='{"ok": true}')
    cascade = AIProviderCascade([provider_a, provider_b])

    result = cascade.generate_with_details("prompt qualquer")

    assert result.provider_name == "A"
    assert provider_a.call_count == 1
    assert provider_b.call_count == 0
    assert len(result.attempts) == 1
    assert result.attempts[0].success is True


def test_cai_para_o_proximo_provedor_quando_o_primeiro_falha() -> None:
    provider_a = FakeAIProvider("A", should_fail=True)
    provider_b = FakeAIProvider("B", response_text='{"ok": true}')
    cascade = AIProviderCascade([provider_a, provider_b])

    result = cascade.generate_with_details("prompt qualquer")

    assert result.provider_name == "B"
    assert len(result.attempts) == 2
    assert result.attempts[0].success is False
    assert result.attempts[0].provider_name == "A"
    assert result.attempts[1].success is True
    assert result.attempts[1].provider_name == "B"


def test_levanta_erro_quando_todos_os_provedores_falham() -> None:
    providers = [FakeAIProvider(name, should_fail=True) for name in ("A", "B", "C")]
    cascade = AIProviderCascade(providers)

    with pytest.raises(AllProvidersFailedError):
        cascade.generate_with_details("prompt qualquer")

    assert len(cascade.last_attempts) == 3
    assert all(not a.success for a in cascade.last_attempts)


def test_cascata_vazia_nao_e_permitida() -> None:
    with pytest.raises(ValueError):
        AIProviderCascade([])


def test_resposta_sem_as_chaves_pedidas_passa_para_o_proximo_provedor() -> None:
    """Modo Python direto: a mesma regra dos nós "JSON ..." do n8n."""
    provider_a = FakeAIProvider("A", response_text='{"titulo": "só isso"}')
    provider_b = FakeAIProvider("B", response_text='{"titulo": "T", "resumo": "R"}')
    cascade = AIProviderCascade([provider_a, provider_b])

    result = cascade.generate_with_details("prompt", response_format="json", required_keys=("titulo", "resumo"))

    assert result.provider_name == "B"
    assert result.attempts[0].success is False
    assert "resumo" in result.attempts[0].error_message


def test_resposta_que_nao_e_json_passa_para_o_proximo_provedor() -> None:
    provider_a = FakeAIProvider("A", response_text="desculpe, não consigo")
    provider_b = FakeAIProvider("B", response_text='{"titulo": "T"}')
    cascade = AIProviderCascade([provider_a, provider_b])

    result = cascade.generate_with_details("prompt", response_format="json", required_keys=("titulo",))

    assert result.provider_name == "B"

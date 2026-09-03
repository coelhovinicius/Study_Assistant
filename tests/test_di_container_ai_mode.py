"""Testes da decisão "n8n vs. Python direto" em
presentation/di_container.py: quando ``[n8n].webhook_url`` está
configurado, ele é o ÚNICO elo da cascata (o n8n decide o fallback
internamente); senão, a cascata é montada a partir de ``[ai.*]``, um
provedor por elo configurado."""

from __future__ import annotations

import pytest

from study_assistant.config.settings import AIProviderSettings, N8nSettings, Settings, TursoSettings
from study_assistant.infrastructure.ai_providers.gemini_provider import GeminiProvider
from study_assistant.infrastructure.ai_providers.n8n_webhook_provider import N8nWebhookProvider
from study_assistant.infrastructure.ai_providers.openai_provider import OpenAIProvider
from study_assistant.presentation.di_container import _build_ai_providers

_TURSO = TursoSettings(database_url="libsql://x.turso.io", auth_token="tok")


def _settings(*, n8n: N8nSettings, ai_cascade: list[AIProviderSettings]) -> Settings:
    from study_assistant.config.settings import AuthSettings

    return Settings(
        turso=_TURSO,
        auth=AuthSettings(username="admin", password_hash="hash"),
        n8n=n8n,
        ai_cascade=ai_cascade,
    )


def test_usa_apenas_n8n_quando_webhook_configurado() -> None:
    settings = _settings(
        n8n=N8nSettings(webhook_url="https://n8n.example.com/webhook/x"),
        ai_cascade=[
            AIProviderSettings(kind="openai", label="OpenAI", api_key="sk-x", model="gpt-5.5"),
            AIProviderSettings(kind="gemini", label="Gemini", api_key="ai-x", model="gemini-2.5-flash"),
        ],
    )

    providers = _build_ai_providers(settings)

    assert len(providers) == 1
    assert isinstance(providers[0], N8nWebhookProvider)


def test_ignora_ai_cascade_quando_n8n_configurado() -> None:
    """Mesmo com [ai.*] preenchido, se o n8n está configurado ele manda —
    a cascata Python nunca deveria rodar em paralelo com o n8n."""
    settings = _settings(
        n8n=N8nSettings(webhook_url="https://n8n.example.com/webhook/x"),
        ai_cascade=[AIProviderSettings(kind="openai", label="OpenAI", api_key="sk-x", model="gpt-5.5")],
    )

    providers = _build_ai_providers(settings)

    assert not any(isinstance(p, OpenAIProvider) for p in providers)


def test_monta_cascata_direto_em_python_quando_sem_n8n() -> None:
    settings = _settings(
        n8n=N8nSettings(webhook_url=""),
        ai_cascade=[
            AIProviderSettings(kind="openai", label="OpenAI", api_key="sk-x", model="gpt-5.5"),
            AIProviderSettings(kind="gemini", label="Gemini", api_key="ai-x", model="gemini-2.5-flash"),
        ],
    )

    providers = _build_ai_providers(settings)

    assert len(providers) == 2
    assert isinstance(providers[0], OpenAIProvider)
    assert isinstance(providers[1], GeminiProvider)


def test_pula_provedores_sem_api_key_no_modo_python() -> None:
    """_build_ai_providers usa settings.configured_ai_cascade (não
    ai_cascade cru), então um elo sem api_key/model é ignorado
    automaticamente — sem precisar de nenhuma lógica extra aqui."""
    settings = _settings(
        n8n=N8nSettings(webhook_url=""),
        ai_cascade=[
            AIProviderSettings(kind="openai", label="OpenAI", api_key="sk-x", model="gpt-5.5"),
            AIProviderSettings(kind="gemini", label="Gemini", api_key="", model="gemini-2.5-flash"),
        ],
    )

    providers = _build_ai_providers(settings)

    assert len(providers) == 1
    assert isinstance(providers[0], OpenAIProvider)


def test_levanta_erro_quando_nenhum_provedor_configurado() -> None:
    settings = _settings(n8n=N8nSettings(webhook_url=""), ai_cascade=[])

    with pytest.raises(RuntimeError):
        _build_ai_providers(settings)

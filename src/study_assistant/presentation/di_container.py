"""Composition root: aqui, e só aqui, as implementações concretas de
infraestrutura são "encaixadas" nas interfaces que a aplicação espera.

Nenhuma outra parte do código deveria precisar saber que o banco é o Turso,
que a extração de PDF usa ``pypdf``, ou que a cascata de IA é composta por
OpenAI/Gemini/Groq/Mistral nessa ordem — tudo isso é decidido uma única vez
aqui, a partir da configuração (``Settings``).
"""

from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from study_assistant.application.analysis_service import AnalyzeStudyMaterialsUseCase
from study_assistant.application.auth_service import AuthenticateAdminUseCase
from study_assistant.application.document_service import DocumentIngestionService
from study_assistant.application.extraction_service import ExtractApostilaInsightsUseCase
from study_assistant.application.history_service import HistoryService
from study_assistant.application.report_service import GenerateReportUseCase
from study_assistant.config.settings import (
    AIProviderSettings,
    AUTH_YAML_PATH,
    Settings,
    load_settings_from_streamlit,
)
from study_assistant.domain.ports import AIProvider
from study_assistant.infrastructure.ai_providers import (
    AIProviderCascade,
    GeminiProvider,
    GroqProvider,
    MistralProvider,
    N8nWebhookProvider,
    OpenAIProvider,
)
from study_assistant.infrastructure.extractors import (
    CompositeTextExtractor,
    DocxTextExtractor,
    PdfTextExtractor,
    TxtTextExtractor,
)
from study_assistant.infrastructure.persistence import TursoHttpClient, TursoSessionRepository
from study_assistant.infrastructure.report_generators import ALL_REPORT_GENERATORS
from study_assistant.infrastructure.security import BcryptPasswordHasher, ConfigUserRepository


@dataclass
class AppContainer:
    """Agrupa todos os casos de uso já prontos para a UI consumir."""

    settings: Settings
    auth_use_case: AuthenticateAdminUseCase
    document_service: DocumentIngestionService
    extraction_use_case: ExtractApostilaInsightsUseCase
    analysis_use_case: AnalyzeStudyMaterialsUseCase
    report_use_case: GenerateReportUseCase
    history_service: HistoryService
    ai_cascade: AIProviderCascade


def _build_ai_provider(config: AIProviderSettings) -> AIProvider:
    if config.kind == "openai":
        return OpenAIProvider(api_key=config.api_key, model=config.model)
    if config.kind == "gemini":
        return GeminiProvider(api_key=config.api_key, model=config.model)
    if config.kind == "groq":
        return GroqProvider(api_key=config.api_key, model=config.model, label=config.label)
    if config.kind == "mistral":
        return MistralProvider(api_key=config.api_key, model=config.model)
    raise ValueError(f"Tipo de provedor de IA desconhecido: {config.kind!r}")


def _build_ai_providers(settings: Settings) -> list[AIProvider]:
    """Decide a estratégia de IA: se ``[n8n].webhook_url`` estiver
    configurado, ele é o ÚNICO elo (o n8n já faz o fallback internamente,
    igual nos outros apps do usuário); senão, monta a cascata direto em
    Python a partir de ``[ai.*]``.
    """
    if settings.n8n.is_configured:
        return [
            N8nWebhookProvider(
                webhook_url=settings.n8n.webhook_url,
                auth_header_name=settings.n8n.auth_header_name,
                auth_header_value=settings.n8n.auth_header_value,
                timeout_seconds=settings.n8n.timeout_seconds,
            )
        ]

    providers = [_build_ai_provider(cfg) for cfg in settings.configured_ai_cascade]
    if not providers:
        raise RuntimeError(
            "Nenhum provedor de IA está configurado. Preencha "
            "st.secrets['n8n']['webhook_url'] (para usar seu n8n) OU pelo "
            "menos uma seção em st.secrets['ai'] (ex: [ai.openai]) para "
            "chamar as APIs de IA direto pelo Python."
        )
    return providers


def build_container(settings: Settings) -> AppContainer:
    if not settings.auth.is_configured:
        raise RuntimeError(
            "Nenhuma credencial de admin configurada. Rode "
            "'python scripts/create_admin_user.py' para criar seu usuário e senha "
            "(grava em auth/users.yaml, ou gera um bloco pronto para colar em "
            "st.secrets['auth'])."
        )

    turso_client = TursoHttpClient(settings.turso.database_url, settings.turso.auth_token)
    session_repository = TursoSessionRepository(turso_client)

    # Credenciais de login não vêm do Turso neste app — mesmo padrão dos
    # outros apps do usuário: st.secrets["auth"] em produção, com fallback
    # para auth/users.yaml local. O Turso fica só para o histórico salvo.
    user_repository = ConfigUserRepository(
        username=settings.auth.username,
        password_hash=settings.auth.password_hash,
        yaml_path=AUTH_YAML_PATH,
    )

    password_hasher = BcryptPasswordHasher(rounds=settings.security.bcrypt_rounds)
    auth_use_case = AuthenticateAdminUseCase(
        user_repository,
        password_hasher,
        max_attempts=settings.security.max_login_attempts,
        lock_minutes=settings.security.lock_minutes,
    )

    text_extractor = CompositeTextExtractor(
        [PdfTextExtractor(), TxtTextExtractor(), DocxTextExtractor()]
    )
    document_service = DocumentIngestionService(text_extractor)

    ai_cascade = AIProviderCascade(_build_ai_providers(settings))

    # Construído antes do HistoryService de propósito: desde que o
    # histórico passou a guardar somente o PDF, HistoryService.save() usa
    # este mesmo caso de uso pra gerar o PDF antes de persistir.
    report_use_case = GenerateReportUseCase(ALL_REPORT_GENERATORS)

    return AppContainer(
        settings=settings,
        auth_use_case=auth_use_case,
        document_service=document_service,
        extraction_use_case=ExtractApostilaInsightsUseCase(ai_cascade),
        analysis_use_case=AnalyzeStudyMaterialsUseCase(ai_cascade),
        report_use_case=report_use_case,
        history_service=HistoryService(session_repository, report_use_case),
        ai_cascade=ai_cascade,
    )


@st.cache_resource(show_spinner=False)
def get_container() -> AppContainer:
    """Constrói o container uma única vez por processo Streamlit (cacheado)."""
    settings = load_settings_from_streamlit()
    return build_container(settings)

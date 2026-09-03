"""Exceções de domínio. Camadas externas devem capturar essas exceções e
traduzi-las para algo apropriado (mensagem na UI, log, HTTP status, etc.)
em vez de deixar exceções técnicas (ex: erro de rede, erro de parsing de
PDF) vazarem para o usuário final sem contexto.
"""

from __future__ import annotations


class StudyAssistantError(Exception):
    """Classe base para todas as exceções da aplicação."""


class UnsupportedFileFormatError(StudyAssistantError):
    """Levantada quando um arquivo enviado tem extensão/formato não suportado."""


class TextExtractionError(StudyAssistantError):
    """Levantada quando não é possível extrair texto de um arquivo."""


class EmptyDocumentError(StudyAssistantError):
    """Levantada quando um documento enviado não contém texto útil."""


class AIProviderError(StudyAssistantError):
    """Erro ao chamar um provedor de IA específico (rede, autenticação, etc.)."""

    def __init__(self, provider_name: str, message: str) -> None:
        self.provider_name = provider_name
        super().__init__(f"[{provider_name}] {message}")


class AllProvidersFailedError(StudyAssistantError):
    """Levantada quando todos os provedores da cascata falharam."""

    def __init__(self, attempts_summary: str) -> None:
        super().__init__(
            "Todos os provedores de IA configurados falharam na cascata de "
            f"fallback. Detalhes:\n{attempts_summary}"
        )


class InvalidAIResponseError(StudyAssistantError):
    """A IA respondeu, mas o conteúdo não pôde ser interpretado (ex: JSON inválido)."""


class AuthenticationError(StudyAssistantError):
    """Credenciais inválidas ao tentar autenticar."""


class AccountLockedError(StudyAssistantError):
    """Conta temporariamente bloqueada por excesso de tentativas de login."""


class ReportGenerationError(StudyAssistantError):
    """Erro ao gerar o documento final de relatório em algum formato."""


class RepositoryError(StudyAssistantError):
    """Erro de persistência (Turso/banco de dados)."""

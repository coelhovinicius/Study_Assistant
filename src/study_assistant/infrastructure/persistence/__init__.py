"""Persistência: cliente Turso e repositórios concretos.

O admin não tem repositório aqui de propósito: as credenciais de login não
vêm do Turso neste app (ver ``infrastructure/security/config_user_repository.py``),
só o histórico de sessões de estudo.
"""

from study_assistant.infrastructure.persistence.session_repository import TursoSessionRepository
from study_assistant.infrastructure.persistence.turso_client import TursoHttpClient

__all__ = ["TursoHttpClient", "TursoSessionRepository"]

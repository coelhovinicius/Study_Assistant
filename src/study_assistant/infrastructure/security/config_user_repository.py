"""Repositório do usuário administrador baseado em configuração — não em
banco de dados.

Segue o mesmo padrão usado nos outros apps do usuário (``auth/auth_manager.py``):
o login "base" (aqui, o único admin) vem de ``st.secrets["auth"]`` em
produção, com fallback para o arquivo local ``auth/users.yaml`` (fora do
Git) quando não há Secrets configurados. O Turso nunca guarda essa
credencial — fica reservado para o histórico de sessões de estudo (o
"resultado salvo"), assim como nos outros apps ele é usado para dados que
não são login.

Como há um único usuário fixo, o controle de tentativas malsucedidas
(lockout) é mantido em memória, no próprio processo do Streamlit — reinicia
se o servidor reiniciar. Isso é uma simplificação aceitável para um app
pessoal de um usuário só; não seria adequado para múltiplos usuários ou
múltiplas réplicas do servidor.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from study_assistant.domain.entities import AdminUser
from study_assistant.domain.ports import UserRepository


class ConfigUserRepository(UserRepository):
    def __init__(self, *, username: str, password_hash: str, yaml_path: Path) -> None:
        self._username = username
        self._password_hash = password_hash
        self._yaml_path = yaml_path
        self._failed_attempts = 0
        self._locked_until: datetime | None = None

    def get_by_username(self, username: str) -> AdminUser | None:
        if not self._password_hash or username != self._username:
            return None
        return AdminUser(
            username=self._username,
            password_hash=self._password_hash,
            failed_login_attempts=self._failed_attempts,
            locked_until=self._locked_until,
        )

    def save(self, user: AdminUser) -> None:
        """Atualiza a credencial em memória e grava o fallback local
        (``auth/users.yaml``). Não escreve em ``st.secrets`` — isso é
        gerenciado fora do app (Streamlit Secrets), como nos outros apps.
        """
        import yaml

        self._username = user.username
        self._password_hash = user.password_hash

        self._yaml_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._yaml_path, "w", encoding="utf-8") as file:
            yaml.safe_dump(
                {"username": user.username, "password_hash": user.password_hash},
                file,
                allow_unicode=True,
            )

    def register_login_attempt(
        self, username: str, *, success: bool, lock_until_minutes: int, max_attempts: int
    ) -> None:
        if username != self._username:
            return

        if success:
            self._failed_attempts = 0
            self._locked_until = None
            return

        self._failed_attempts += 1
        if self._failed_attempts >= max_attempts:
            self._locked_until = datetime.now(timezone.utc) + timedelta(minutes=lock_until_minutes)

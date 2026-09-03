"""Repositório de usuário em memória, para testar AuthenticateAdminUseCase
sem precisar de um banco Turso de verdade."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from study_assistant.domain.entities import AdminUser
from study_assistant.domain.ports import UserRepository


class InMemoryUserRepository(UserRepository):
    def __init__(self) -> None:
        self._users: dict[str, AdminUser] = {}

    def add(self, user: AdminUser) -> None:
        self._users[user.username] = user

    def get_by_username(self, username: str) -> AdminUser | None:
        return self._users.get(username)

    def save(self, user: AdminUser) -> None:
        self._users[user.username] = user

    def register_login_attempt(
        self, username: str, *, success: bool, lock_until_minutes: int, max_attempts: int
    ) -> None:
        user = self._users.get(username)
        if user is None:
            return

        if success:
            self._users[username] = AdminUser(
                id=user.id,
                username=user.username,
                password_hash=user.password_hash,
                created_at=user.created_at,
                failed_login_attempts=0,
                locked_until=None,
            )
            return

        new_attempts = user.failed_login_attempts + 1
        locked_until = None
        if new_attempts >= max_attempts:
            locked_until = datetime.now(timezone.utc) + timedelta(minutes=lock_until_minutes)

        self._users[username] = AdminUser(
            id=user.id,
            username=user.username,
            password_hash=user.password_hash,
            created_at=user.created_at,
            failed_login_attempts=new_attempts,
            locked_until=locked_until,
        )

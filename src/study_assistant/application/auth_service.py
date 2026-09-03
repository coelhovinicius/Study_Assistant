"""Caso de uso: autenticação do (único) usuário administrador.

Inclui proteção básica contra força bruta (bloqueio temporário após N
tentativas malsucedidas) e evita vazar, pela resposta, se o problema foi o
usuário não existir ou a senha estar errada — a mensagem é sempre genérica.
"""

from __future__ import annotations

from study_assistant.domain.entities import AdminUser
from study_assistant.domain.exceptions import AccountLockedError, AuthenticationError
from study_assistant.domain.ports import PasswordHasher, UserRepository

_GENERIC_ERROR_MESSAGE = "Usuário ou senha inválidos."

# Hash "dummy" (de uma senha aleatória, nunca usada) só para gastar um tempo
# de verificação parecido com o caso real, mesmo quando o usuário não
# existe — mitiga (não elimina) enumeração de usuário por tempo de resposta.
_DUMMY_HASH = "$2b$12$C6UzMDM.H6dfI/f/IKcEeO0kw6b6JmSF6qLpuqQZeqXbHfIcQ8Vly"


class AuthenticateAdminUseCase:
    def __init__(
        self,
        user_repository: UserRepository,
        password_hasher: PasswordHasher,
        *,
        max_attempts: int = 5,
        lock_minutes: int = 15,
    ) -> None:
        self._user_repository = user_repository
        self._password_hasher = password_hasher
        self._max_attempts = max_attempts
        self._lock_minutes = lock_minutes

    def execute(self, username: str, password: str) -> AdminUser:
        user = self._user_repository.get_by_username(username)

        if user is not None and user.is_locked():
            raise AccountLockedError(
                "Conta temporariamente bloqueada por excesso de tentativas. "
                "Tente novamente em alguns minutos."
            )

        password_hash = user.password_hash if user is not None else _DUMMY_HASH
        password_ok = self._password_hasher.verify(password, password_hash)

        if user is None or not password_ok:
            if user is not None:
                self._user_repository.register_login_attempt(
                    username,
                    success=False,
                    lock_until_minutes=self._lock_minutes,
                    max_attempts=self._max_attempts,
                )
            raise AuthenticationError(_GENERIC_ERROR_MESSAGE)

        self._user_repository.register_login_attempt(
            username, success=True, lock_until_minutes=self._lock_minutes, max_attempts=self._max_attempts
        )
        return user

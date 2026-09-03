"""Testes do caso de uso de autenticação (login do admin + bloqueio por
excesso de tentativas)."""

from __future__ import annotations

import pytest

from study_assistant.application.auth_service import AuthenticateAdminUseCase
from study_assistant.domain.entities import AdminUser
from study_assistant.domain.exceptions import AccountLockedError, AuthenticationError
from study_assistant.infrastructure.security.bcrypt_password_hasher import BcryptPasswordHasher
from tests.fixtures.in_memory_user_repository import InMemoryUserRepository


@pytest.fixture
def hasher() -> BcryptPasswordHasher:
    return BcryptPasswordHasher(rounds=4)


@pytest.fixture
def user_repository(hasher: BcryptPasswordHasher) -> InMemoryUserRepository:
    repo = InMemoryUserRepository()
    repo.add(AdminUser(username="admin", password_hash=hasher.hash("senha-correta")))
    return repo


def test_login_com_credenciais_corretas_funciona(
    user_repository: InMemoryUserRepository, hasher: BcryptPasswordHasher
) -> None:
    use_case = AuthenticateAdminUseCase(user_repository, hasher, max_attempts=3, lock_minutes=15)
    user = use_case.execute("admin", "senha-correta")
    assert user.username == "admin"


def test_login_com_senha_errada_falha(
    user_repository: InMemoryUserRepository, hasher: BcryptPasswordHasher
) -> None:
    use_case = AuthenticateAdminUseCase(user_repository, hasher, max_attempts=3, lock_minutes=15)
    with pytest.raises(AuthenticationError):
        use_case.execute("admin", "senha-errada")


def test_login_com_usuario_inexistente_falha_com_mensagem_generica(
    user_repository: InMemoryUserRepository, hasher: BcryptPasswordHasher
) -> None:
    use_case = AuthenticateAdminUseCase(user_repository, hasher, max_attempts=3, lock_minutes=15)
    with pytest.raises(AuthenticationError) as exc_info:
        use_case.execute("nao-existe", "qualquer-senha")
    # a mensagem não deve revelar se o problema foi o usuário ou a senha
    assert "inválidos" in str(exc_info.value)


def test_conta_bloqueia_apos_exceder_tentativas(
    user_repository: InMemoryUserRepository, hasher: BcryptPasswordHasher
) -> None:
    use_case = AuthenticateAdminUseCase(user_repository, hasher, max_attempts=3, lock_minutes=15)

    for _ in range(3):
        with pytest.raises(AuthenticationError):
            use_case.execute("admin", "senha-errada")

    with pytest.raises(AccountLockedError):
        use_case.execute("admin", "senha-correta")  # nem senha certa entra com conta bloqueada


def test_login_bem_sucedido_zera_contador_de_tentativas(
    user_repository: InMemoryUserRepository, hasher: BcryptPasswordHasher
) -> None:
    use_case = AuthenticateAdminUseCase(user_repository, hasher, max_attempts=3, lock_minutes=15)

    with pytest.raises(AuthenticationError):
        use_case.execute("admin", "senha-errada")

    use_case.execute("admin", "senha-correta")

    stored_user = user_repository.get_by_username("admin")
    assert stored_user is not None
    assert stored_user.failed_login_attempts == 0

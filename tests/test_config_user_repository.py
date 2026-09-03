"""Testes do repositório de credenciais baseado em configuração (sem
Turso) — mesmo padrão dos outros apps do usuário: st.secrets["auth"] com
fallback em auth/users.yaml."""

from __future__ import annotations

from pathlib import Path

from study_assistant.infrastructure.security.config_user_repository import ConfigUserRepository


def test_get_by_username_retorna_none_se_sem_hash_configurado(tmp_path: Path) -> None:
    repo = ConfigUserRepository(username="admin", password_hash="", yaml_path=tmp_path / "users.yaml")
    assert repo.get_by_username("admin") is None


def test_get_by_username_retorna_usuario_quando_configurado(tmp_path: Path) -> None:
    repo = ConfigUserRepository(
        username="admin", password_hash="hash-fake", yaml_path=tmp_path / "users.yaml"
    )
    user = repo.get_by_username("admin")
    assert user is not None
    assert user.username == "admin"
    assert user.password_hash == "hash-fake"


def test_get_by_username_retorna_none_para_outro_usuario(tmp_path: Path) -> None:
    repo = ConfigUserRepository(
        username="admin", password_hash="hash-fake", yaml_path=tmp_path / "users.yaml"
    )
    assert repo.get_by_username("outro_usuario") is None


def test_save_grava_arquivo_yaml_local(tmp_path: Path) -> None:
    yaml_path = tmp_path / "auth" / "users.yaml"
    repo = ConfigUserRepository(username="admin", password_hash="", yaml_path=yaml_path)

    from study_assistant.domain.entities import AdminUser

    repo.save(AdminUser(username="admin", password_hash="novo-hash"))

    assert yaml_path.exists()
    content = yaml_path.read_text(encoding="utf-8")
    assert "admin" in content
    assert "novo-hash" in content

    # e o repositório em memória já reflete a nova credencial
    user = repo.get_by_username("admin")
    assert user is not None
    assert user.password_hash == "novo-hash"


def test_lockout_apos_tentativas_e_reset_em_sucesso(tmp_path: Path) -> None:
    repo = ConfigUserRepository(
        username="admin", password_hash="hash-fake", yaml_path=tmp_path / "users.yaml"
    )

    for _ in range(3):
        repo.register_login_attempt("admin", success=False, lock_until_minutes=15, max_attempts=3)

    locked_user = repo.get_by_username("admin")
    assert locked_user is not None
    assert locked_user.is_locked() is True

    repo.register_login_attempt("admin", success=True, lock_until_minutes=15, max_attempts=3)
    unlocked_user = repo.get_by_username("admin")
    assert unlocked_user is not None
    assert unlocked_user.is_locked() is False
    assert unlocked_user.failed_login_attempts == 0

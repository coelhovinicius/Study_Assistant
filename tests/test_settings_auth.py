"""Testes da resolução de credenciais de admin em config/settings.py:
st.secrets["auth"] tem prioridade; auth/users.yaml é o fallback local;
sem nenhum dos dois, o app fica com auth.is_configured == False."""

from __future__ import annotations

from pathlib import Path

import pytest

import study_assistant.config.settings as settings_module
from study_assistant.config.settings import load_settings

_BASE_SECRETS = {"turso": {"database_url": "libsql://x.turso.io", "auth_token": "tok"}}


@pytest.fixture(autouse=True)
def _isolate_auth_yaml_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Evita que os testes leiam/escrevam o auth/users.yaml real do projeto."""
    fake_path = tmp_path / "users.yaml"
    monkeypatch.setattr(settings_module, "AUTH_YAML_PATH", fake_path)
    return fake_path


def test_usa_secrets_quando_disponivel() -> None:
    secrets = {**_BASE_SECRETS, "auth": {"username": "admin", "password_hash": "hash-do-secrets"}}
    settings = load_settings(secrets)
    assert settings.auth.username == "admin"
    assert settings.auth.password_hash == "hash-do-secrets"
    assert settings.auth.is_configured is True


def test_cai_para_yaml_quando_secrets_nao_tem_auth(_isolate_auth_yaml_path: Path) -> None:
    _isolate_auth_yaml_path.write_text(
        'username: admin\npassword_hash: "hash-do-yaml"\n', encoding="utf-8"
    )
    settings = load_settings(_BASE_SECRETS)
    assert settings.auth.username == "admin"
    assert settings.auth.password_hash == "hash-do-yaml"


def test_secrets_tem_prioridade_sobre_yaml(_isolate_auth_yaml_path: Path) -> None:
    _isolate_auth_yaml_path.write_text(
        'username: admin\npassword_hash: "hash-do-yaml"\n', encoding="utf-8"
    )
    secrets = {**_BASE_SECRETS, "auth": {"username": "admin", "password_hash": "hash-do-secrets"}}
    settings = load_settings(secrets)
    assert settings.auth.password_hash == "hash-do-secrets"


def test_sem_secrets_e_sem_yaml_fica_nao_configurado() -> None:
    settings = load_settings(_BASE_SECRETS)
    assert settings.auth.is_configured is False


def test_analise_em_lotes_usa_os_padroes_combinados_sem_secao_no_secrets() -> None:
    analysis = load_settings(_BASE_SECRETS).analysis
    assert analysis.max_total_chars == 120_000
    assert analysis.batch_chars == 12_000
    assert analysis.saved_responses_days == 7


def test_analise_em_lotes_pode_ser_ajustada_pelo_secrets() -> None:
    secrets = {**_BASE_SECRETS, "analysis": {"max_total_chars": 60000, "saved_responses_days": 3}}
    analysis = load_settings(secrets).analysis
    assert analysis.max_total_chars == 60_000
    assert analysis.batch_chars == 12_000
    assert analysis.saved_responses_days == 3

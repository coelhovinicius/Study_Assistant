"""Testes do hashing de senha (bcrypt)."""

from __future__ import annotations

from study_assistant.infrastructure.security.bcrypt_password_hasher import BcryptPasswordHasher


def test_hash_e_diferente_da_senha_original() -> None:
    hasher = BcryptPasswordHasher(rounds=4)  # rounds baixo só para o teste rodar rápido
    password_hash = hasher.hash("minha-senha-secreta")
    assert password_hash != "minha-senha-secreta"
    assert password_hash.startswith("$2b$")


def test_verify_aceita_a_senha_correta() -> None:
    hasher = BcryptPasswordHasher(rounds=4)
    password_hash = hasher.hash("minha-senha-secreta")
    assert hasher.verify("minha-senha-secreta", password_hash) is True


def test_verify_rejeita_senha_errada() -> None:
    hasher = BcryptPasswordHasher(rounds=4)
    password_hash = hasher.hash("minha-senha-secreta")
    assert hasher.verify("senha-errada", password_hash) is False


def test_verify_nao_quebra_com_hash_malformado() -> None:
    hasher = BcryptPasswordHasher(rounds=4)
    assert hasher.verify("qualquer-senha", "isso-nao-e-um-hash-valido") is False


def test_dois_hashes_da_mesma_senha_sao_diferentes() -> None:
    # bcrypt usa salt aleatório por chamada — dois hashes da mesma senha
    # nunca devem ser idênticos, mas ambos devem validar a mesma senha.
    hasher = BcryptPasswordHasher(rounds=4)
    hash_1 = hasher.hash("mesma-senha")
    hash_2 = hasher.hash("mesma-senha")
    assert hash_1 != hash_2
    assert hasher.verify("mesma-senha", hash_1) is True
    assert hasher.verify("mesma-senha", hash_2) is True

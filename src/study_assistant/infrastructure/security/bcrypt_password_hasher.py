"""Hashing de senha com bcrypt.

bcrypt já embute um salt aleatório por senha e é propositalmente lento
(fator de custo configurável), o que o torna adequado contra ataques de
força bruta — nunca armazenamos a senha em texto puro, nem usamos hashes
rápidos como MD5/SHA-256 puro para isso.
"""

from __future__ import annotations

from study_assistant.domain.ports import PasswordHasher


class BcryptPasswordHasher(PasswordHasher):
    def __init__(self, rounds: int = 12) -> None:
        # 12 é um bom equilíbrio custo/segurança em 2026 para uso pessoal;
        # aumente se quiser mais margem de segurança (dobra o custo por unidade).
        self._rounds = rounds

    def hash(self, plain_password: str) -> str:
        import bcrypt

        salt = bcrypt.gensalt(rounds=self._rounds)
        return bcrypt.hashpw(plain_password.encode("utf-8"), salt).decode("utf-8")

    def verify(self, plain_password: str, password_hash: str) -> bool:
        import bcrypt

        try:
            return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))
        except ValueError:
            # hash malformado/corrompido — trata como senha inválida, não crasha o app
            return False

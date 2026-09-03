#!/usr/bin/env python3
"""Cria ou redefine a senha do usuário administrador único do app.

Mesmo padrão dos outros apps do usuário: NÃO grava no Turso. Este script
gera o hash bcrypt da senha e:
  1. grava em auth/users.yaml (fallback local, fora do Git) — é o que o
     app usa automaticamente se você não tiver configurado Secrets; e
  2. imprime um bloco pronto para colar em .streamlit/secrets.toml
     (ou nos Secrets do Streamlit Cloud), caso prefira essa via — que tem
     prioridade sobre o auth/users.yaml quando presente.

Uso:
    python scripts/create_admin_user.py [--username admin] [--secrets .streamlit/secrets.toml]

A senha é lida de forma oculta (getpass) — nunca passe a senha como
argumento de linha de comando, pois ficaria salva no histórico do shell.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from _common import PROJECT_ROOT, add_src_to_path, load_toml_secrets

add_src_to_path()

from study_assistant.infrastructure.security.bcrypt_password_hasher import (  # noqa: E402
    BcryptPasswordHasher,
)

_MIN_PASSWORD_LENGTH = 8
_DEFAULT_USERNAME = "admin"
_YAML_PATH = PROJECT_ROOT / "auth" / "users.yaml"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", default=None, help=f"Padrão: {_DEFAULT_USERNAME!r}")
    parser.add_argument(
        "--secrets",
        default=".streamlit/secrets.toml",
        help="Usado só para ler [security].bcrypt_rounds, se existir; opcional.",
    )
    args = parser.parse_args()

    username = args.username or _DEFAULT_USERNAME

    bcrypt_rounds = 12
    try:
        secrets = load_toml_secrets(args.secrets)
        bcrypt_rounds = int(secrets.get("security", {}).get("bcrypt_rounds", 12))
    except SystemExit:
        pass  # secrets.toml ainda não existe — segue com o padrão (12)

    password = getpass.getpass(f"Nova senha para '{username}': ")
    confirm = getpass.getpass("Confirme a senha: ")

    if password != confirm:
        print("Erro: as senhas não coincidem.", file=sys.stderr)
        raise SystemExit(1)
    if len(password) < _MIN_PASSWORD_LENGTH:
        print(f"Erro: use uma senha com pelo menos {_MIN_PASSWORD_LENGTH} caracteres.", file=sys.stderr)
        raise SystemExit(1)

    password_hash = BcryptPasswordHasher(rounds=bcrypt_rounds).hash(password)

    import yaml

    _YAML_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_YAML_PATH, "w", encoding="utf-8") as file:
        yaml.safe_dump({"username": username, "password_hash": password_hash}, file, allow_unicode=True)

    print(f"\nCredenciais gravadas em: {_YAML_PATH.relative_to(PROJECT_ROOT)}")
    print(
        "\nSe preferir usar Streamlit Secrets em vez do arquivo local "
        "(recomendado em produção — tem prioridade sobre o yaml), cole isto em "
        ".streamlit/secrets.toml:\n"
    )
    print("[auth]")
    print(f'username = "{username}"')
    print(f'password_hash = "{password_hash}"')


if __name__ == "__main__":
    main()

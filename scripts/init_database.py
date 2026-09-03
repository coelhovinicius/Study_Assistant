#!/usr/bin/env python3
"""Cria (ou verifica) as tabelas do Study Assistant no banco Turso.

Uso:
    python scripts/init_database.py [--secrets .streamlit/secrets.toml]

Seguro para rodar mais de uma vez: todas as instruções usam
"CREATE TABLE IF NOT EXISTS" / "CREATE INDEX IF NOT EXISTS", e as migrações
de coluna nova (ver ``_MIGRATIONS`` abaixo) ignoram o erro de "coluna já
existe" quando rodadas de novo num banco que já tinha sido migrado.
"""

from __future__ import annotations

import argparse

from _common import PROJECT_ROOT, add_src_to_path, load_toml_secrets

add_src_to_path()

from study_assistant.domain.exceptions import RepositoryError  # noqa: E402
from study_assistant.config.settings import load_settings  # noqa: E402
from study_assistant.infrastructure.persistence.turso_client import TursoHttpClient  # noqa: E402

_SCHEMA_PATH = (
    PROJECT_ROOT / "src" / "study_assistant" / "infrastructure" / "persistence" / "schema.sql"
)

# Migrações de coluna nova em tabela já existente: "CREATE TABLE IF NOT
# EXISTS" (no schema.sql) só cria a coluna em bancos NOVOS — um banco que já
# tinha sa_study_sessions criada antes da mudança pra guardar o PDF no
# histórico precisa deste ALTER TABLE pra ganhar as colunas pdf_bytes/
# pdf_filename. Cada instrução é tentada; se o Turso responder "coluna já
# existe" (rodar o script de novo, banco já migrado antes), o erro é
# ignorado — é o que mantém "seguro rodar mais de uma vez".
_MIGRATIONS: tuple[str, ...] = (
    "ALTER TABLE sa_study_sessions ADD COLUMN pdf_bytes BLOB",
    "ALTER TABLE sa_study_sessions ADD COLUMN pdf_filename TEXT",
)


def _run_migrations(client: TursoHttpClient) -> None:
    for statement in _MIGRATIONS:
        try:
            client.execute(statement)
        except RepositoryError as exc:
            if "duplicate column" in str(exc).lower():
                print(f"OK (coluna já existia): {statement}")
                continue
            raise
        else:
            print(f"OK: {statement}")


def _split_statements(sql_text: str) -> list[str]:
    # Remove as linhas de comentário ANTES de separar por ";" — se um
    # comentário vier colado na frente de um comando (ex: o cabeçalho do
    # arquivo seguido direto do primeiro CREATE TABLE, sem linha em branco
    # entre eles), os dois caem no mesmo pedaço ao dividir por ";", e um
    # filtro que olha só o início do pedaço ("começa com --? então é só
    # comentário") descartaria o comando de verdade junto com o comentário.
    lines = [line for line in sql_text.splitlines() if not line.strip().startswith("--")]
    cleaned_sql = "\n".join(lines)

    statements = []
    for raw_statement in cleaned_sql.split(";"):
        statement = raw_statement.strip()
        if statement:
            statements.append(statement)
    return statements


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--secrets", default=".streamlit/secrets.toml")
    args = parser.parse_args()

    secrets = load_toml_secrets(args.secrets)
    settings = load_settings(secrets)
    client = TursoHttpClient(settings.turso.database_url, settings.turso.auth_token)

    sql_text = _SCHEMA_PATH.read_text(encoding="utf-8")
    for statement in _split_statements(sql_text):
        client.execute(statement)
        first_line = statement.splitlines()[0][:70]
        print(f"OK: {first_line}...")

    _run_migrations(client)

    print("\nSchema do Study Assistant criado/verificado com sucesso no Turso.")


if __name__ == "__main__":
    main()

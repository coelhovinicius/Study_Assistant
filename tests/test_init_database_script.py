"""Teste de regressão para scripts/init_database.py: o schema.sql começa
com um bloco de comentário colado direto no primeiro CREATE TABLE (sem
linha em branco entre os dois), e uma versão anterior de
`_split_statements` descartava esse primeiro comando inteiro junto com o
comentário — a tabela `sa_study_sessions` nunca era criada, e o índice
que depende dela quebrava com "no such table". Este teste garante que
isso não volta a acontecer."""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from init_database import _SCHEMA_PATH, _split_statements  # noqa: E402


def test_extrai_todos_os_create_table_do_schema_real() -> None:
    sql_text = _SCHEMA_PATH.read_text(encoding="utf-8")
    statements = _split_statements(sql_text)

    create_tables = [s for s in statements if s.upper().startswith("CREATE TABLE")]
    assert len(create_tables) == 4
    assert any("sa_study_sessions" in s for s in create_tables)
    assert any("sa_materials" in s for s in create_tables)
    assert any("sa_provider_attempts" in s for s in create_tables)
    assert any("sa_ai_respostas" in s for s in create_tables)


def test_nao_perde_comando_colado_direto_apos_comentario_de_cabecalho() -> None:
    """Caso mínimo que reproduz o bug: comentário de cabeçalho SEM linha em
    branco antes do primeiro comando — os dois caem no mesmo pedaço ao
    dividir por ';'."""
    sql_text = "-- comentário de cabeçalho\n-- linha 2\nCREATE TABLE IF NOT EXISTS x (id TEXT);"

    statements = _split_statements(sql_text)

    assert len(statements) == 1
    assert statements[0].startswith("CREATE TABLE IF NOT EXISTS x")


def test_ignora_linhas_de_comentario_no_meio_do_arquivo() -> None:
    sql_text = (
        "CREATE TABLE a (id TEXT);\n"
        "-- comentário solto no meio\n"
        "CREATE TABLE b (id TEXT);\n"
    )

    statements = _split_statements(sql_text)

    assert len(statements) == 2
    assert statements[0].startswith("CREATE TABLE a")
    assert statements[1].startswith("CREATE TABLE b")


def test_ignora_pedacos_vazios() -> None:
    sql_text = "CREATE TABLE a (id TEXT);\n\n\n-- só comentário, sem comando;\n"

    statements = _split_statements(sql_text)

    assert len(statements) == 1

"""Testes de application/text_batches.py — divisão do material em lotes
que cabem numa chamada de IA, sempre cortando numa fronteira natural."""

from __future__ import annotations

from study_assistant.application.text_batches import split_into_batches


def test_texto_pequeno_vira_um_lote_so() -> None:
    assert split_into_batches("uma página só", 100) == ["uma página só"]


def test_texto_vazio_nao_gera_lote() -> None:
    assert split_into_batches("   \n\n ", 100) == []


def test_corta_entre_paginas_sem_passar_do_limite() -> None:
    pages = [f"Página {i}: " + ("conteúdo " * 30).strip() for i in range(10)]
    text = "\n\n".join(pages)

    batches = split_into_batches(text, 1000)

    assert len(batches) > 1
    assert all(len(batch) <= 1000 for batch in batches)
    # nenhuma página é partida ao meio, e nada se perde nem muda de ordem
    assert "\n\n".join(batches) == text


def test_paragrafo_gigante_e_cortado_por_linha_e_depois_por_palavra() -> None:
    long_line = " ".join(f"palavra{i}" for i in range(400))
    text = "linha curta\n" + long_line

    batches = split_into_batches(text, 300)

    assert all(len(batch) <= 300 for batch in batches)
    words = " ".join(batches).split()
    assert words == text.split()  # nenhuma palavra cortada ou perdida

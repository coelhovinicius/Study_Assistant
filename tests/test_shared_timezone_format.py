"""Testes de shared/timezone_format.py.

O app guarda tudo em UTC (Turso não tem tipo de data nativo), mas o
usuário está no Brasil (Brasília, UTC-3) — mostrar horário UTC pra ele é
confuso, então tudo que é exibido na tela/relatório passa por aqui."""

from __future__ import annotations

from datetime import datetime, timezone

from study_assistant.shared.timezone_format import format_brasilia


def test_converte_utc_para_horario_de_brasilia() -> None:
    # 14:30 UTC == 11:30 em Brasília (UTC-3, sem horário de verão hoje em dia)
    value = datetime(2026, 8, 31, 14, 30, tzinfo=timezone.utc)
    assert format_brasilia(value) == "31/08/2026 11:30"


def test_trata_datetime_naive_como_utc() -> None:
    """Datetime sem tzinfo é tratado como UTC — mesma convenção usada em
    infrastructure/persistence/datetime_utils.py, pra não haver duas
    interpretações diferentes de "hora sem fuso" dentro do mesmo app."""
    naive = datetime(2026, 8, 31, 14, 30)
    aware = datetime(2026, 8, 31, 14, 30, tzinfo=timezone.utc)
    assert format_brasilia(naive) == format_brasilia(aware)


def test_atravessa_a_virada_do_dia() -> None:
    # 01:00 UTC de um dia vira 22:00 do dia ANTERIOR em Brasília.
    value = datetime(2026, 9, 2, 1, 0, tzinfo=timezone.utc)
    assert format_brasilia(value) == "01/09/2026 22:00"


def test_aceita_formato_customizado() -> None:
    value = datetime(2026, 8, 31, 14, 30, tzinfo=timezone.utc)
    assert format_brasilia(value, fmt="%H:%M") == "11:30"

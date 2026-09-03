"""Exibição de datas/horas no fuso do usuário (Brasília, UTC-3).

Tudo é armazenado em UTC (Turso/SQLite não tem tipo de data nativo — ver
``infrastructure/persistence/datetime_utils.py``), o que é a escolha certa
para persistência, mas mostrar "UTC" pra um usuário no Brasil é confuso.
Este módulo fica fora de domain/application/infrastructure/presentation de
propósito: tanto os geradores de relatório (infra) quanto as páginas do
Streamlit (presentation) precisam formatar datas, e nenhuma das duas deveria
depender da outra só por causa disso.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# zoneinfo depende do banco de fusos IANA instalado no sistema. No Linux/macOS
# geralmente já vem pronto; no Windows não vem — por isso 'tzdata' está no
# requirements.txt (senão isso levantaria ZoneInfoNotFoundError no PC do
# usuário mesmo com o código certo).
BRASILIA_TZ = ZoneInfo("America/Sao_Paulo")

_DEFAULT_FORMAT = "%d/%m/%Y %H:%M"


def format_brasilia(value: datetime, *, fmt: str = _DEFAULT_FORMAT) -> str:
    """Formata ``value`` no horário de Brasília — só a data/hora, sem
    escrever "(horário de Brasília)" no texto (ninguém precisa disso
    soletrado toda vez que vê uma data no relatório).

    Se ``value`` vier sem timezone (naive), assume UTC — mesma convenção já
    usada em ``infrastructure/persistence/datetime_utils.py``.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    local = value.astimezone(BRASILIA_TZ)
    return local.strftime(fmt)

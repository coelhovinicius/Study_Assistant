"""Utilitários de conversão de datas usadas pelos repositórios Turso.

O Turso/SQLite não tem um tipo nativo de data — datas são guardadas como
texto ISO-8601 (UTC). Estas funções centralizam a conversão para evitar
que cada repositório reimplemente (e possivelmente erre) o parsing.
"""

from __future__ import annotations

from datetime import datetime, timezone


def to_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def from_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed

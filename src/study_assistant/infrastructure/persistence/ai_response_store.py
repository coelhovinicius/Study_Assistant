"""Respostas de IA já recebidas, guardadas no Turso (tabela ``sa_ai_respostas``).

Existe pra análise em lotes não perder nada: cada lote respondido é
gravado na hora, então se a análise pausar (IA fora do ar, cota esgotada),
o navegador fechar ou o servidor reiniciar, continuar depois só manda pra
IA o que ainda falta — ver ``application/ai_caller.py``.

Não guarda o texto dos materiais do usuário, só a resposta da IA,
identificada por uma "impressão digital" (hash) do pedido. E é
temporário: ``purge_older_than`` apaga o que passou de alguns dias — o
histórico de verdade continua sendo só o PDF salvo em ``sa_study_sessions``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from study_assistant.domain.entities import SavedAIResponse
from study_assistant.domain.ports import AIResponseStore
from study_assistant.infrastructure.persistence.datetime_utils import to_iso
from study_assistant.infrastructure.persistence.turso_client import TursoHttpClient

# As mesmas instruções do schema.sql. Repetidas aqui porque a tabela é
# criada sozinha no primeiro uso: sem isso, quem atualizasse o app sem rodar
# scripts/init_database.py de novo ficaria sem onde salvar o progresso.
_CREATE_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS sa_ai_respostas (
        cache_key TEXT PRIMARY KEY,
        response TEXT NOT NULL,
        provider_name TEXT,
        model TEXT,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_sa_ai_respostas_created_at ON sa_ai_respostas(created_at)",
)


class TursoAIResponseStore(AIResponseStore):
    def __init__(self, client: TursoHttpClient) -> None:
        self._client = client
        self._table_ready = False

    def _ensure_table(self) -> None:
        if not self._table_ready:
            self._client.execute_batch([(statement, None) for statement in _CREATE_STATEMENTS])
            self._table_ready = True

    def get(self, key: str) -> SavedAIResponse | None:
        self._ensure_table()
        row = self._client.execute(
            "SELECT response, provider_name, model FROM sa_ai_respostas WHERE cache_key = ?",
            [key],
        ).first()
        if row is None:
            return None
        return SavedAIResponse(
            text=row["response"],
            provider_name=row.get("provider_name") or "",
            model=row.get("model") or "",
        )

    def save(self, key: str, response: SavedAIResponse) -> None:
        self._ensure_table()
        self._client.execute(
            """
            INSERT INTO sa_ai_respostas (cache_key, response, provider_name, model, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                response = excluded.response,
                provider_name = excluded.provider_name,
                model = excluded.model,
                created_at = excluded.created_at
            """,
            [key, response.text, response.provider_name, response.model, to_iso(datetime.now(timezone.utc))],
        )

    def purge_older_than(self, days: int) -> None:
        self._ensure_table()
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        self._client.execute("DELETE FROM sa_ai_respostas WHERE created_at < ?", [to_iso(cutoff)])

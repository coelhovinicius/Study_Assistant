"""Testes de infrastructure/persistence/ai_response_store.py — com um
cliente Turso falso que só registra o SQL (sem rede, sem banco)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from study_assistant.domain.entities import SavedAIResponse
from study_assistant.infrastructure.persistence.ai_response_store import TursoAIResponseStore
from study_assistant.infrastructure.persistence.turso_client import TursoQueryResult


@dataclass
class _RecordingTursoClient:
    calls: list[tuple[str, tuple[Any, ...]]] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)

    def execute(self, sql: str, params=None) -> TursoQueryResult:
        self.calls.append((" ".join(sql.split()), tuple(params or [])))
        if sql.strip().startswith("SELECT"):
            return TursoQueryResult(columns=[], rows=self.rows)
        return TursoQueryResult(columns=[], rows=[])

    def execute_batch(self, statements) -> list[TursoQueryResult]:
        return [self.execute(sql, params) for sql, params in statements]


def test_cria_a_tabela_sozinho_uma_vez_so() -> None:
    """Quem atualizar o app sem rodar scripts/init_database.py de novo não
    pode ficar sem onde salvar o progresso da análise."""
    client = _RecordingTursoClient()
    store = TursoAIResponseStore(client)

    store.get("a")
    store.get("b")

    creates = [sql for sql, _ in client.calls if sql.startswith("CREATE TABLE")]
    assert len(creates) == 1
    assert "sa_ai_respostas" in creates[0]


def test_save_grava_a_resposta_e_quem_respondeu() -> None:
    client = _RecordingTursoClient()
    store = TursoAIResponseStore(client)

    store.save("chave", SavedAIResponse(text='{"a": 1}', provider_name="n8n", model="cascata"))

    sql, params = client.calls[-1]
    assert sql.startswith("INSERT INTO sa_ai_respostas")
    assert "ON CONFLICT(cache_key) DO UPDATE" in sql
    assert params[:4] == ("chave", '{"a": 1}', "n8n", "cascata")


def test_get_devolve_a_resposta_salva() -> None:
    client = _RecordingTursoClient(rows=[{"response": '{"a": 1}', "provider_name": "n8n", "model": "cascata"}])

    saved = TursoAIResponseStore(client).get("chave")

    assert saved == SavedAIResponse(text='{"a": 1}', provider_name="n8n", model="cascata")
    assert client.calls[-1][1] == ("chave",)


def test_get_sem_resposta_salva_devolve_none() -> None:
    assert TursoAIResponseStore(_RecordingTursoClient()).get("chave") is None


def test_purge_apaga_so_o_que_passou_do_prazo() -> None:
    client = _RecordingTursoClient()

    TursoAIResponseStore(client).purge_older_than(7)

    sql, params = client.calls[-1]
    assert sql == "DELETE FROM sa_ai_respostas WHERE created_at < ?"
    cutoff = datetime.fromisoformat(params[0])
    expected = datetime.now(timezone.utc) - timedelta(days=7)
    assert abs((cutoff - expected).total_seconds()) < 60

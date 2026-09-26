"""Testes de infrastructure/persistence/session_repository.py — usa um
cliente Turso falso (grava as instruções SQL recebidas, sem rede/banco de
verdade), no mesmo espírito dos outros testes do projeto.

Regressão principal (mudança pedida pelo usuário: "quero que, somente,
guarde o PDF"): save() não persiste mais o texto bruto dos materiais nem a
análise estruturada — só id/título/data e o PDF já pronto (gerado por
HistoryService antes de chamar o repositório). sa_materials e
sa_provider_attempts não recebem mais nenhuma linha nova; elas continuam
existindo só pra conseguir ler sessões salvas ANTES dessa mudança (get()
tem os dois caminhos: PDF armazenado -> devolve direto; sem PDF armazenado
(legado) -> reconstrói de materiais + análise, como sempre funcionou).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from study_assistant.domain.entities import (
    AnalysisResult,
    Material,
    MaterialType,
    ProviderAttempt,
    SourceFormat,
    StudySession,
)
from study_assistant.infrastructure.persistence.session_repository import TursoSessionRepository
from study_assistant.infrastructure.persistence.turso_client import TursoQueryResult


@dataclass
class _RecordingTursoClient:
    """Registra cada instrução SQL executada, sem falar com nenhum banco de
    verdade. Devolve um resultado vazio pra qualquer SELECT.

    ``execute_batch`` (usado por get()/delete(), que continuam precisando
    de mais de uma instrução por chamada) registra cada instrução em
    ``calls`` no mesmo formato que ``execute`` sempre registrou.
    ``batch_call_count`` conta só as chamadas de ``execute_batch`` — save()
    hoje usa ``execute`` direto (é uma instrução só), então não mexe nesse
    contador. ``canned_results`` deixa programar uma resposta pra um SELECT
    específico (casado pelo prefixo do SQL normalizado) — usado pelos
    testes de get(), que precisam de uma linha de sessão de verdade pra
    montar o StudySession de volta."""

    calls: list[tuple[str, tuple[Any, ...]]] = field(default_factory=list)
    batch_call_count: int = 0
    canned_results: dict[str, TursoQueryResult] = field(default_factory=dict)

    def execute(self, sql: str, params=None) -> TursoQueryResult:
        normalized = " ".join(sql.split())
        self.calls.append((normalized, tuple(params or [])))
        for prefix, result in self.canned_results.items():
            if normalized.startswith(prefix):
                return result
        return TursoQueryResult(columns=[], rows=[])

    def execute_batch(self, statements) -> list[TursoQueryResult]:
        self.batch_call_count += 1
        return [self.execute(sql, params) for sql, params in statements]


def _sample_session() -> StudySession:
    """Sessão com materiais e análise — só pra ter algo realista pra passar
    pra save(); note que save() não olha mais pra ``materials`` nem
    ``analysis_result`` (só usa id/title/created_at), então esses campos
    não aparecem nas asserções dos testes de save()."""
    material = Material(
        filename="apostila.pdf",
        material_type=MaterialType.APOSTILA,
        source_format=SourceFormat.PDF,
        raw_text="conteúdo de exemplo",
    )
    analysis = AnalysisResult(
        sections={"analise_apostila": "texto qualquer"},
        generated_by_provider="OpenAI",
        generated_by_model="gpt-5.5",
        provider_attempts=(
            ProviderAttempt("OpenAI", "gpt-5.5", success=True, duration_ms=100.0),
            ProviderAttempt("Gemini", "gemini-2.5-flash", success=False, duration_ms=50.0, error_message="timeout"),
        ),
    )
    return StudySession(
        title="Sessão de teste",
        materials=[material],
        apostila_insights=None,
        analysis_result=analysis,
    )


def test_save_grava_so_id_titulo_data_e_pdf_numa_unica_instrucao() -> None:
    client = _RecordingTursoClient()
    repo = TursoSessionRepository(client)
    session = _sample_session()

    repo.save(session, pdf_bytes=b"%PDF-conteudo-fake", pdf_filename="sessao_de_teste.pdf")

    assert len(client.calls) == 1  # UMA instrução só — nada de materiais/tentativas
    sql, params = client.calls[0]
    assert sql.startswith("INSERT INTO sa_study_sessions")
    assert params == (
        session.id,
        session.title,
        session.created_at.isoformat(),
        b"%PDF-conteudo-fake",
        "sessao_de_teste.pdf",
    )


def test_save_nao_grava_nada_em_materiais_nem_em_tentativas() -> None:
    """Regressão central do pedido "guarde somente o PDF": mesmo com uma
    sessão que TEM materiais e tentativas de provider, save() não deve
    tocar em sa_materials nem em sa_provider_attempts — essas tabelas só
    continuam existindo pra ler sessões salvas antes dessa mudança."""
    client = _RecordingTursoClient()
    repo = TursoSessionRepository(client)
    session = _sample_session()  # tem 1 material e 2 tentativas de provider

    repo.save(session, pdf_bytes=b"%PDF-conteudo-fake", pdf_filename="sessao.pdf")

    assert not any("sa_materials" in sql for sql, _ in client.calls)
    assert not any("sa_provider_attempts" in sql for sql, _ in client.calls)


def test_save_duas_vezes_atualiza_em_vez_de_duplicar() -> None:
    client = _RecordingTursoClient()
    repo = TursoSessionRepository(client)
    session = _sample_session()

    repo.save(session, pdf_bytes=b"versao-1", pdf_filename="s.pdf")
    repo.save(session, pdf_bytes=b"versao-2", pdf_filename="s.pdf")

    assert len(client.calls) == 2
    assert "ON CONFLICT(id) DO UPDATE" in client.calls[0][0]
    assert client.calls[1][1][3] == b"versao-2"  # pdf_bytes da segunda chamada


def test_rename_atualiza_titulo_e_nome_do_pdf_numa_unica_instrucao() -> None:
    client = _RecordingTursoClient()
    repo = TursoSessionRepository(client)

    repo.rename("sessao-123", title="Título novo", pdf_filename="titulo_novo.pdf")

    assert client.calls == [
        (
            "UPDATE sa_study_sessions SET title = ?, pdf_filename = ? WHERE id = ?",
            ("Título novo", "titulo_novo.pdf", "sessao-123"),
        )
    ]


def test_delete_remove_tentativas_junto_com_sessao_e_materiais() -> None:
    client = _RecordingTursoClient()
    repo = TursoSessionRepository(client)

    repo.delete("sessao-123")

    tables_deleted = [sql for sql, params in client.calls if sql.startswith("DELETE") and params == ("sessao-123",)]
    assert any("sa_provider_attempts" in sql for sql in tables_deleted)
    assert any("sa_materials" in sql for sql in tables_deleted)
    assert any("sa_study_sessions" in sql for sql in tables_deleted)


def test_delete_manda_tudo_num_unico_execute_batch() -> None:
    client = _RecordingTursoClient()
    repo = TursoSessionRepository(client)

    repo.delete("sessao-123")

    assert client.batch_call_count == 1
    assert len(client.calls) == 3


def test_get_de_sessao_salva_so_com_pdf_devolve_o_pdf_sem_reconstruir_nada() -> None:
    """Sessão salva DEPOIS da mudança pra guardar só o PDF: get() devolve
    stored_pdf_bytes/stored_pdf_filename direto da linha, sem tentar montar
    materiais ou análise (que nem foram salvos pra essa sessão)."""
    session_row = {
        "id": "s1",
        "title": "Sessão salva só com PDF",
        "created_at": "2026-08-31T00:00:00+00:00",
        "apostila_insights_json": None,
        "analysis_sections_json": None,
        "generated_by_provider": None,
        "generated_by_model": None,
        "pdf_bytes": b"%PDF-conteudo-fake",
        "pdf_filename": "sessao_salva_so_com_pdf.pdf",
    }
    client = _RecordingTursoClient(
        canned_results={
            "SELECT * FROM sa_study_sessions WHERE id = ?": TursoQueryResult(
                columns=list(session_row), rows=[session_row]
            ),
        }
    )
    repo = TursoSessionRepository(client)

    session = repo.get("s1")

    assert session is not None
    assert session.stored_pdf_bytes == b"%PDF-conteudo-fake"
    assert session.stored_pdf_filename == "sessao_salva_so_com_pdf.pdf"
    assert session.materials == []
    assert session.analysis_result is None


def test_get_de_sessao_salva_so_com_pdf_sem_filename_usa_titulo_como_fallback() -> None:
    """pdf_filename é preenchido por HistoryService.save() sempre que salva
    de verdade — mas se por algum motivo a coluna vier vazia (ex: linha
    editada manualmente no banco), get() não pode devolver um nome de
    arquivo None (quebraria o download_button do histórico)."""
    session_row = {
        "id": "s1",
        "title": "Minha Sessão",
        "created_at": "2026-08-31T00:00:00+00:00",
        "pdf_bytes": b"%PDF-conteudo-fake",
        "pdf_filename": None,
    }
    client = _RecordingTursoClient(
        canned_results={
            "SELECT * FROM sa_study_sessions WHERE id = ?": TursoQueryResult(
                columns=list(session_row), rows=[session_row]
            ),
        }
    )
    repo = TursoSessionRepository(client)

    session = repo.get("s1")

    assert session is not None
    assert session.stored_pdf_filename == "Minha Sessão.pdf"


def test_get_de_sessao_legada_sem_pdf_reconstroi_a_partir_de_materiais_e_analise() -> None:
    """Sessão salva ANTES da mudança (sem pdf_bytes): get() continua
    reconstruindo do jeito antigo — é o que preserva o histórico já salvo
    do usuário sem exigir nenhuma migração de dados."""
    session_row = {
        "id": "legado-1",
        "title": "Sessão antiga",
        "created_at": "2026-08-20T00:00:00+00:00",
        "apostila_insights_json": None,
        "analysis_sections_json": None,
        "generated_by_provider": None,
        "generated_by_model": None,
        # sem pdf_bytes/pdf_filename — nem existiam quando essa linha foi salva.
    }
    client = _RecordingTursoClient(
        canned_results={
            "SELECT * FROM sa_study_sessions WHERE id = ?": TursoQueryResult(
                columns=list(session_row), rows=[session_row]
            ),
        }
    )
    repo = TursoSessionRepository(client)

    session = repo.get("legado-1")

    assert session is not None
    assert session.stored_pdf_bytes is None
    assert session.materials == []  # nenhum material canned pra essa sessão, mas o caminho é o de reconstrução
    assert session.analysis_result is None


def test_get_manda_as_3_consultas_num_unico_execute_batch() -> None:
    """Independente de qual dos dois caminhos (PDF pronto ou legado) a
    sessão cair depois, as 3 consultas (sessão, materiais, tentativas) já
    saem juntas num único request — só depois é que dá pra saber qual
    caminho seguir."""
    client = _RecordingTursoClient()
    repo = TursoSessionRepository(client)

    repo.get("qualquer-id")

    assert client.batch_call_count == 1
    assert len(client.calls) == 3


def test_get_de_sessao_inexistente_tambem_manda_um_unico_batch_e_retorna_none() -> None:
    client = _RecordingTursoClient()
    repo = TursoSessionRepository(client)

    assert repo.get("nao-existe") is None
    assert client.batch_call_count == 1
    assert len(client.calls) == 3

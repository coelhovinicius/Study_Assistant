"""Testes de application/history_service.py.

Foco no pedido do usuário "quero que, somente, guarde o PDF": save()
precisa gerar o PDF (via GenerateReportUseCase, o mesmo caso de uso que já
gera os downloads da tela de análise) ANTES de chamar o repositório, e
passar exatamente esse conteúdo pra ele — o repositório em si não sabe
nada sobre gerar relatório (ver session_repository.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from study_assistant.application.history_service import HistoryService
from study_assistant.application.report_service import GenerateReportUseCase
from study_assistant.domain.entities import StudySession
from study_assistant.domain.exceptions import ReportGenerationError
from study_assistant.domain.ports import ReportGenerator


class _FakePdfGenerator(ReportGenerator):
    def __init__(self, content: bytes = b"%PDF-fake") -> None:
        self._content = content

    @property
    def format_name(self) -> str:
        return "pdf"

    @property
    def mime_type(self) -> str:
        return "application/pdf"

    def generate(self, session: StudySession) -> bytes:
        return self._content


class _BrokenPdfGenerator(ReportGenerator):
    """Simula reportlab ausente/quebrado — mesmo tipo de falha que
    PdfReportGenerator.generate() levanta nesse caso."""

    @property
    def format_name(self) -> str:
        return "pdf"

    @property
    def mime_type(self) -> str:
        return "application/pdf"

    def generate(self, session: StudySession) -> bytes:
        raise ReportGenerationError("Dependência 'reportlab' não instalada.")


@dataclass
class _RecordingRepository:
    """Dublê do SessionRepository — só grava o que save() recebeu, sem
    banco nenhum por trás."""

    saved_calls: list[dict[str, Any]] = field(default_factory=list)
    renamed_calls: list[dict[str, Any]] = field(default_factory=list)

    def save(self, session, *, pdf_bytes, pdf_filename) -> None:
        self.saved_calls.append({"session": session, "pdf_bytes": pdf_bytes, "pdf_filename": pdf_filename})

    def list_summaries(self, limit: int = 50) -> list[dict]:
        return []

    def get(self, session_id: str):
        return None

    def rename(self, session_id: str, *, title: str, pdf_filename: str) -> None:
        self.renamed_calls.append({"session_id": session_id, "title": title, "pdf_filename": pdf_filename})

    def delete(self, session_id: str) -> None:
        pass


def _session() -> StudySession:
    return StudySession(title="Minha sessão", materials=[])


def test_save_gera_o_pdf_e_manda_exatamente_isso_pro_repositorio() -> None:
    repo = _RecordingRepository()
    service = HistoryService(repo, GenerateReportUseCase([_FakePdfGenerator(b"%PDF-conteudo")]))
    session = _session()

    service.save(session)

    assert len(repo.saved_calls) == 1
    call = repo.saved_calls[0]
    assert call["session"] is session
    assert call["pdf_bytes"] == b"%PDF-conteudo"
    assert call["pdf_filename"].endswith(".pdf")


def test_save_marca_a_sessao_como_salva_depois_de_persistir() -> None:
    repo = _RecordingRepository()
    service = HistoryService(repo, GenerateReportUseCase([_FakePdfGenerator()]))
    session = _session()
    assert session.saved is False

    result = service.save(session)

    assert session.saved is True
    assert result is session


def test_save_propaga_erro_de_geracao_do_pdf_sem_chamar_o_repositorio() -> None:
    """Se o PDF não puder ser gerado, save() não deve persistir nada
    parcial nem meio-salvo — nem chegar a chamar o repositório."""
    repo = _RecordingRepository()
    service = HistoryService(repo, GenerateReportUseCase([_BrokenPdfGenerator()]))
    session = _session()

    with pytest.raises(ReportGenerationError):
        service.save(session)

    assert repo.saved_calls == []
    assert session.saved is False


def test_rename_tira_espacos_e_atualiza_o_nome_do_pdf_junto() -> None:
    repo = _RecordingRepository()
    service = HistoryService(repo, GenerateReportUseCase([_FakePdfGenerator()]))

    result = service.rename("abc123", "  Cálculo I — Unidade 2  ")

    assert result == "Cálculo I — Unidade 2"
    assert repo.renamed_calls == [
        {"session_id": "abc123", "title": "Cálculo I — Unidade 2", "pdf_filename": "calculo_i_unidade_2.pdf"}
    ]


def test_rename_com_titulo_vazio_nao_chama_o_repositorio() -> None:
    repo = _RecordingRepository()
    service = HistoryService(repo, GenerateReportUseCase([_FakePdfGenerator()]))

    with pytest.raises(ValueError):
        service.rename("abc123", "   ")

    assert repo.renamed_calls == []

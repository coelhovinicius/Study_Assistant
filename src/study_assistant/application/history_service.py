"""Caso de uso: histórico de sessões salvas ("salvar ou não os resultados").

Só é chamado quando o usuário explicitamente decide salvar; o app funciona
inteiramente sem isso, sessão a sessão, se o usuário preferir não guardar
nada.
"""

from __future__ import annotations

from study_assistant.application.report_service import GenerateReportUseCase
from study_assistant.domain.entities import StudySession
from study_assistant.domain.ports import SessionRepository


class HistoryService:
    def __init__(
        self, session_repository: SessionRepository, report_use_case: GenerateReportUseCase
    ) -> None:
        self._session_repository = session_repository
        self._report_use_case = report_use_case

    def save(self, session: StudySession) -> StudySession:
        # Pedido do usuário: o histórico guarda SOMENTE o PDF — nada de
        # texto bruto dos materiais nem de análise estruturada. O PDF é
        # gerado aqui (reaproveitando o mesmo gerador usado pelo botão de
        # download da tela de análise) e é isso que vai pro repositório;
        # o repositório em si não sabe nada sobre gerar relatório, só
        # persiste o que recebe.
        report = self._report_use_case.execute(session, "pdf")
        self._session_repository.save(session, pdf_bytes=report.content, pdf_filename=report.filename)
        session.saved = True
        return session

    def list_summaries(self, limit: int = 50) -> list[dict]:
        return self._session_repository.list_summaries(limit)

    def get(self, session_id: str) -> StudySession | None:
        return self._session_repository.get(session_id)

    def delete(self, session_id: str) -> None:
        self._session_repository.delete(session_id)

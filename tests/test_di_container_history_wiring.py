"""Regressão de composição em presentation/di_container.py: desde que
HistoryService passou a depender de GenerateReportUseCase (pra gerar o PDF
antes de salvar — pedido do usuário "guarde somente o PDF"), build_container
precisa passar a MESMA instância de report_use_case pros dois lugares
(``AppContainer.report_use_case`` e ``HistoryService``) — usar duas
instâncias diferentes não quebraria nada hoje, mas seria um desperdício
silencioso (dois GenerateReportUseCase fazendo a mesma coisa) fácil de
introduzir sem perceber numa reordenação futura do build_container.
"""

from __future__ import annotations

from study_assistant.config.settings import AuthSettings, N8nSettings, Settings, TursoSettings
from study_assistant.presentation.di_container import build_container


def _settings() -> Settings:
    return Settings(
        turso=TursoSettings(database_url="libsql://x.turso.io", auth_token="tok"),
        auth=AuthSettings(username="admin", password_hash="hash"),
        n8n=N8nSettings(webhook_url="https://n8n.example.com/webhook/x"),
        ai_cascade=[],
    )


def test_history_service_usa_a_mesma_instancia_de_report_use_case_do_container() -> None:
    container = build_container(_settings())

    assert container.history_service._report_use_case is container.report_use_case


def test_report_use_case_do_container_tem_o_gerador_de_pdf_disponivel() -> None:
    """Se "pdf" sumir de available_formats, HistoryService.save() (que
    pede explicitamente o formato "pdf") passa a levantar
    ReportGenerationError pra TODA tentativa de salvar no histórico."""
    container = build_container(_settings())

    assert "pdf" in container.report_use_case.available_formats

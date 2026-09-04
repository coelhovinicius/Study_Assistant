"""Testes de presentation/pages_/history_page.py.

Mesmas restrições de "bare mode" (sem streamlit run) explicadas no topo de
test_upload_analysis_page.py: st.button()/themed_button() sempre retornam
False, então simular um clique de verdade exige monkeypatch. E uma função
decorada com ``@st.dialog`` levanta ``StreamlitAPIException`` se chamada
direto fora de um app rodando — os testes do CONTEÚDO do diálogo chamam
``.__wrapped__`` (a função original, sem a decoração) em vez da função
decorada.
"""

from __future__ import annotations

from types import SimpleNamespace

import streamlit as st

from study_assistant.application.report_service import GeneratedReport
from study_assistant.domain.entities import StudySession
from study_assistant.domain.exceptions import ReportGenerationError, RepositoryError
from study_assistant.presentation.pages_ import history_page as page


def setup_function() -> None:
    st.session_state.clear()


def test_excluir_clicado_abre_dialogo_em_vez_de_excluir_direto(monkeypatch) -> None:
    """Regressão: clicar em "Excluir" apagava a sessão do banco na hora,
    sem confirmação — a ação mais destrutiva da tela (apaga permanente do
    Turso) era justamente a que menos perguntava. Agora o clique só abre
    o diálogo (``_confirm_delete_dialog``)."""
    deleted_ids = []

    class _HistoryService:
        def list_summaries(self):
            return [{"id": "abc123", "title": "Sessão X", "created_at": None}]

        def delete(self, session_id):
            deleted_ids.append(session_id)

    container = SimpleNamespace(history_service=_HistoryService())

    # themed_button() é usado só pelo botão "Excluir" nesta tela (o "Ver /
    # baixar" usa st.button comum) — forçar True simula o clique nele sem
    # afetar o resto.
    monkeypatch.setattr(page, "themed_button", lambda *args, **kwargs: True)

    dialog_calls = []
    monkeypatch.setattr(
        page,
        "_confirm_delete_dialog",
        lambda c, **kwargs: dialog_calls.append(kwargs),
    )

    page.render_history_page(container)

    assert dialog_calls == [{"session_id": "abc123", "title": "Sessão X"}]
    assert deleted_ids == []  # não pode ter excluído só pelo clique


def test_confirm_delete_dialog_ao_confirmar_exclui_e_limpa_a_visualizacao(monkeypatch) -> None:
    deleted_ids = []

    class _HistoryService:
        def delete(self, session_id):
            deleted_ids.append(session_id)

    container = SimpleNamespace(history_service=_HistoryService())
    st.session_state[page._VIEWING_KEY] = "abc123"

    monkeypatch.setattr(page, "themed_button", lambda *args, **kwargs: True)

    page._confirm_delete_dialog.__wrapped__(container, session_id="abc123", title="Sessão X")

    assert deleted_ids == ["abc123"]
    assert page._VIEWING_KEY not in st.session_state


def test_confirm_delete_dialog_com_erro_do_turso_nao_estoura_e_mantem_a_sessao(monkeypatch) -> None:
    """Se o Turso estiver fora do ar, o diálogo mostra o erro (não
    testável em bare mode, sem navegador) mas não pode deixar a exceção
    escapar nem remover a sessão da tela de visualização."""

    class _FailingHistoryService:
        def delete(self, session_id):
            raise RepositoryError("turso fora do ar")

    container = SimpleNamespace(history_service=_FailingHistoryService())
    st.session_state[page._VIEWING_KEY] = "abc123"

    monkeypatch.setattr(page, "themed_button", lambda *args, **kwargs: True)

    page._confirm_delete_dialog.__wrapped__(container, session_id="abc123", title="Sessão X")

    assert st.session_state[page._VIEWING_KEY] == "abc123"


# --- visualização: "Ver/baixar" só baixa, nunca renderiza -----------------
#
# Pedido explícito do usuário: em vez de mostrar o conteúdo da sessão na
# tela (seções de análise, insights, múltiplos formatos de download),
# "Ver/baixar" deve SÓ oferecer o PDF pra download — sem renderizar nada.
# Isso vale tanto pra sessão salva depois da mudança pra guardar só o PDF
# (usa o PDF já guardado) quanto pra uma sessão legada (gera o PDF na hora,
# a partir dos materiais/análise que ainda existem pra ela, mas mesmo assim
# só oferece o download).


def test_ver_sessao_salva_so_com_pdf_usa_o_pdf_guardado_direto(monkeypatch) -> None:
    saved_session = StudySession(
        id="abc123",
        title="Sessão X",
        materials=[],
        stored_pdf_bytes=b"%PDF-conteudo-fake",
        stored_pdf_filename="sessao_x.pdf",
    )

    class _HistoryService:
        def list_summaries(self):
            return [{"id": "abc123", "title": "Sessão X", "created_at": None}]

        def get(self, session_id):
            assert session_id == "abc123"
            return saved_session

    report_use_case_calls = []
    container = SimpleNamespace(
        history_service=_HistoryService(),
        report_use_case=SimpleNamespace(
            execute=lambda *a, **k: report_use_case_calls.append((a, k)) or None
        ),
    )
    st.session_state[page._VIEWING_KEY] = "abc123"

    download_button_calls = []
    monkeypatch.setattr(
        st, "download_button", lambda *args, **kwargs: download_button_calls.append(kwargs) or False
    )

    page.render_history_page(container)

    assert report_use_case_calls == []  # PDF já guardado — não gera de novo
    assert len(download_button_calls) == 1
    assert download_button_calls[0]["data"] == b"%PDF-conteudo-fake"
    assert download_button_calls[0]["file_name"] == "sessao_x.pdf"
    assert download_button_calls[0]["mime"] == "application/pdf"


def test_ver_sessao_legada_gera_pdf_na_hora_e_so_oferece_download(monkeypatch) -> None:
    """Sessão salva ANTES da mudança (sem stored_pdf_bytes, mas com
    materiais/análise reconstruídos por get()): o PDF é gerado na hora
    (reaproveitando report_use_case), mas a tela não renderiza nada — só o
    botão de baixar esse PDF recém-gerado."""
    legacy_session = StudySession(id="legado-1", title="Sessão Antiga", materials=[])

    class _HistoryService:
        def list_summaries(self):
            return [{"id": "legado-1", "title": "Sessão Antiga", "created_at": None}]

        def get(self, session_id):
            return legacy_session

    execute_calls = []

    def _fake_execute(session, fmt):
        execute_calls.append((session, fmt))
        return GeneratedReport(content=b"%PDF-gerado-na-hora", filename="sessao_antiga.pdf", mime_type="application/pdf")

    container = SimpleNamespace(
        history_service=_HistoryService(),
        report_use_case=SimpleNamespace(execute=_fake_execute),
    )
    st.session_state[page._VIEWING_KEY] = "legado-1"

    download_button_calls = []
    monkeypatch.setattr(
        st, "download_button", lambda *args, **kwargs: download_button_calls.append(kwargs) or False
    )

    page.render_history_page(container)

    assert execute_calls == [(legacy_session, "pdf")]
    assert len(download_button_calls) == 1
    assert download_button_calls[0]["data"] == b"%PDF-gerado-na-hora"
    assert download_button_calls[0]["file_name"] == "sessao_antiga.pdf"


def test_ver_sessao_legada_com_erro_ao_gerar_pdf_mostra_erro_sem_quebrar(monkeypatch) -> None:
    legacy_session = StudySession(id="legado-1", title="Sessão Antiga", materials=[])

    class _HistoryService:
        def list_summaries(self):
            return [{"id": "legado-1", "title": "Sessão Antiga", "created_at": None}]

        def get(self, session_id):
            return legacy_session

    def _broken_execute(session, fmt):
        raise ReportGenerationError("reportlab não instalado")

    container = SimpleNamespace(
        history_service=_HistoryService(),
        report_use_case=SimpleNamespace(execute=_broken_execute),
    )
    st.session_state[page._VIEWING_KEY] = "legado-1"

    download_button_calls = []
    monkeypatch.setattr(
        st, "download_button", lambda *args, **kwargs: download_button_calls.append(kwargs) or False
    )

    page.render_history_page(container)  # não pode levantar

    assert download_button_calls == []

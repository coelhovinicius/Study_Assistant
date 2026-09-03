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

from study_assistant.domain.entities import StudySession
from study_assistant.domain.exceptions import RepositoryError
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


# --- visualização: sessão salva só com PDF vs. sessão legada --------------


def test_ver_sessao_salva_so_com_pdf_mostra_botao_de_download_e_nao_chama_render_full_result(
    monkeypatch,
) -> None:
    """Sessão salva DEPOIS da mudança pra guardar só o PDF: a tela não tem
    materiais/análise pra mostrar (nem foram salvos) — só um botão pra
    baixar o PDF que está guardado. Não pode cair em render_full_result
    (que tentaria regenerar outros formatos a partir de dados que não
    existem para essa sessão)."""
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

    container = SimpleNamespace(history_service=_HistoryService())
    st.session_state[page._VIEWING_KEY] = "abc123"

    render_full_result_calls = []
    monkeypatch.setattr(
        page, "render_full_result", lambda *args, **kwargs: render_full_result_calls.append((args, kwargs))
    )
    download_button_calls = []
    monkeypatch.setattr(
        st, "download_button", lambda *args, **kwargs: download_button_calls.append(kwargs) or False
    )

    page.render_history_page(container)

    assert render_full_result_calls == []
    assert len(download_button_calls) == 1
    assert download_button_calls[0]["data"] == b"%PDF-conteudo-fake"
    assert download_button_calls[0]["file_name"] == "sessao_x.pdf"
    assert download_button_calls[0]["mime"] == "application/pdf"


def test_ver_sessao_legada_sem_pdf_armazenado_cai_no_render_full_result(monkeypatch) -> None:
    """Sessão salva ANTES da mudança (sem stored_pdf_bytes, mas com
    materiais/análise reconstruídos por get()): continua mostrando tudo na
    tela do jeito que sempre funcionou."""
    legacy_session = StudySession(id="legado-1", title="Sessão Antiga", materials=[])

    class _HistoryService:
        def list_summaries(self):
            return [{"id": "legado-1", "title": "Sessão Antiga", "created_at": None}]

        def get(self, session_id):
            return legacy_session

    container = SimpleNamespace(history_service=_HistoryService())
    st.session_state[page._VIEWING_KEY] = "legado-1"

    render_full_result_calls = []
    monkeypatch.setattr(
        page, "render_full_result", lambda *args, **kwargs: render_full_result_calls.append((args, kwargs))
    )

    page.render_history_page(container)

    assert len(render_full_result_calls) == 1
    args, kwargs = render_full_result_calls[0]
    assert args[1] is legacy_session
    assert kwargs["key_prefix"] == "hist_legado-1"

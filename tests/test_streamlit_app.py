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

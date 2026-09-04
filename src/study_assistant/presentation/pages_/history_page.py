"""Página de histórico: sessões que o usuário optou por salvar."""

from __future__ import annotations

import streamlit as st

from study_assistant.domain.exceptions import ReportGenerationError, RepositoryError
from study_assistant.infrastructure.persistence.datetime_utils import from_iso
from study_assistant.presentation.di_container import AppContainer
from study_assistant.presentation.theme import themed_button
from study_assistant.shared.timezone_format import format_brasilia

_VIEWING_KEY = "history_viewing_session_id"


def _show_repository_error(message: str, exc: RepositoryError) -> None:
    st.error(message)
    with st.expander("Detalhes técnicos"):
        st.code(str(exc))


@st.dialog("Excluir esta sessão?")
def _confirm_delete_dialog(container: AppContainer, *, session_id: str, title: str) -> None:
    st.write(f'Isso apaga "{title}" do histórico — não pode ser desfeito.')
    confirm_col, cancel_col = st.columns(2)
    with confirm_col:
        if themed_button("🗑️ Confirmar", variant="delete", use_container_width=True):
            # st.spinner mostra feedback DURANTE a chamada (mesmo sem rerun
            # — é o que faz o clique não parecer travado enquanto espera o
            # Turso responder, principalmente quando isso demora).
            with st.spinner("Excluindo..."):
                try:
                    container.history_service.delete(session_id)
                except RepositoryError as exc:
                    _show_repository_error("Não foi possível excluir essa sessão agora.", exc)
                else:
                    if st.session_state.get(_VIEWING_KEY) == session_id:
                        st.session_state.pop(_VIEWING_KEY, None)
                    st.rerun()
    with cancel_col:
        if st.button("Cancelar", use_container_width=True):
            st.rerun()


def render_history_page(container: AppContainer) -> None:
    st.header("🗂️ Histórico de sessões salvas")

    try:
        summaries = container.history_service.list_summaries()
    except RepositoryError as exc:
        _show_repository_error(
            "Não foi possível carregar o histórico agora (falha ao acessar o "
            "banco Turso). Tente de novo em instantes.",
            exc,
        )
        return

    if not summaries:
        st.info("Nenhuma sessão salva ainda. Sessões só entram aqui se você clicar em "
                 "\"Salvar no histórico\" na tela de análise.")
        return

    for row in summaries:
        created_at = from_iso(row.get("created_at"))
        created_at_label = format_brasilia(created_at) if created_at else "—"
        with st.container(border=True):
            st.markdown(f"**{row['title']}**")
            st.caption(created_at_label)
            col1, col2 = st.columns(2)
            with col1:
                if st.button("👁️ Ver / baixar", key=f"view_{row['id']}", use_container_width=True):
                    st.session_state[_VIEWING_KEY] = row["id"]
            with col2:
                if themed_button(
                    "🗑️ Excluir",
                    variant="delete",
                    key=f"delete_{row['id']}",
                    use_container_width=True,
                ):
                    _confirm_delete_dialog(container, session_id=row["id"], title=row["title"])

    viewing_id = st.session_state.get(_VIEWING_KEY)
    if not viewing_id:
        return

    try:
        session = container.history_service.get(viewing_id)
    except RepositoryError as exc:
        _show_repository_error("Não foi possível carregar essa sessão agora.", exc)
        return

    if session is None:
        st.session_state.pop(_VIEWING_KEY, None)
        return

    st.divider()
    st.subheader(f"📄 {session.title}")

    # Pedido explícito do usuário: "Ver/baixar" não é mais pra RENDERIZAR
    # nada na tela — é só pra disponibilizar o PDF pra download. Nada de
    # expanders com as seções da análise, nem botões de outros formatos.
    if session.stored_pdf_bytes:
        # Sessão salva DEPOIS da mudança pra guardar só o PDF: o PDF já
        # está pronto, guardado — usa direto, sem gerar nada de novo.
        pdf_bytes = session.stored_pdf_bytes
        pdf_filename = session.stored_pdf_filename or f"{session.title}.pdf"
    else:
        # Legado: sessão salva ANTES da mudança, sem PDF guardado — os
        # materiais/análise ainda existem pra ela (reconstruídos por
        # history_service.get()), então o PDF é gerado na hora, uma vez,
        # só pra virar o download. Mesmo assim NÃO renderiza as seções na
        # tela — só o botão de baixar.
        try:
            report = container.report_use_case.execute(session, "pdf")
        except ReportGenerationError as exc:
            st.error("Não foi possível gerar o PDF dessa sessão agora.")
            with st.expander("Detalhes técnicos"):
                st.code(str(exc))
            return
        pdf_bytes = report.content
        pdf_filename = report.filename

    st.download_button(
        "📄 Baixar PDF",
        data=pdf_bytes,
        file_name=pdf_filename,
        mime="application/pdf",
        use_container_width=True,
        key=f"hist_{session.id}_download_pdf",
    )

"""Ponto de entrada da interface Streamlit: configura a página, decide entre
tela de login e área autenticada, e roteia entre as páginas internas.
"""

from __future__ import annotations

import streamlit as st

from study_assistant.domain.exceptions import RepositoryError
from study_assistant.presentation.di_container import get_container
from study_assistant.presentation.pages_.history_page import render_history_page
from study_assistant.presentation.pages_.login_page import (
    SESSION_KEY_USERNAME,
    is_authenticated,
    logout,
    render_login_page,
    restore_session_from_url,
)
from study_assistant.presentation.pages_.upload_analysis_page import (
    has_unsaved_analysis,
    render_upload_analysis_page,
)
from study_assistant.presentation.theme import (
    LOGO_PATH,
    LOGO_WORDMARK_PATH,
    inject_global_css,
    themed_button,
)


def _page_icon() -> str:
    return str(LOGO_PATH) if LOGO_PATH.is_file() else "📚"


@st.dialog("Sair?")
def _confirm_logout_dialog() -> None:
    st.write("Isso encerra sua sessão — você vai precisar fazer login de novo.")
    if has_unsaved_analysis():
        st.warning("A análise atual ainda não foi salva no histórico — ela será perdida.")
    confirm_col, cancel_col = st.columns(2)
    with confirm_col:
        if themed_button("🚪 Confirmar", variant="delete", use_container_width=True):
            logout()
            st.rerun()
    with cancel_col:
        if st.button("Cancelar", use_container_width=True):
            st.rerun()


def run() -> None:
    st.set_page_config(page_title="Study Assistant", page_icon=_page_icon(), layout="wide")
    inject_global_css()

    try:
        container = get_container()
    except (RepositoryError, RuntimeError) as exc:
        st.error(
            "Não foi possível iniciar o app. Verifique a configuração em "
            "`.streamlit/secrets.toml` (Turso e provedores de IA)."
        )
        with st.expander("Detalhes técnicos"):
            st.code(str(exc))
        st.stop()
        return

    # Tenta reidratar o login a partir do token na URL ANTES de checar
    # is_authenticated() — é isso que faz o F5 não jogar de volta pra tela
    # de login (ver comentário em login_page.py sobre por que isso é
    # necessário).
    restore_session_from_url()

    if not is_authenticated():
        render_login_page(container)
        return

    with st.sidebar:
        if LOGO_WORDMARK_PATH.is_file():
            st.image(str(LOGO_WORDMARK_PATH), width=130)
        st.markdown(f"👤 **{st.session_state[SESSION_KEY_USERNAME]}**")
        page = st.radio("Navegação", ["📚 Nova análise", "🗂️ Histórico"], label_visibility="collapsed")
        st.divider()
        if st.button("Sair", use_container_width=True):
            _confirm_logout_dialog()

    if page.endswith("Nova análise"):
        render_upload_analysis_page(container)
    else:
        render_history_page(container)

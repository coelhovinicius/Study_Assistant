"""Página de login (usuário administrador único)."""

from __future__ import annotations

import secrets
import time

import streamlit as st

from study_assistant.domain.exceptions import AccountLockedError, AuthenticationError
from study_assistant.presentation.di_container import AppContainer
from study_assistant.presentation.theme import LOGO_PATH

SESSION_KEY_USERNAME = "authenticated_username"

# --- Login sobrevivendo a um F5 -------------------------------------------
#
# st.session_state some quando a aba dá um reload completo (F5): o
# Streamlit não reaproveita a sessão anterior nesse caso (é assim que o
# Streamlit funciona, não um bug deste app) — então sem isto aqui, um F5
# sempre jogava de volta pra tela de login. A correção: no login, gera um
# token de sessão aleatório, guarda (token -> usuário + validade) num
# dicionário compartilhado entre TODAS as sessões do processo (por isso
# `st.cache_resource`, não `st.session_state`), e bota o token na URL via
# `st.query_params` — que, ao contrário de `st.session_state`, sobrevive a
# um F5 porque é parte da própria URL recarregada. Em cada execução, se
# não tem login na sessão mas tem um token válido na URL, o login é
# restaurado a partir dele.
#
# O token tem 128 bits de entropia (`secrets.token_urlsafe(16)`) — curto o
# bastante pra não virar uma string gigante na barra de endereço, mas
# ainda assim no patamar recomendado (OWASP) para tokens de sessão; ir
# mais curto que isso deixaria de ser "boa prática" (ficaria adivinhável
# por força bruta). Ele nunca é a senha nem o hash da senha, só um
# identificador opaco — e é revogado no logout.
_TOKEN_QUERY_PARAM = "s"
_TOKEN_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 dias


@st.cache_resource(show_spinner=False)
def _session_token_store() -> dict[str, tuple[str, float]]:
    """token -> (username, epoch de expiração). Um dict só por processo,
    compartilhado entre todas as sessões — é o que permite uma sessão NOVA
    (criada pelo F5) reconhecer um token emitido por uma sessão anterior."""
    return {}


def _issue_session_token(username: str) -> str:
    store = _session_token_store()
    now = time.time()
    # Limpeza oportunista dos tokens já vencidos, pra esse dicionário não
    # crescer pra sempre num processo que fica rodando dias a fio.
    for expired_token in [t for t, (_, expires_at) in store.items() if expires_at <= now]:
        store.pop(expired_token, None)

    token = secrets.token_urlsafe(16)
    store[token] = (username, now + _TOKEN_TTL_SECONDS)
    return token


def restore_session_from_url() -> None:
    """Chamado uma vez no início de cada execução do app (antes de checar
    `is_authenticated`): se a sessão perdeu o login (ex: acabou de levar um
    F5) mas a URL tem um token de sessão válido, restaura o login a partir
    dele — sem precisar pedir usuário/senha de novo."""
    if is_authenticated():
        return

    token = st.query_params.get(_TOKEN_QUERY_PARAM)
    if not token:
        return

    entry = _session_token_store().get(token)
    if entry is None:
        st.query_params.pop(_TOKEN_QUERY_PARAM, None)
        return

    username, expires_at = entry
    if time.time() > expires_at:
        _session_token_store().pop(token, None)
        st.query_params.pop(_TOKEN_QUERY_PARAM, None)
        return

    st.session_state[SESSION_KEY_USERNAME] = username


def is_authenticated() -> bool:
    return bool(st.session_state.get(SESSION_KEY_USERNAME))


def logout() -> None:
    token = st.query_params.get(_TOKEN_QUERY_PARAM)
    if token:
        _session_token_store().pop(token, None)
    st.query_params.pop(_TOKEN_QUERY_PARAM, None)
    st.session_state.pop(SESSION_KEY_USERNAME, None)


def render_login_page(container: AppContainer) -> None:
    # A página principal usa layout="wide" (bom pra tela de upload/análise,
    # com vários materiais e resultados lado a lado) — mas isso faz o
    # formulário de login esticar por toda a largura se renderizado direto.
    # Como o Streamlit não deixa mudar o layout por página, a correção é
    # confinar SÓ o conteúdo do login numa coluna central (o terço do
    # meio: [1, 1, 1] deixa 1/3 da tela pra cada lado e 1/3 pro formulário).
    _, center, _ = st.columns([1, 1, 1])
    with center:
        if LOGO_PATH.is_file():
            st.image(str(LOGO_PATH), width=64)
        st.title("🔐 Study Assistant")
        st.caption("Acesso restrito — uso pessoal.")

        with st.form("login_form", clear_on_submit=False):
            username = st.text_input("Usuário")
            password = st.text_input("Senha", type="password")
            submitted = st.form_submit_button("Entrar", type="primary", use_container_width=True)

        if not submitted:
            return

        if not username or not password:
            st.error("Informe usuário e senha.")
            return

        try:
            user = container.auth_use_case.execute(username.strip(), password)
        except AccountLockedError as exc:
            st.error(str(exc))
        except AuthenticationError as exc:
            st.error(str(exc))
        else:
            st.session_state[SESSION_KEY_USERNAME] = user.username
            st.query_params[_TOKEN_QUERY_PARAM] = _issue_session_token(user.username)
            st.rerun()

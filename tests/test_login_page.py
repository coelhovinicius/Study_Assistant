"""Testes de presentation/pages_/login_page.py — foco na persistência de
login entre F5 (``restore_session_from_url`` / ``_issue_session_token`` /
``logout``).

Regressão: um F5 (reload completo da aba) sempre derrubava o login, porque
``st.session_state`` não sobrevive a um reload — só a URL sobrevive. A
correção guarda um token de sessão num dicionário compartilhado entre
sessões (``st.cache_resource``) e bota o token na URL (``st.query_params``);
em cada execução, ``restore_session_from_url`` reidrata o login a partir
desse token antes de qualquer checagem de autenticação.

Mesmas restrições de "bare mode" do resto da suíte (ver topo de
test_upload_analysis_page.py).
"""

from __future__ import annotations

import time

import streamlit as st

from study_assistant.presentation.pages_ import login_page as page


def setup_function() -> None:
    st.session_state.clear()
    st.query_params.clear()
    page._session_token_store().clear()


def test_restore_nao_faz_nada_se_ja_esta_autenticado() -> None:
    st.session_state[page.SESSION_KEY_USERNAME] = "admin"
    st.query_params[page._TOKEN_QUERY_PARAM] = "token-qualquer"

    page.restore_session_from_url()

    assert st.session_state[page.SESSION_KEY_USERNAME] == "admin"


def test_restore_nao_faz_nada_sem_token_na_url() -> None:
    page.restore_session_from_url()

    assert not page.is_authenticated()


def test_restore_reidrata_o_login_a_partir_de_um_token_valido() -> None:
    token = page._issue_session_token("admin")
    st.query_params[page._TOKEN_QUERY_PARAM] = token
    st.session_state.clear()  # simula o F5: perde session_state, mantém a URL

    page.restore_session_from_url()

    assert st.session_state[page.SESSION_KEY_USERNAME] == "admin"


def test_restore_ignora_token_desconhecido_e_limpa_da_url() -> None:
    st.query_params[page._TOKEN_QUERY_PARAM] = "token-inventado-por-alguem"

    page.restore_session_from_url()

    assert not page.is_authenticated()
    assert page._TOKEN_QUERY_PARAM not in st.query_params


def test_restore_ignora_token_vencido_e_o_remove_do_armazenamento(monkeypatch) -> None:
    token = page._issue_session_token("admin")
    st.query_params[page._TOKEN_QUERY_PARAM] = token

    # Avança o relógio pra além da validade do token sem esperar 7 dias de
    # verdade. Importante: captura o "agora" ANTES do monkeypatch — a lambda
    # não pode chamar time.time() de novo, porque isso patchearia a si
    # mesma (page.time é o mesmo módulo `time` importado aqui no teste).
    future = time.time() + page._TOKEN_TTL_SECONDS + 1
    monkeypatch.setattr(page.time, "time", lambda: future)

    page.restore_session_from_url()

    assert not page.is_authenticated()
    assert token not in page._session_token_store()
    assert page._TOKEN_QUERY_PARAM not in st.query_params


def test_logout_revoga_o_token_e_um_f5_depois_disso_nao_reloga() -> None:
    token = page._issue_session_token("admin")
    st.session_state[page.SESSION_KEY_USERNAME] = "admin"
    st.query_params[page._TOKEN_QUERY_PARAM] = token

    page.logout()

    assert not page.is_authenticated()
    assert page._TOKEN_QUERY_PARAM not in st.query_params
    assert token not in page._session_token_store()

    # E mesmo que alguém reenvie a URL antiga com o token revogado (ex:
    # aba duplicada, histórico do navegador), ele não volta a autenticar.
    st.query_params[page._TOKEN_QUERY_PARAM] = token
    page.restore_session_from_url()
    assert not page.is_authenticated()


def test_tokens_emitidos_tem_128_bits_de_entropia() -> None:
    """O usuário pediu um token mais curto que o padrão — 16 bytes
    (secrets.token_urlsafe(16)) é o piso recomendado (OWASP) pra um token
    de sessão; encurtar mais que isso deixaria de ser boa prática."""
    token = page._issue_session_token("admin")
    # token_urlsafe(16) gera 16 bytes -> ~22 caracteres base64url (sem "=").
    assert len(token) >= 20


def test_tokens_vencidos_sao_limpos_ao_emitir_um_token_novo(monkeypatch) -> None:
    old_token = page._issue_session_token("admin")
    future = time.time() + page._TOKEN_TTL_SECONDS + 1
    monkeypatch.setattr(page.time, "time", lambda: future)

    page._issue_session_token("admin")  # dispara a limpeza oportunista

    assert old_token not in page._session_token_store()

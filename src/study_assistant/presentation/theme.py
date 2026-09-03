"""Tema visual do app: paleta de cores, injeção de CSS e o aviso de
"alterações não salvas" antes de fechar/recarregar a aba.

Paleta: azul-petróleo + dourado extraídos da imagem de referência do
usuário (o medalhão "V"), combinados com lápis-lazúli para ações normais
(entrar, salvar, analisar, ver/baixar) e vermelho para ações destrutivas
(descartar, excluir) — na prática só existem essas duas categorias no app:
"Descartar" (sessão ainda não salva) e "Excluir" (sessão já salva) são, no
fundo, a mesma ação de jogar fora alguma coisa, então usam a mesma cor; e
"Salvar" não precisa se distinguir de "Entrar", os dois são só "a ação
positiva da tela". O Streamlit só tem UMA cor "primária" nativa
(``.streamlit/config.toml``), então o vermelho é pintado via CSS, usando
uma "âncora" invisível (``st.markdown`` + ``:has()``) logo antes do botão
— o jeito padrão de estilizar um widget específico no Streamlit sem
depender da ordem/índice dos elementos no DOM. Se no futuro surgir um
botão que precise de uma cor própria, é só acrescentar uma entrada nova em
``_VARIANT_COLORS`` — a estrutura já suporta mais de uma variante.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import streamlit as st
from streamlit.components.v1 import html as _components_html

# --- Paleta -----------------------------------------------------------

# Identidade (cabeçalhos, título do PDF, destaques) — extraída da imagem.
NAVY = "#0a3f56"
NAVY_DARK = "#062a3a"
GOLD = "#c9a24d"
GOLD_LIGHT = "#e6bf73"

# Botões.
LAPIS_LAZULI = "#26619c"        # ações normais (padrão Azure da Microsoft é próximo disso)
LAPIS_LAZULI_HOVER = "#1f4e7d"
IRON_MAN_RED = "#a6192e"        # ações destrutivas: descartar/excluir (vermelho quente)
IRON_MAN_RED_HOVER = "#841426"

ButtonVariant = Literal["delete"]

_ANCHOR_CLASS: dict[ButtonVariant, str] = {
    "delete": "sa-anchor-delete",
}

_VARIANT_COLORS: dict[ButtonVariant, tuple[str, str, str]] = {
    # (cor base, cor no hover, cor do texto)
    "delete": (IRON_MAN_RED, IRON_MAN_RED_HOVER, "#ffffff"),
}

_ASSETS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "assets"
LOGO_PATH = _ASSETS_DIR / "logo.png"                    # só o medalhão — ícone da aba, login
LOGO_WORDMARK_PATH = _ASSETS_DIR / "logo_wordmark.png"   # medalhão + "Quality Assurance" — sidebar


def _variant_css(variant: ButtonVariant) -> str:
    cls = _ANCHOR_CLASS[variant]
    color, hover, text_color = _VARIANT_COLORS[variant]
    # O seletor ":has()" localiza o "element-container" que contém a âncora
    # e pinta o botão do PRÓXIMO element-container (o botão de verdade) —
    # cobre tanto st.button quanto st.form_submit_button, e tanto o nome de
    # classe mais antigo do Streamlit quanto o data-testid mais novo.
    return f"""
    div.element-container:has(> div.stMarkdown div.{cls}) + div.element-container button,
    div[data-testid="stElementContainer"]:has(> div.stMarkdown div.{cls})
        + div[data-testid="stElementContainer"] button {{
        background-color: {color} !important;
        border-color: {color} !important;
        color: {text_color} !important;
    }}
    div.element-container:has(> div.stMarkdown div.{cls}) + div.element-container button:hover,
    div[data-testid="stElementContainer"]:has(> div.stMarkdown div.{cls})
        + div[data-testid="stElementContainer"] button:hover {{
        background-color: {hover} !important;
        border-color: {hover} !important;
        color: {text_color} !important;
    }}
    /* disabled=True (ex: botão bloqueado durante processamento) precisa
       ficar visivelmente "apagado" — sem esta regra, a cor viva acima (com
       !important) vence a cor cinza que o próprio Streamlit usaria para
       indicar "desabilitado", e o botão continua parecendo clicável. */
    div.element-container:has(> div.stMarkdown div.{cls}) + div.element-container button:disabled,
    div[data-testid="stElementContainer"]:has(> div.stMarkdown div.{cls})
        + div[data-testid="stElementContainer"] button:disabled {{
        background-color: transparent !important;
        border-color: rgba(49, 51, 63, 0.2) !important;
        color: rgba(49, 51, 63, 0.4) !important;
        cursor: not-allowed !important;
    }}
    """


def inject_global_css() -> None:
    """Chame uma vez por execução da página (``streamlit_app.py``)."""
    variant_rules = "".join(_variant_css(v) for v in _ANCHOR_CLASS)
    # Esconder só a <div> marcadora (v1 desta função) não bastava: o
    # Streamlit embrulha TODO st.markdown num "element-container" próprio,
    # e é esse invólucro — não a div marcadora em si — que tem
    # margem/padding e ocupa uma linha no layout. display:none na div de
    # dentro não zera a altura do invólucro por fora dela. A correção é
    # esconder o invólucro inteiro (via :has(), que continua enxergando o
    # marcador mesmo escondido) — aí ele realmente some do fluxo, sem
    # empurrar o botão ao lado pra baixo.
    hide_wrapper_rules = "".join(
        f"""
        div.element-container:has(> div.stMarkdown > div.{cls}),
        div[data-testid="stElementContainer"]:has(> div.stMarkdown div.{cls}) {{
            display: none;
        }}
        """
        for cls in _ANCHOR_CLASS.values()
    )
    st.markdown(
        f"""<style>
        {hide_wrapper_rules}
        /* Botões "normais" (kind=secondary): também na linha lápis-lazúli,
           pra tudo que não é primário nem um dos tipos especiais ficar
           consistente com o resto da paleta. */
        button[kind="secondary"] {{
            border-color: {LAPIS_LAZULI} !important;
            color: {LAPIS_LAZULI} !important;
        }}
        button[kind="secondary"]:hover {{
            border-color: {LAPIS_LAZULI_HOVER} !important;
            color: {LAPIS_LAZULI_HOVER} !important;
            background-color: rgba(38, 97, 156, 0.06) !important;
        }}
        {variant_rules}
        /* Sidebar com um leve toque da identidade (azul-petróleo/dourado). */
        section[data-testid="stSidebar"] {{
            border-right: 1px solid {GOLD};
        }}
        </style>""",
        unsafe_allow_html=True,
    )


def _anchor(variant: ButtonVariant) -> None:
    st.markdown(f'<div class="{_ANCHOR_CLASS[variant]}"></div>', unsafe_allow_html=True)


def themed_button(label: str, *, variant: ButtonVariant, **kwargs) -> bool:
    """``st.button`` na cor de ação destrutiva (vermelho). Para o botão
    "normal" (lápis-lazúli), use ``st.button`` direto — a cor já vem do
    CSS global (funciona tanto com ``type="primary"`` quanto sem)."""
    _anchor(variant)
    return st.button(label, **kwargs)


def themed_form_submit_button(label: str, *, variant: ButtonVariant, **kwargs) -> bool:
    _anchor(variant)
    return st.form_submit_button(label, **kwargs)


def render_unsaved_changes_guard(*, active: bool) -> None:
    """Pede confirmação do navegador antes de fechar/recarregar a aba
    quando há uma análise recém-gerada e ainda não salva no histórico —
    perder uma rodada de análise por engano (ela já custou chamadas de IA)
    seria bem chato.

    ``st.markdown`` com ``<script>`` NÃO executa JS (navegadores não rodam
    scripts inseridos via innerHTML) — por isso isto usa
    ``st.components.v1.html``, cujo conteúdo carrega num iframe de verdade
    (que executa scripts) e, por estar na mesma origem do app, consegue
    alcançar a aba principal via ``window.top`` para registrar o
    ``beforeunload`` nela (não faria sentido registrado só no iframe).
    Isso só intercepta fechar a aba/recarregar/navegar para outra URL — os
    reruns internos do Streamlit (clique em botão, upload) não passam por
    aqui, então não geram pop-up indevido.
    """
    flag = "true" if active else "false"
    _components_html(
        f"""<script>
        try {{
            var top = window.top;
            top.__saUnsavedChanges = {flag};
            if (!top.__saUnloadGuardBound) {{
                top.__saUnloadGuardBound = true;
                top.addEventListener('beforeunload', function (e) {{
                    if (top.__saUnsavedChanges) {{
                        e.preventDefault();
                        e.returnValue = '';
                    }}
                }});
            }}
        }} catch (err) {{
            /* navegador pode restringir acesso entre frames; melhor
               silenciosamente não avisar do que quebrar a página */
        }}
        </script>""",
        height=0,
        width=0,
    )

"""Testes de presentation/theme.py — só a parte pura (sem chamar st.*, que
precisa de uma sessão Streamlit rodando de verdade)."""

from __future__ import annotations

import re

from study_assistant.presentation import theme

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def test_todas_as_cores_da_paleta_sao_hexadecimais_validas() -> None:
    cores = [
        theme.NAVY,
        theme.NAVY_DARK,
        theme.GOLD,
        theme.GOLD_LIGHT,
        theme.LAPIS_LAZULI,
        theme.LAPIS_LAZULI_HOVER,
        theme.IRON_MAN_RED,
        theme.IRON_MAN_RED_HOVER,
    ]
    for cor in cores:
        assert _HEX_RE.match(cor), f"{cor!r} não é um hexadecimal #rrggbb válido"


def test_variante_semantica_delete_tem_ancora_e_cor() -> None:
    # Só existe uma variante hoje: "descartar"/"excluir" são a mesma ação
    # (jogar fora algo), então usam a mesma cor — "salvar" ficou igual a
    # "entrar" (o azul normal), sem precisar de variante própria.
    esperado = {"delete"}
    assert set(theme._ANCHOR_CLASS) == esperado
    assert set(theme._VARIANT_COLORS) == esperado


def test_variant_css_referencia_a_classe_ancora_e_a_cor_certa() -> None:
    for variant in theme._ANCHOR_CLASS:
        css = theme._variant_css(variant)
        assert theme._ANCHOR_CLASS[variant] in css
        cor, hover, _texto = theme._VARIANT_COLORS[variant]
        assert cor in css
        assert hover in css


def test_variant_css_tem_regra_para_botao_desabilitado() -> None:
    """Bug que este teste evita: sem uma regra ``:disabled`` própria, a cor
    viva do botão (pintada com !important) vence a aparência "apagada" que
    o Streamlit usaria pra indicar disabled=True — o botão de "Descartar",
    por exemplo, continuaria com cara de clicável mesmo desabilitado
    durante um salvamento em andamento."""
    for variant in theme._ANCHOR_CLASS:
        css = theme._variant_css(variant)
        assert ":disabled" in css


def test_logo_path_aponta_para_um_arquivo_existente() -> None:
    """O ícone da página e o cabeçalho da sidebar/login dependem deste
    arquivo existir — se o caminho quebrar (ex: reorganização de pastas),
    o app não quebra (há fallback pro emoji 📚), mas silenciosamente perde
    o logo, o que passaria despercebido sem este teste."""
    assert theme.LOGO_PATH.is_file()

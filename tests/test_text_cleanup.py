"""Limpeza dos caracteres de extração no texto mostrado (tela e relatórios).
Casos tirados dos PDFs reais das apostilas do usuário."""

from __future__ import annotations

import pytest

from study_assistant.shared.text_cleanup import clean_display_text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("de\ufb01nição do \ufb02uxo", "definição do fluxo"),
        ("o\ufb00set e\ufb03cient \ufb02ow", "offset efficient flow"),
        ("o trade-o\u01af \ufb01nanceiro", "o trade-off financeiro"),
        ("\uf0b7 Teste de Caixa Branca", "• Teste de Caixa Branca"),
        ("\uf06c Hardware e software.", "• Hardware e software."),
        ("\uf0fc Corretiva: para corrigir", "✓ Corretiva: para corrigir"),
        ("cafe\u0301", "café"),
        ("Texto comum: ção, é, “aspas”, — e →.", "Texto comum: ção, é, “aspas”, — e →."),
        ("", ""),
    ],
)
def test_limpa_os_caracteres_de_extracao(raw: str, expected: str) -> None:
    assert clean_display_text(raw) == expected

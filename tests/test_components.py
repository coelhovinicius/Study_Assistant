"""Testes de presentation/components.py — só a parte pura (filtragem de
formatos), sem chamar st.* de verdade (precisa de uma sessão Streamlit
rodando)."""

from __future__ import annotations

from study_assistant.infrastructure.report_generators import ALL_REPORT_GENERATORS, CsvReportGenerator
from study_assistant.presentation import components


def test_csv_esta_oculto_da_ui_mas_continua_registrado_no_backend() -> None:
    """Pedido do usuário: esconder o botão de baixar .csv da tela, mas
    manter o gerador funcionando no código (reativável no futuro). As duas
    pontas são independentes: _HIDDEN_FORMATS é só um filtro de UI, e
    ALL_REPORT_GENERATORS (o registro "de verdade" dos formatos suportados)
    não pode perder o csv por causa disso."""
    assert "csv" in components._HIDDEN_FORMATS
    assert any(isinstance(gen, CsvReportGenerator) for gen in ALL_REPORT_GENERATORS)


def test_reativar_csv_e_so_tirar_do_conjunto_de_ocultos() -> None:
    """Documenta o "como reativar" via teste: simulando o conjunto vazio,
    o csv voltaria a aparecer na lista de formatos filtrados."""
    available = ["docx", "pdf", "txt", "csv"]
    hidden: frozenset[str] = frozenset()  # simula _HIDDEN_FORMATS vazio
    assert [f for f in available if f not in hidden] == available


def test_filtro_de_formatos_ocultos_remove_apenas_o_csv() -> None:
    available = ["docx", "pdf", "txt", "csv"]
    filtered = [f for f in available if f not in components._HIDDEN_FORMATS]
    assert filtered == ["docx", "pdf", "txt"]

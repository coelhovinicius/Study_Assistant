"""Testes de infrastructure/report_generators/report_content.py."""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

from study_assistant.domain.entities import (
    ApostilaInsights,
    ExtractedSection,
    ExtractionMethod,
    Material,
    MaterialType,
    SourceFormat,
    StudySession,
)
from study_assistant.domain.entities import AnalysisResult
from study_assistant.infrastructure.report_generators.report_content import (
    ReportOutline,
    _EXTRACTION_METHOD_LABELS,
    _reflow_paragraphs,
    build_report_outline,
)


def _minimal_session(**kwargs) -> StudySession:
    material = Material(
        filename="apostila.pdf",
        material_type=MaterialType.APOSTILA,
        source_format=SourceFormat.PDF,
        raw_text="conteúdo",
    )
    defaults = dict(title="Sessão de teste", materials=[material])
    defaults.update(kwargs)
    return StudySession(**defaults)


def test_generated_at_label_usa_horario_de_brasilia() -> None:
    session = _minimal_session(created_at=datetime(2026, 8, 31, 14, 30, tzinfo=timezone.utc))
    outline = build_report_outline(session)
    assert outline.generated_at_label == "31/08/2026 11:30"


def test_report_outline_nao_expoe_mais_provider_label() -> None:
    """``provider_label`` foi removido de propósito: nenhum dos 4 formatos
    de relatório exibe mais "Provedor de IA: ..." (pedido do usuário de não
    anunciar a IA por trás) — manter o campo vivo e sem uso seria só lixo
    esquecido no dataclass."""
    field_names = {f.name for f in dataclasses.fields(ReportOutline)}
    assert "provider_label" not in field_names


def test_rotulo_de_extracao_por_ia_nao_menciona_ia_explicitamente() -> None:
    """O usuário pediu pra tirar os "olha, foi a IA!" — o rótulo do método
    de extração não pode mais conter a sigla "IA" isolada."""
    label = _EXTRACTION_METHOD_LABELS[ExtractionMethod.IA]
    assert label == "identificado por interpretação automática do texto"
    assert "IA" not in label.upper().split()


def test_insights_usam_o_rotulo_suavizado() -> None:
    insights_session = _minimal_session(
        apostila_insights=ApostilaInsights(
            referencias_bibliograficas=ExtractedSection("ref", ExtractionMethod.HEURISTICA),
            dicas_leitura=ExtractedSection("dica", ExtractionMethod.IA),
            desafio_pratico=ExtractedSection("desafio", ExtractionMethod.NAO_ENCONTRADO),
        )
    )
    outline = build_report_outline(insights_session)
    method_labels = {insight.label: insight.method_label for insight in outline.insights}
    assert method_labels["Dicas / Indicações de Leitura"] == "identificado por interpretação automática do texto"


# --- _reflow_paragraphs: bug relatado pelo usuário (PDF com "cara de
# poema" nas páginas 2 a 5 — texto extraído por heurística direto da
# apostila, com uma quebra de linha a cada ~10 palavras, era tratado como
# se cada linha curta fosse um parágrafo próprio). -----------------------


def test_reflow_junta_linhas_de_layout_quebrado_num_paragrafo_so() -> None:
    """Texto exatamente como o extraído bruto do PDF da apostila: cada
    linha é só onde o PDF original quebrou visualmente, não onde o
    parágrafo termina de verdade."""
    texto_quebrado = (
        "Com base no que você aprendeu sobre teste e inspeção de\n"
        "Software, verifique os seguintes itens em sua análise:"
    )
    resultado = _reflow_paragraphs(texto_quebrado)
    assert resultado == (
        "Com base no que você aprendeu sobre teste e inspeção de "
        "Software, verifique os seguintes itens em sua análise:"
    )
    # o ponto central do bug: isso não pode continuar sendo 2 "parágrafos"
    assert resultado.count("\n") == 0


def test_reflow_preserva_itens_de_lista_com_marcador_mesmo_sem_linha_em_branco() -> None:
    """Réplica fiel do "Desafio Prático" do PDF que o usuário anexou: uma
    lista de bullets sem NENHUMA linha em branco entre eles, cada um
    quebrado em várias linhas de layout."""
    texto_quebrado = (
        "• Busque a identificação do problema, apontando três\n"
        "falhas que você acredita que poderiam ter sido\n"
        "detectadas durante as inspeções e testes.\n"
        "• Mapeie as possíveis causas dessas falhas."
    )
    resultado = _reflow_paragraphs(texto_quebrado)
    paragrafos = resultado.split("\n")
    assert paragrafos == [
        "• Busque a identificação do problema, apontando três falhas que "
        "você acredita que poderiam ter sido detectadas durante as "
        "inspeções e testes.",
        "• Mapeie as possíveis causas dessas falhas.",
    ]


def test_reflow_respeita_linha_em_branco_como_separador_de_paragrafo() -> None:
    texto = "Primeiro parágrafo,\nem duas linhas.\n\nSegundo parágrafo."
    resultado = _reflow_paragraphs(texto)
    assert resultado == "Primeiro parágrafo, em duas linhas.\nSegundo parágrafo."


def test_reflow_nao_altera_texto_ja_bem_formado_da_ia() -> None:
    """Texto como a IA já devolve (um parágrafo por linha, sem quebra de
    layout no meio) precisa passar batido — sem isso seria uma regressão
    no que já funcionava."""
    texto_ia = (
        "Primeiro parágrafo já completo numa linha só.\n"
        "Segundo parágrafo, também completo."
    )
    assert _reflow_paragraphs(texto_ia) == texto_ia


def test_reflow_com_texto_vazio_retorna_vazio() -> None:
    assert _reflow_paragraphs("") == ""
    assert _reflow_paragraphs("   \n  \n") == ""


def test_build_report_outline_aplica_reflow_nos_insights() -> None:
    session = _minimal_session(
        apostila_insights=ApostilaInsights(
            referencias_bibliograficas=ExtractedSection(
                "Com base no que você aprendeu sobre teste e inspeção de\n"
                "Software, verifique os seguintes itens em sua análise:",
                ExtractionMethod.HEURISTICA,
            ),
            dicas_leitura=ExtractedSection("", ExtractionMethod.NAO_ENCONTRADO),
            desafio_pratico=ExtractedSection("", ExtractionMethod.NAO_ENCONTRADO),
        )
    )
    outline = build_report_outline(session)
    referencias = next(i for i in outline.insights if i.label == "Referências Bibliográficas")
    assert "\n" not in referencias.content


def test_build_report_outline_aplica_reflow_nas_secoes_de_analise() -> None:
    session = _minimal_session(
        analysis_result=AnalysisResult(
            sections={
                "analise_apostila": (
                    "• Busque a identificação do problema, apontando três\n"
                    "falhas que você acredita que poderiam ter sido\n"
                    "detectadas durante as inspeções e testes."
                )
            },
            generated_by_provider="OpenAI",
            generated_by_model="gpt-5.5",
            provider_attempts=(),
        )
    )
    outline = build_report_outline(session)
    _, content = outline.sections[0]
    assert content == (
        "• Busque a identificação do problema, apontando três falhas que "
        "você acredita que poderiam ter sido detectadas durante as "
        "inspeções e testes."
    )


def test_reflow_mantem_o_subtitulo_de_parte_numa_linha_propria() -> None:
    """Subtítulo "### Parte X de Y — ..." (análise em lotes) não termina em
    pontuação — sem tratamento, o parágrafo seguinte seria grudado nele."""
    text = (
        "### Parte 1 de 2 — Fundamentos\nPrimeiro parágrafo da parte.\n\n"
        "### Parte 2 de 2 — Organização\nSegundo."
    )

    assert _reflow_paragraphs(text).split("\n") == [
        "### Parte 1 de 2 — Fundamentos",
        "Primeiro parágrafo da parte.",
        "### Parte 2 de 2 — Organização",
        "Segundo.",
    ]


def test_split_bold_separa_os_trechos_em_negrito_do_markdown() -> None:
    from study_assistant.infrastructure.report_generators.report_content import split_bold, strip_bold

    assert split_bold("Um **Método** formaliza o **Processo**.") == [
        ("Um ", False),
        ("Método", True),
        (" formaliza o ", False),
        ("Processo", True),
        (".", False),
    ]
    assert split_bold("asterisco sem par ** some") == [("asterisco sem par  some", False)]
    assert strip_bold("### **Parte 1** — Título") == "### Parte 1 — Título"


def test_sem_apostila_o_bloco_de_extracoes_fala_em_material_e_esconde_o_nao_encontrado() -> None:
    session = _minimal_session(
        apostila_insights=ApostilaInsights(
            referencias_bibliograficas=ExtractedSection("", ExtractionMethod.NAO_ENCONTRADO),
            dicas_leitura=ExtractedSection("", ExtractionMethod.NAO_ENCONTRADO),
            desafio_pratico=ExtractedSection("Caso da startup.", ExtractionMethod.HEURISTICA),
            from_apostila=False,
        )
    )

    outline = build_report_outline(session)

    assert outline.insights_title == "Extrações do Material"
    assert [item.label for item in outline.insights] == ["Desafio Prático (norte para a resolução)"]
    assert outline.insights[0].method_label == "encontrado diretamente no material"


def test_com_apostila_o_bloco_de_extracoes_continua_igual() -> None:
    session = _minimal_session(
        apostila_insights=ApostilaInsights(
            referencias_bibliograficas=ExtractedSection("", ExtractionMethod.NAO_ENCONTRADO),
            dicas_leitura=ExtractedSection("Leia X.", ExtractionMethod.HEURISTICA),
            desafio_pratico=ExtractedSection("Resolva Y.", ExtractionMethod.HEURISTICA),
        )
    )

    outline = build_report_outline(session)

    assert outline.insights_title == "Extrações da Apostila"
    assert len(outline.insights) == 3
    assert outline.insights[0].content == "(não encontrado)"
    assert outline.insights[1].method_label == "encontrado diretamente na apostila"

"""Testes da extração heurística e do fallback com IA para as três seções
que o usuário hoje recorta manualmente da apostila."""

from __future__ import annotations

from study_assistant.application.apostila_heuristics import extract_sections_heuristically
from study_assistant.application.extraction_service import ExtractApostilaInsightsUseCase
from study_assistant.domain.entities import ExtractionMethod
from tests.fixtures.fake_ai_provider import FakeAIProvider

_APOSTILA_COM_CABECALHOS = """
Unidade 3 — Introdução ao Direito Constitucional

Conteúdo teórico da unidade, bastante extenso, falando sobre princípios
fundamentais e organização do Estado.

Referências Bibliográficas
MENDES, Gilmar. Curso de Direito Constitucional. São Paulo: Saraiva, 2020.
BARROSO, Luís Roberto. Curso de Direito Constitucional Contemporâneo.

Dicas de Leitura
Para aprofundar, veja o texto complementar sobre federalismo no portal
da disciplina.

Desafio Prático
Elabore um parecer sobre a constitucionalidade de uma lei estadual que
contrarie norma federal, aplicando os conceitos desta unidade.
""".strip()

_APOSTILA_SEM_CABECALHOS = """
Só um texto corrido qualquer, sem nenhuma seção identificável de
referências, dicas de leitura ou desafio prático.
""".strip()


def test_extracao_heuristica_encontra_as_tres_secoes() -> None:
    sections = extract_sections_heuristically(_APOSTILA_COM_CABECALHOS)

    assert "referencias_bibliograficas" in sections
    assert "MENDES, Gilmar" in sections["referencias_bibliograficas"]

    assert "dicas_leitura" in sections
    assert "federalismo" in sections["dicas_leitura"]

    assert "desafio_pratico" in sections
    assert "parecer" in sections["desafio_pratico"]


def test_extracao_heuristica_retorna_vazio_sem_cabecalhos() -> None:
    sections = extract_sections_heuristically(_APOSTILA_SEM_CABECALHOS)
    assert sections == {}


def test_use_case_usa_heuristica_quando_encontra_cabecalhos() -> None:
    ai_provider = FakeAIProvider("fake", response_text='{"encontrado": false, "conteudo": ""}')
    use_case = ExtractApostilaInsightsUseCase(ai_provider)

    insights = use_case.execute(_APOSTILA_COM_CABECALHOS)

    assert insights.referencias_bibliograficas.method == ExtractionMethod.HEURISTICA
    assert insights.dicas_leitura.method == ExtractionMethod.HEURISTICA
    assert insights.desafio_pratico.method == ExtractionMethod.HEURISTICA
    assert ai_provider.call_count == 0  # não precisou cair para IA
    assert insights.is_complete


def test_use_case_cai_para_ia_quando_heuristica_nao_encontra() -> None:
    ai_provider = FakeAIProvider(
        "fake", response_text='{"encontrado": true, "conteudo": "extraído pela IA"}'
    )
    use_case = ExtractApostilaInsightsUseCase(ai_provider)

    insights = use_case.execute(_APOSTILA_SEM_CABECALHOS)

    assert insights.referencias_bibliograficas.method == ExtractionMethod.IA
    assert insights.referencias_bibliograficas.content == "extraído pela IA"
    assert ai_provider.call_count == 3  # uma chamada por seção


def test_use_case_marca_nao_encontrado_quando_ia_tambem_nao_acha() -> None:
    ai_provider = FakeAIProvider("fake", response_text='{"encontrado": false, "conteudo": ""}')
    use_case = ExtractApostilaInsightsUseCase(ai_provider)

    insights = use_case.execute(_APOSTILA_SEM_CABECALHOS)

    assert insights.referencias_bibliograficas.method == ExtractionMethod.NAO_ENCONTRADO
    assert not insights.is_complete

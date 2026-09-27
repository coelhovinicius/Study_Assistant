"""Testes da extração heurística e do fallback com IA (em lotes) para as
três seções que o usuário hoje recorta manualmente da apostila."""

from __future__ import annotations

import json

from study_assistant.application.ai_caller import ResilientAICaller
from study_assistant.application.apostila_heuristics import extract_sections_heuristically
from study_assistant.application.extraction_service import ExtractApostilaInsightsUseCase
from study_assistant.domain.entities import ExtractionMethod
from study_assistant.infrastructure.ai_providers.cascade import AIProviderCascade
from tests.fixtures.fake_ai_provider import ScriptedAIProvider
from tests.fixtures.in_memory_ai_response_store import FakeClock, InMemoryAIResponseStore

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

_ALL_KEYS = ("referencias_bibliograficas", "dicas_leitura", "desafio_pratico")


def _use_case(provider: ScriptedAIProvider, **kwargs) -> ExtractApostilaInsightsUseCase:
    clock = FakeClock()
    caller = ResilientAICaller(
        AIProviderCascade([provider]), InMemoryAIResponseStore(), sleep=clock.sleep, clock=clock
    )
    return ExtractApostilaInsightsUseCase(caller, **kwargs)


def _answer(**found: str) -> str:
    return json.dumps({key: found.get(key, "") for key in _ALL_KEYS})


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
    provider = ScriptedAIProvider(lambda prompt: _answer())

    insights = _use_case(provider).execute(_APOSTILA_COM_CABECALHOS)

    assert insights.referencias_bibliograficas.method == ExtractionMethod.HEURISTICA
    assert insights.dicas_leitura.method == ExtractionMethod.HEURISTICA
    assert insights.desafio_pratico.method == ExtractionMethod.HEURISTICA
    assert provider.prompts == []  # não precisou cair para IA
    assert insights.is_complete


def test_use_case_cai_para_ia_com_uma_chamada_por_lote_para_todas_as_secoes() -> None:
    provider = ScriptedAIProvider(lambda prompt: _answer(referencias_bibliograficas="extraído pela IA"))

    insights = _use_case(provider).execute(_APOSTILA_SEM_CABECALHOS)

    assert insights.referencias_bibliograficas.method == ExtractionMethod.IA
    assert insights.referencias_bibliograficas.content == "extraído pela IA"
    assert len(provider.prompts) == 1  # apostila pequena = 1 lote, as 3 seções numa chamada só
    assert provider.required_keys == [_ALL_KEYS]


def test_use_case_junta_o_que_cada_lote_encontrou_em_ordem() -> None:
    """Dicas de leitura costumam vir espalhadas pela apostila inteira."""
    pages = [f"[pagina{i}] " + "texto " * 40 for i in range(4)]

    def responder(prompt: str) -> str:
        page = next(p for p in ("pagina0", "pagina1", "pagina2", "pagina3") if p in prompt)
        return _answer(dicas_leitura=f"dica da {page}")

    provider = ScriptedAIProvider(responder)
    insights = _use_case(provider, batch_chars=300).execute("\n\n".join(pages))

    assert len(provider.prompts) == 4
    assert insights.dicas_leitura.content == "dica da pagina0\n\ndica da pagina1\n\ndica da pagina2\n\ndica da pagina3"


def test_so_pede_a_ia_as_secoes_que_a_heuristica_nao_achou() -> None:
    apostila = _APOSTILA_SEM_CABECALHOS + "\n\nDesafio Prático\nResolva o caso X."
    provider = ScriptedAIProvider(lambda prompt: json.dumps({"referencias_bibliograficas": "", "dicas_leitura": ""}))

    insights = _use_case(provider).execute(apostila)

    assert insights.desafio_pratico.method == ExtractionMethod.HEURISTICA
    assert provider.required_keys == [("referencias_bibliograficas", "dicas_leitura")]


def test_use_case_marca_nao_encontrado_quando_ia_tambem_nao_acha() -> None:
    provider = ScriptedAIProvider(lambda prompt: _answer())

    insights = _use_case(provider).execute(_APOSTILA_SEM_CABECALHOS)

    assert insights.referencias_bibliograficas.method == ExtractionMethod.NAO_ENCONTRADO
    assert not insights.is_complete

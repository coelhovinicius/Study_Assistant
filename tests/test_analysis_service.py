"""Testes de application/analysis_service.py — análise em lotes.

O que o usuário pediu e estes testes travam:
* continua sendo UMA análise com as mesmas seções (um PDF só), com cada
  lote virando uma "Parte X de Y — título" dentro da seção do material;
* nenhum lote fica sem análise: falha pausa, e continuar NÃO pede de novo
  à IA o que já tinha sido respondido.
"""

from __future__ import annotations

import json
import re

import pytest

from study_assistant.application.ai_caller import ResilientAICaller
from study_assistant.application.analysis_service import AnalyzeStudyMaterialsUseCase
from study_assistant.domain.entities import (
    ApostilaInsights,
    ExtractedSection,
    ExtractionMethod,
    Material,
    MaterialType,
    SourceFormat,
)
from study_assistant.domain.exceptions import AIProviderError, AnalysisPausedError
from study_assistant.infrastructure.ai_providers.cascade import AIProviderCascade
from tests.fixtures.fake_ai_provider import ScriptedAIProvider
from tests.fixtures.in_memory_ai_response_store import FakeClock, InMemoryAIResponseStore

_FOUND = ApostilaInsights(
    referencias_bibliograficas=ExtractedSection("MENDES, Gilmar. Curso de Direito Constitucional.", ExtractionMethod.HEURISTICA),
    dicas_leitura=ExtractedSection("Leia o texto sobre federalismo.", ExtractionMethod.HEURISTICA),
    desafio_pratico=ExtractedSection("Elabore um parecer sobre a lei X.", ExtractionMethod.HEURISTICA),
)
_NOT_FOUND = ApostilaInsights(
    referencias_bibliograficas=ExtractedSection("", ExtractionMethod.NAO_ENCONTRADO),
    dicas_leitura=ExtractedSection("", ExtractionMethod.NAO_ENCONTRADO),
    desafio_pratico=ExtractedSection("", ExtractionMethod.NAO_ENCONTRADO),
)


def _material(text: str, *, kind: MaterialType = MaterialType.APOSTILA, filename: str = "apostila.pdf") -> Material:
    return Material(filename=filename, material_type=kind, source_format=SourceFormat.PDF, raw_text=text)


def _pages(*names: str) -> str:
    # Cada "página" tem ~200 caracteres e um marcador que o responder
    # abaixo usa pra saber de que lote é o prompt.
    return "\n\n".join(f"[{name}] " + "conteúdo da página " * 10 for name in names)


def _responder(prompt: str) -> str:
    if "DESAFIO PRÁTICO DA APOSTILA" in prompt:
        return json.dumps({"analise_e_resolucao_desafio": "Resolução do desafio."})
    if "REFERÊNCIAS BIBLIOGRÁFICAS DA APOSTILA" in prompt:
        return json.dumps({"analise_referencias_bibliograficas": "Análise das referências."})
    if "DICAS / INDICAÇÕES DE LEITURA DA APOSTILA" in prompt:
        return json.dumps({"analise_dicas_leitura": "Análise das dicas."})
    if "síntese geral" in prompt:
        return json.dumps({"sintese_geral": "Síntese de tudo."})
    pages = re.findall(r"\[(\w+)\]", prompt)
    return json.dumps(
        {"titulo": f"Assunto {'+'.join(pages)}", "analise": f"Análise de {'+'.join(pages)}.", "resumo": f"Resumo {pages}"}
    )


def _use_case(provider: ScriptedAIProvider, store: InMemoryAIResponseStore | None = None, **kwargs) -> AnalyzeStudyMaterialsUseCase:
    clock = FakeClock()
    caller = ResilientAICaller(
        AIProviderCascade([provider]),
        store if store is not None else InMemoryAIResponseStore(),
        sleep=clock.sleep,
        clock=clock,
    )
    return AnalyzeStudyMaterialsUseCase(caller, **kwargs)


def test_material_de_um_lote_so_nao_ganha_subtitulo_de_parte() -> None:
    provider = ScriptedAIProvider(_responder)

    result = _use_case(provider).execute([_material(_pages("p1"))], _FOUND)

    assert result.sections["analise_apostila"] == "Análise de p1."
    assert result.sections["analise_referencias_bibliograficas"] == "Análise das referências."
    assert result.sections["analise_dicas_leitura"] == "Análise das dicas."
    assert result.sections["analise_e_resolucao_desafio"] == "Resolução do desafio."
    assert result.sections["sintese_geral"] == "Síntese de tudo."
    assert result.sections["analise_livro"] == ""  # sem livro, a seção nem aparece no PDF


def test_cada_lote_vira_uma_parte_em_ordem_dentro_da_mesma_secao() -> None:
    provider = ScriptedAIProvider(_responder)
    text = _pages("p1", "p2", "p3", "p4", "p5", "p6")

    result = _use_case(provider, batch_chars=450).execute([_material(text)], _FOUND)

    section = result.sections["analise_apostila"]
    headings = re.findall(r"^### (.+)$", section, flags=re.MULTILINE)
    assert headings == [
        "Parte 1 de 3 — Assunto p1+p2",
        "Parte 2 de 3 — Assunto p3+p4",
        "Parte 3 de 3 — Assunto p5+p6",
    ]
    assert section.index("Análise de p1+p2.") < section.index("Análise de p5+p6.")


def test_secoes_finais_recebem_os_resumos_de_todos_os_lotes() -> None:
    provider = ScriptedAIProvider(_responder)

    _use_case(provider, batch_chars=450).execute([_material(_pages("p1", "p2", "p3", "p4"))], _FOUND)

    challenge_prompt = next(p for p in provider.prompts if "DESAFIO PRÁTICO DA APOSTILA" in p)
    assert "Resumo ['p1', 'p2']" in challenge_prompt
    assert "Resumo ['p3', 'p4']" in challenge_prompt


def test_trecho_nao_encontrado_na_apostila_nao_gasta_chamada_de_ia() -> None:
    provider = ScriptedAIProvider(_responder)

    result = _use_case(provider).execute([_material(_pages("p1"))], _NOT_FOUND)

    assert "Não foram encontradas referências" in result.sections["analise_referencias_bibliograficas"]
    assert "Não foi encontrado um desafio" in result.sections["analise_e_resolucao_desafio"]
    assert len(provider.prompts) == 2  # o lote da apostila + a síntese


def test_lote_que_falha_pausa_e_continuar_nao_pede_de_novo_o_que_ja_veio() -> None:
    """O pedido central do usuário: nada se perde e nada é reanalisado."""
    store = InMemoryAIResponseStore()
    text = _pages("p1", "p2", "p3", "p4", "p5", "p6")
    ai_down_for = {"p3"}

    def flaky(prompt: str) -> str:
        if any(f"[{page}]" in prompt for page in ai_down_for):
            raise AIProviderError("n8n", "Request too large ... tokens per minute (TPM)")
        return _responder(prompt)

    first_try = ScriptedAIProvider(flaky)
    with pytest.raises(AnalysisPausedError) as info:
        _use_case(first_try, store, batch_chars=450).execute([_material(text)], _FOUND)
    assert "parte 2 de 3" in info.value.step_label

    # "Continuar análise": outra rodada (até com o servidor reiniciado —
    # memória vazia, só o banco), com a IA de volta.
    ai_down_for.clear()
    second_try = ScriptedAIProvider(flaky)
    result = _use_case(second_try, store, batch_chars=450).execute([_material(text)], _FOUND)

    assert not any("[p1]" in p for p in second_try.prompts)  # o lote 1 não foi pedido de novo
    assert any("[p3]" in p for p in second_try.prompts)
    assert "Análise de p1+p2." in result.sections["analise_apostila"]
    assert "Análise de p5+p6." in result.sections["analise_apostila"]


def test_varios_arquivos_do_mesmo_tipo_levam_o_nome_do_arquivo_no_subtitulo() -> None:
    provider = ScriptedAIProvider(_responder)
    materials = [
        _material(_pages("a1"), filename="unidade1.pdf"),
        _material(_pages("b1"), filename="unidade2.pdf"),
    ]

    result = _use_case(provider).execute(materials, _FOUND)

    headings = re.findall(r"^### (.+)$", result.sections["analise_apostila"], flags=re.MULTILINE)
    assert headings == ["unidade1.pdf — Assunto a1", "unidade2.pdf — Assunto b1"]


def test_material_alem_do_limite_ganha_observacao_em_vez_de_sumir() -> None:
    provider = ScriptedAIProvider(_responder)
    materials = [
        _material(_pages("p1", "p2")),
        _material(_pages("l1"), kind=MaterialType.LIVRO, filename="livro.pdf"),
    ]

    result = _use_case(provider, max_total_chars=300).execute(materials, _FOUND)

    assert "os últimos" in result.sections["analise_apostila"]
    assert '"livro.pdf" não foi analisado' in result.sections["analise_livro"]
    assert not any("[l1]" in p for p in provider.prompts)


def test_registra_quem_respondeu_e_as_tentativas() -> None:
    provider = ScriptedAIProvider(_responder, name="n8n")

    result = _use_case(provider).execute([_material(_pages("p1"))], _FOUND)

    assert result.generated_by_provider == "n8n"
    assert len(result.provider_attempts) == 5  # lote + referências + dicas + desafio + síntese


def test_podcast_entra_no_limite_antes_dos_livros() -> None:
    """Regressão da análise real do usuário: os dois livros gastaram o limite
    de caracteres e o podcast — curto e central pra aula — ficou de fora."""
    provider = ScriptedAIProvider(_responder)
    materials = [
        _material(_pages("ap1")),
        _material(_pages("la", "lb", "lc"), kind=MaterialType.LIVRO, filename="livro.pdf"),
        _material(_pages("pc1"), kind=MaterialType.AUDIODESCRICAO_PODCAST, filename="podcast.pdf"),
    ]

    result = _use_case(provider, max_total_chars=500).execute(materials, _FOUND)

    assert "Análise de pc1." in result.sections["analise_podcast"]
    assert "não foi analisado" not in result.sections["analise_podcast"]
    assert "os últimos" in result.sections["analise_livro"]  # quem fica com a sobra é o livro


def test_resposta_da_ia_em_lista_vira_texto_legivel_na_secao() -> None:
    """Regressão: a análise das referências veio como lista de objetos e
    ia pro PDF como "[{'referencia': ..., 'conteudo': ...}]"."""

    def responder(prompt: str) -> str:
        if "REFERÊNCIAS BIBLIOGRÁFICAS DA APOSTILA" in prompt:
            return json.dumps(
                {"analise_referencias_bibliograficas": [{"referencia": "SATO, D. 2014.", "conteudo": "CI e CD."}]}
            )
        return _responder(prompt)

    result = _use_case(ScriptedAIProvider(responder)).execute([_material(_pages("p1"))], _FOUND)

    assert result.sections["analise_referencias_bibliograficas"] == "SATO, D. 2014.\nCI e CD."

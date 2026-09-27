"""Testes de config/prompts.py.

Desde a análise em lotes não existe mais o prompt único pedindo as 8
seções de uma vez (e com ele sumiu a regressão de "a IA preencher só a
seção de referências e deixar as outras vazias": cada seção final agora é
uma chamada própria, com uma chave só). O que continua valendo:

* a melhoria pedida pelo usuário nas referências (conteúdo técnico do
  assunto, não "por que foi indicada") — agora no prompt dedicado a elas;
* cada prompt pede exatamente as chaves que o workflow do n8n confere.
"""

from __future__ import annotations

from study_assistant.config.prompts import (
    BATCH_ANALYSIS_KEYS,
    build_batch_analysis_prompt,
    build_batch_extraction_prompt,
    build_challenge_prompt,
    build_reading_tips_prompt,
    build_references_prompt,
    build_synthesis_prompt,
)


def _batch_prompt(part_number: int = 2, part_count: int = 4) -> str:
    return build_batch_analysis_prompt(
        material_label="Apostila",
        filename="unidade3.pdf",
        focus="conceitos-chave",
        part_number=part_number,
        part_count=part_count,
        text="TEXTO DO LOTE",
    )


def test_prompt_de_referencias_ainda_pede_conteudo_tecnico() -> None:
    """A melhoria pedida pelo usuário (conteúdo técnico, não "por que
    indicada") precisa continuar no prompt — isso é uma ADIÇÃO, não algo a
    reverter."""
    prompt = build_references_prompt(references_text="MENDES, Gilmar...", topics="- Parte 1")
    assert "conteúdo técnico" in prompt
    assert "por que foi" in prompt
    assert '"analise_referencias_bibliograficas"' in prompt


def test_prompt_do_lote_pede_as_tres_chaves_que_o_n8n_confere() -> None:
    prompt = _batch_prompt()
    for key in BATCH_ANALYSIS_KEYS:
        assert f'"{key}"' in prompt
    assert "TEXTO DO LOTE" in prompt


def test_prompt_do_lote_diz_qual_parte_esta_sendo_analisada() -> None:
    assert "parte 2 de 4" in _batch_prompt(2, 4)
    assert "foi dividido" not in _batch_prompt(1, 1)


def test_prompts_das_secoes_finais_pedem_uma_chave_cada() -> None:
    assert '"analise_dicas_leitura"' in build_reading_tips_prompt(tips_text="x", topics="y")
    assert '"analise_e_resolucao_desafio"' in build_challenge_prompt(challenge_text="x", summaries="y")
    assert '"sintese_geral"' in build_synthesis_prompt(summaries="y")


def test_desafio_continua_pedindo_resolucao_passo_a_passo() -> None:
    prompt = build_challenge_prompt(challenge_text="Elabore um parecer", summaries="resumos")
    assert "RESOLVA" in prompt
    assert "passo a passo" in prompt
    assert "Elabore um parecer" in prompt


def test_prompt_de_extracao_pede_so_as_secoes_que_faltam() -> None:
    prompt = build_batch_extraction_prompt(
        sections={"desafio_pratico": "Desafio Prático"}, part_number=1, part_count=3, text="texto"
    )
    assert '"desafio_pratico"' in prompt
    assert "referencias_bibliograficas" not in prompt
    assert "não invente" in prompt

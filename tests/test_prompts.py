"""Testes de config/prompts.py.

Cobre a regressão relatada pelo usuário: depois de pedir conteúdo técnico
mais rico nas referências bibliográficas (item 5), a IA passou a gerar
SOMENTE a seção de referências e deixar as outras 7 vazias. A causa
provável foi um item 5 desproporcionalmente longo/enfático em relação aos
demais, fazendo um modelo mais fraco da cascata "focar" só nele. O reforço
abaixo garante que o prompt deixe claro que todas as 8 seções continuam
obrigatórias — sem remover a melhoria pedida no conteúdo das referências.
"""

from __future__ import annotations

from study_assistant.config.prompts import build_analysis_prompt


def _sample_prompt() -> str:
    return build_analysis_prompt(materials_context="material X", insights_context="insights Y")


def test_prompt_ainda_pede_conteudo_tecnico_nas_referencias() -> None:
    """A melhoria pedida pelo usuário (conteúdo técnico, não "por que
    indicada") precisa continuar no prompt — isso é uma ADIÇÃO, não algo a
    reverter."""
    prompt = _sample_prompt()
    assert "conteúdo técnico" in prompt
    assert "por que foi" in prompt


def test_prompt_reforca_que_todas_as_8_secoes_sao_obrigatorias() -> None:
    """Reforço adicionado para corrigir a regressão: o modelo não pode
    parar de gerar as outras 7 seções só porque a instrução de referências
    ficou mais detalhada."""
    prompt = _sample_prompt()
    assert "TODAS elas" in prompt or "todas obrigatórias" in prompt.lower()
    assert "ERRADA" in prompt


def test_item_5_nao_e_desproporcionalmente_maior_que_os_outros_itens() -> None:
    """Raiz da regressão: o item 5 (referências) ficou tão mais longo que
    os itens 1, 6, 7 e 8 que um provedor mais fraco da cascata passou a
    tratá-lo como se fosse a única instrução real. Este teste trava um
    limite de proporção pra evitar que isso volte a acontecer sem que
    alguém perceba."""
    prompt = _sample_prompt()
    lines = prompt.splitlines()

    def _item_block(marker: str, next_marker: str) -> str:
        start = next(i for i, line in enumerate(lines) if line.strip().startswith(marker))
        end = next(i for i, line in enumerate(lines) if line.strip().startswith(next_marker))
        return "\n".join(lines[start:end])

    item5 = _item_block("5.", "6.")
    item7 = _item_block("7.", "8.")

    # Item 5 pode ser um pouco mais detalhado (é o pedido explícito do
    # usuário), mas não pode ser vários múltiplos maior que outro item
    # também "denso" como o 7 (resolução do desafio).
    assert len(item5) <= len(item7) * 2.5


def test_secao_extraction_prompt_continua_intacta() -> None:
    """Mudança foi só no prompt de análise expandida — o prompt de
    fallback de extração de seção não deveria ter sido tocado."""
    from study_assistant.config.prompts import build_section_extraction_prompt

    prompt = build_section_extraction_prompt(section_label="Referências", apostila_text="texto")
    assert "encontrado" in prompt
    assert "conteúdo" in prompt

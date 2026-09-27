"""Testes do parsing tolerante de respostas JSON de IA."""

from __future__ import annotations

import pytest

from study_assistant.application.ai_json_utils import ai_text, parse_json_response
from study_assistant.domain.exceptions import InvalidAIResponseError


def test_parseia_json_puro() -> None:
    assert parse_json_response('{"a": 1}') == {"a": 1}


def test_parseia_json_dentro_de_bloco_markdown() -> None:
    raw = 'Aqui está:\n```json\n{"a": 1}\n```\nEspero que ajude!'
    assert parse_json_response(raw) == {"a": 1}


def test_parseia_json_com_texto_ao_redor() -> None:
    raw = 'Segue o resultado: {"a": 1, "b": "texto"} — qualquer dúvida, avise.'
    assert parse_json_response(raw) == {"a": 1, "b": "texto"}


def test_levanta_erro_quando_nao_ha_json() -> None:
    with pytest.raises(InvalidAIResponseError):
        parse_json_response("isso aqui não é JSON nenhum")

# --- ai_text: valor de uma chave da resposta como texto corrido -----------


def test_ai_text_lista_de_objetos_vira_paragrafos_e_nao_repr_do_python() -> None:
    """Regressão: a análise das referências veio como lista de objetos e
    ia parar no PDF como "[{'referencia': ..., 'conteudo': ...}]"."""
    value = [
        {"referencia": "SATO, D. DevOps na prática. 2014.", "conteudo": "Apresenta CI e CD."},
        {"referencia": "SOMMERVILLE, I. Engenharia de software. 2018.", "conteudo": "Cobre o ciclo de vida."},
    ]

    text = ai_text(value)

    assert text == (
        "SATO, D. DevOps na prática. 2014.\nApresenta CI e CD.\n\n"
        "SOMMERVILLE, I. Engenharia de software. 2018.\nCobre o ciclo de vida."
    )
    assert "{" not in text and "'referencia'" not in text


def test_ai_text_desfaz_quebra_de_linha_escapada_duas_vezes() -> None:
    """Regressão: o gpt-oss devolveu "\\n\\n" literal no meio do texto,
    que aparecia no PDF como "rapidamente.\\n\\nO PMBOK"."""
    assert ai_text("rapidamente.\\n\\nO PMBOK") == "rapidamente.\n\nO PMBOK"


def test_ai_text_valores_vazios_e_simples() -> None:
    assert ai_text(None) == ""
    assert ai_text("  texto  ") == "texto"
    assert ai_text(3) == "3"

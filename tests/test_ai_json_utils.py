"""Testes do parsing tolerante de respostas JSON de IA."""

from __future__ import annotations

import pytest

from study_assistant.application.ai_json_utils import parse_json_response
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

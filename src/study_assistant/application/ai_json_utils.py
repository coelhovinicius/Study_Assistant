"""Parsing tolerante de respostas em JSON vindas de um provedor de IA.

Mesmo pedindo explicitamente "responda só com JSON", modelos às vezes
envolvem a resposta em blocos de markdown (```json ... ```) ou adicionam
uma frase antes/depois. Em vez de fazer cada caso de uso lidar com isso,
centralizamos aqui uma extração tolerante.
"""

from __future__ import annotations

import json
import re

from study_assistant.domain.exceptions import InvalidAIResponseError

_CODE_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def parse_json_response(raw_text: str) -> dict:
    """Tenta interpretar ``raw_text`` como um objeto JSON, com algumas
    tentativas de recuperação antes de desistir."""
    candidates = [raw_text.strip()]

    fence_match = _CODE_FENCE_PATTERN.search(raw_text)
    if fence_match:
        candidates.insert(0, fence_match.group(1).strip())

    first_brace = raw_text.find("{")
    last_brace = raw_text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidates.append(raw_text[first_brace : last_brace + 1].strip())

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict):
            return parsed

    raise InvalidAIResponseError(
        "Não foi possível interpretar a resposta da IA como um JSON válido. "
        f"Resposta recebida (início): {raw_text[:300]!r}"
    )

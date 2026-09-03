"""Extração heurística (baseada em cabeçalhos) das três seções que o
usuário hoje recorta manualmente da apostila: referências bibliográficas,
dicas/indicações de leitura e o desafio prático.

Isso roda sem chamar nenhuma IA — é rápido, gratuito e funciona bem quando
a apostila segue um padrão de cabeçalhos razoavelmente comum. Quando não
encontra uma seção com confiança, deixa o campo marcado como "não
encontrado"; a camada de aplicação (``extraction_service``) decide então
se vale a pena tentar de novo com apoio de IA.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_HEADER_PATTERNS: dict[str, re.Pattern[str]] = {
    "referencias_bibliograficas": re.compile(
        r"referencias(\s+bibliograficas)?\b", re.IGNORECASE
    ),
    "dicas_leitura": re.compile(
        r"(dicas|indicacoes)\s+de\s+leitura\b|leitura\s+complementar\b|"
        r"sugestoes?\s+de\s+leitura\b",
        re.IGNORECASE,
    ),
    "desafio_pratico": re.compile(
        r"desafio\s+pratico\b|resolucao\s+do\s+desafio\b|"
        r"atividade\s+pratica\b|norte\s+para\s+a\s+resolucao\b",
        re.IGNORECASE,
    ),
}

# Prefixo aceitável antes do cabeçalho na mesma linha (numeração, marcadores, etc.)
_MAX_LINE_PREFIX_LENGTH = 20
_LINE_PREFIX_STRIP_CHARS = " .:-–—•\t0123456789"


def _fold(text: str) -> str:
    """Remove acentos e baixa a caixa, preservando o comprimento do texto
    (para que os índices encontrados no texto "dobrado" continuem válidos
    no texto original)."""
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower()


@dataclass(frozen=True)
class _HeaderMatch:
    section_key: str
    start: int
    header_end: int  # fim da linha do cabeçalho, onde o conteúdo começa


def _is_plausible_header_position(folded_text: str, match_start: int) -> bool:
    line_start = folded_text.rfind("\n", 0, match_start) + 1
    prefix = folded_text[line_start:match_start]
    return len(prefix.strip(_LINE_PREFIX_STRIP_CHARS)) <= _MAX_LINE_PREFIX_LENGTH


def _find_header_matches(original_text: str) -> list[_HeaderMatch]:
    folded = _fold(original_text)
    matches: list[_HeaderMatch] = []

    for section_key, pattern in _HEADER_PATTERNS.items():
        for match in pattern.finditer(folded):
            if not _is_plausible_header_position(folded, match.start()):
                continue
            line_end = folded.find("\n", match.end())
            header_end = line_end + 1 if line_end != -1 else len(folded)
            matches.append(_HeaderMatch(section_key, match.start(), header_end))
            break  # só a primeira ocorrência de cada seção é usada

    return sorted(matches, key=lambda m: m.start)


def extract_sections_heuristically(apostila_text: str) -> dict[str, str]:
    """Retorna um dict {chave_da_secao: conteudo}. Chaves ausentes = não encontrado.

    As chaves possíveis são: 'referencias_bibliograficas', 'dicas_leitura',
    'desafio_pratico'.
    """
    matches = _find_header_matches(apostila_text)
    if not matches:
        return {}

    results: dict[str, str] = {}
    for index, header_match in enumerate(matches):
        next_start = matches[index + 1].start if index + 1 < len(matches) else len(apostila_text)
        content = apostila_text[header_match.header_end : next_start].strip()
        if content:
            results[header_match.section_key] = content

    return results

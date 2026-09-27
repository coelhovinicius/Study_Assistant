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
from functools import lru_cache

# Todos com \b no começo: sem isso, "referencias" casava dentro de
# "preferências" ("Recolher preferências e ..." virava o cabeçalho das
# Referências numa apostila real do usuário).
_HEADER_PATTERNS: dict[str, re.Pattern[str]] = {
    "referencias_bibliograficas": re.compile(
        r"\breferencias(\s+bibliograficas)?\b", re.IGNORECASE
    ),
    # "Dica do Professor", "Leitura Fundamental" e "Indicação de leitura 1"
    # são os cabeçalhos que as apostilas da Kroton/Anhanguera do usuário
    # usam de fato (conferido nas 30 apostilas dele): sem eles, a dica ia
    # parar dentro do Desafio Prático e a IA tinha que procurá-la lote a lote.
    "dicas_leitura": re.compile(
        r"\b(?:(?:dicas|indicacoes|indicacao)\s+de\s+leitura|leitura\s+complementar|"
        r"sugestoes?\s+de\s+leitura|leitura\s+fundamental|dica\s+do\s+professor)\b",
        re.IGNORECASE,
    ),
    "desafio_pratico": re.compile(
        # "Teoria em Prática" e "Reflita sobre a seguinte situação" abrem o
        # ENUNCIADO do desafio nas apostilas Kroton do usuário — vêm antes do
        # "Norte para a resolução", que é só a orientação. Sem eles, só a
        # orientação era extraída e a IA resolvia o desafio sem conhecer a
        # situação proposta. "Desafio Profissional", "Desafio Proposto" e
        # "Exercício Proposto" abrem os documentos de desafio avulsos dele.
        r"\b(?:desafio\s+pratico|resolucao\s+do\s+desafio|"
        r"atividade\s+pratica|norte\s+para\s+a\s+resolucao|teoria\s+em\s+pratica|"
        r"reflita\s+sobre\s+a\s+seguinte\s+situacao|desafio\s+profissional|"
        r"desafio\s+proposto|exercicio\s+proposto)\b",
        re.IGNORECASE,
    ),
}

# Prefixo aceitável antes do cabeçalho na mesma linha (numeração, marcadores, etc.)
_MAX_LINE_PREFIX_LENGTH = 20
_LINE_PREFIX_STRIP_CHARS = " .:-–—•\t0123456789"
# Fim de frase seguido de texto ("...profissional. A ") — numeração como
# "1. " ou "3.2. " não conta (antes do ponto vem dígito, não letra).
_SENTENCE_BOUNDARY = re.compile(r"[^\W\d_][.!?]\s+\S")
# E o que pode vir depois dele na mesma linha ("Indicação de leitura 1").
# Uma linha de cabeçalho também não é uma frase terminada em ponto:
# "exemplos e referências na história." (meio do texto) era tomada pelo
# cabeçalho das Referências numa apostila real do usuário, e a lista de
# verdade, no fim, ficava de fora. Reticências não contam como fim de
# frase — "Norte para a resolução..." é cabeçalho de verdade.
_MAX_LINE_SUFFIX_LENGTH = 40

# Marca de layout que vem logo abaixo de "Dica do Professor" e de "Teoria em
# Prática" nas apostilas Kroton do usuário: "Bloco 5" + o nome do professor,
# em linhas próprias — às vezes com o título do slide antes, quebrado em até
# 3 linhas ("Técnicas de usabilidade: \nmelhorando a qualidade da
# \nexperiência do usuário\nBloco 4\nAriel Dias"). Não é conteúdo da seção.
# Só sai se for exatamente isso: "Bloco N" sozinho na linha e, embaixo, uma
# linha curta sem pontuação final (um nome).
_LAYOUT_BYLINE = re.compile(
    r"\A\s*(?:[^\n]{1,100}\n\s*){0,3}bloco\s+\d+\s*\n[^\n.:;!?]{1,60}\n", re.IGNORECASE
)


@lru_cache(maxsize=None)
def _fold_char(ch: str) -> str:
    base = "".join(c for c in unicodedata.normalize("NFKD", ch) if not unicodedata.combining(c)).lower()
    # "…" vira "..." e "ﬁ" vira "fi" na normalização — um caractere virando
    # vários desalinhava o texto "dobrado" do original, e cada trecho saía
    # cortado no começo (ex: "oco 5" em vez de "Bloco 5", numa apostila
    # real do usuário com reticências). Esses ficam como estão.
    return base if len(base) == 1 else ch


def _fold(text: str) -> str:
    """Remove acentos e baixa a caixa, preservando o comprimento do texto
    (para que os índices encontrados no texto "dobrado" continuem válidos
    no texto original)."""
    return "".join(_fold_char(ch) for ch in text)


@dataclass(frozen=True)
class _HeaderMatch:
    section_key: str
    start: int
    header_end: int  # fim da linha do cabeçalho, onde o conteúdo começa


def _is_plausible_header_position(folded_text: str, match_start: int, match_end: int) -> bool:
    line_start = folded_text.rfind("\n", 0, match_start) + 1
    line_end = folded_text.find("\n", match_end)
    if line_end == -1:
        line_end = len(folded_text)
    prefix = folded_text[line_start:match_start]
    suffix = folded_text[match_end:line_end]
    if len(prefix.strip(_LINE_PREFIX_STRIP_CHARS)) > _MAX_LINE_PREFIX_LENGTH:
        return False
    # Uma frase terminando antes, na mesma linha, = meio de parágrafo, não
    # cabeçalho: "profissional. A resolução do Desafio não precisará ser
    # postada ou" era tomada pelo cabeçalho do desafio (documentos reais).
    if _SENTENCE_BOUNDARY.search(prefix):
        return False
    if len(suffix.strip(_LINE_PREFIX_STRIP_CHARS)) > _MAX_LINE_SUFFIX_LENGTH:
        return False
    line = folded_text[line_start:line_end].rstrip()
    ends_sentence = line.endswith(".") and not line.endswith("..")
    return not ends_sentence


def _find_header_matches(original_text: str) -> list[_HeaderMatch]:
    folded = _fold(original_text)
    matches: list[_HeaderMatch] = []

    for section_key, pattern in _HEADER_PATTERNS.items():
        for match in pattern.finditer(folded):
            if not _is_plausible_header_position(folded, match.start(), match.end()):
                continue
            line_end = folded.find("\n", match.end())
            header_end = line_end + 1 if line_end != -1 else len(folded)
            matches.append(_HeaderMatch(section_key, match.start(), header_end))
            # Só a primeira ocorrência de cada seção: uma lista de referências
            # que continua na página seguinte repete o cabeçalho, e o conteúdo
            # tem que seguir até o próximo cabeçalho de OUTRA seção.
            break

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
        content = _LAYOUT_BYLINE.sub("", apostila_text[header_match.header_end : next_start]).strip()
        if content:
            results[header_match.section_key] = content

    return results

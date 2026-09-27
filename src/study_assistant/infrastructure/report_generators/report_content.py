"""Monta um "esboço" de conteúdo comum, reaproveitado pelos quatro geradores
de relatório (docx/pdf/txt/csv), evitando duplicar a lógica de "o que vai
no relatório e em que ordem" em cada formato.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from study_assistant.domain.entities import (
    SECTION_SUBHEADING_PREFIX,
    ExtractionMethod,
    MaterialType,
    StudySession,
)
from study_assistant.shared.timezone_format import format_brasilia

# Marcadores de item de lista reconhecidos ao reconstruir parágrafos (ver
# ``_reflow_paragraphs``). "* " exige o espaço depois pra não confundir com
# "**negrito**" que a IA às vezes usa dentro do próprio texto.
_BULLET_PREFIXES = ("•", "- ", "* ")

# Uma linha que TERMINA com um desses caracteres é tratada como o fim de
# uma frase/parágrafo de verdade. Uma linha que NÃO termina com nenhum
# deles é tratada como "cortada no meio" pelo layout do PDF/DOCX de
# origem — provavelmente continua na linha seguinte. Ponto-e-vírgula fica
# de fora de propósito: em listas de apostila é comum encadear itens tipo
# "falta de acompanhamento; integração com ferramentas externas." — tratar
# ";" como fim de parágrafo quebraria esse item em dois pedaços soltos.
_SENTENCE_END_CHARS = (".", "!", "?", ":", "…", ")", "\"", "”")


def _reflow_paragraphs(text: str) -> str:
    """Reconstrói parágrafos de verdade a partir de texto que pode vir com
    quebra de linha "de layout" em vez de quebra de linha "de parágrafo".

    Os 4 geradores de relatório (docx/pdf/txt/csv) tratam cada quebra de
    linha (``\\n``) do texto como o fim de um parágrafo — e isso é correto
    para o texto que a IA gera (ela normalmente escreve um parágrafo
    inteiro numa linha só, separando parágrafos por quebra de linha,
    mesmo sem linha em branco entre eles). O problema é o texto extraído
    por HEURÍSTICA direto do PDF/DOCX da apostila (referências, dicas de
    leitura, desafio prático): esse texto preserva a quebra de linha
    ORIGINAL do documento fonte — uma quebra a cada ~10 palavras, não uma
    por parágrafo. Repassado sem tratamento, cada uma dessas linhas curtas
    vira um "parágrafo" próprio nos 4 formatos — no PDF (que justifica o
    texto do corpo) isso literalmente fica com cara de poema: cada linha
    curta esticada pra ocupar a largura toda da página.

    Não dá pra usar só "linha em branco separa parágrafo" como regra: o
    texto da IA muitas vezes NÃO tem linha em branco entre parágrafos (aí
    juntaria parágrafos que deveriam continuar separados). O sinal mais
    confiável é outro: uma linha "cortada no meio" pelo layout quase nunca
    termina em pontuação de fim de frase — ela para no meio de uma
    oração. Por isso, a linha seguinte só é tratada como parágrafo NOVO
    se a linha anterior já tiver terminado em pontuação (. ! ? : ; … ) " ”),
    se houver uma linha em branco entre elas, ou se ela começar com um
    marcador de lista (•, -, *) — o resto é união (continuação da mesma
    linha visualmente quebrada). Texto que já vem "limpo" (um parágrafo
    completo por linha, cada um terminando em pontuação) passa por aqui
    sem alteração nenhuma.

    Subtítulo das partes da análise em lotes ("### Parte 2 de 4 — ...",
    ver ``SECTION_SUBHEADING_PREFIX``) é sempre uma linha própria: não
    termina em pontuação, então sem essa regra o parágrafo seguinte seria
    grudado nele.
    """
    normalized = text.replace("\r\n", "\n").strip()
    if not normalized:
        return normalized

    paragraphs: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            paragraphs.append(" ".join(buffer))
            buffer.clear()

    for raw_line in normalized.split("\n"):
        line = raw_line.strip()
        if not line:
            flush()
            continue
        if line.startswith(SECTION_SUBHEADING_PREFIX):
            flush()
            paragraphs.append(line)
            continue
        starts_new_item = line.startswith(_BULLET_PREFIXES)
        previous_line_ended_sentence = bool(buffer) and buffer[-1].endswith(_SENTENCE_END_CHARS)
        if buffer and (starts_new_item or previous_line_ended_sentence):
            flush()
        buffer.append(line)
    flush()

    return "\n".join(paragraphs)

_BOLD_PATTERN = re.compile(r"\*\*(.+?)\*\*")


def split_bold(line: str) -> list[tuple[str, bool]]:
    """Pedaços de uma linha, marcando os que estavam em **negrito**.

    A IA marca negrito à moda markdown (``**Método**``): a tela mostra
    certo, mas o PDF e o DOCX exibiam os asteriscos no meio do texto. Os
    geradores usam isto pra aplicar o negrito de verdade. Asterisco duplo
    sem par é descartado — nunca aparece solto no documento.
    """
    pieces: list[tuple[str, bool]] = []
    last = 0
    for match in _BOLD_PATTERN.finditer(line):
        if match.start() > last:
            pieces.append((line[last : match.start()], False))
        pieces.append((match.group(1), True))
        last = match.end()
    if last < len(line):
        pieces.append((line[last:], False))
    return [(text.replace("**", ""), bold) for text, bold in pieces if text.replace("**", "")]


def strip_bold(line: str) -> str:
    """A linha sem as marcas de negrito (pra títulos, que já são negrito)."""
    return "".join(text for text, _ in split_bold(line))


_MATERIAL_TYPE_LABELS: dict[MaterialType, str] = {
    MaterialType.APOSTILA: "Apostila",
    MaterialType.LIVRO: "Livro",
    MaterialType.AUDIODESCRICAO_PODCAST: "Audiodescrição do Podcast",
    MaterialType.OUTRO: "Outro material",
}

# Rótulos deliberadamente discretos quanto a "como" cada trecho foi obtido —
# o usuário sabe que o app usa IA por trás, mas não quer isso anunciado a
# cada seção do relatório ("não precisa colocar um giroflex" — pedido dele).
_EXTRACTION_METHOD_LABELS: dict[ExtractionMethod, str] = {
    ExtractionMethod.HEURISTICA: "encontrado diretamente na apostila",
    ExtractionMethod.IA: "identificado por interpretação automática do texto",
    ExtractionMethod.NAO_ENCONTRADO: "não encontrado no material enviado",
}


@dataclass(frozen=True)
class InsightItem:
    label: str
    content: str
    method_label: str


@dataclass(frozen=True)
class MaterialItem:
    filename: str
    type_label: str


@dataclass(frozen=True)
class ReportOutline:
    title: str
    generated_at_label: str
    materials: list[MaterialItem]
    insights: list[InsightItem]
    sections: list[tuple[str, str]]


def build_report_outline(session: StudySession) -> ReportOutline:
    materials = [
        MaterialItem(
            filename=m.filename,
            type_label=_MATERIAL_TYPE_LABELS.get(m.material_type, m.material_type.value),
        )
        for m in session.materials
    ]

    insights: list[InsightItem] = []
    if session.apostila_insights:
        pairs = (
            ("Referências Bibliográficas", session.apostila_insights.referencias_bibliograficas),
            ("Dicas / Indicações de Leitura", session.apostila_insights.dicas_leitura),
            ("Desafio Prático (norte para a resolução)", session.apostila_insights.desafio_pratico),
        )
        for label, section in pairs:
            insights.append(
                InsightItem(
                    label=label,
                    content=_reflow_paragraphs(section.content) or "(não encontrado)",
                    method_label=_EXTRACTION_METHOD_LABELS.get(section.method, ""),
                )
            )

    sections: list[tuple[str, str]] = []
    if session.analysis_result:
        sections = [
            (title, _reflow_paragraphs(content))
            for title, content in session.analysis_result.ordered_sections()
        ]

    return ReportOutline(
        title=session.title,
        generated_at_label=format_brasilia(session.created_at),
        materials=materials,
        insights=insights,
        sections=sections,
    )

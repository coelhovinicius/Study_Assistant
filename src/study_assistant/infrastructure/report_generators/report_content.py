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
from study_assistant.shared.text_cleanup import clean_display_text
from study_assistant.shared.timezone_format import format_brasilia

# Marcadores de item de lista reconhecidos ao reconstruir parágrafos (ver
# ``_reflow_paragraphs``). "* " exige o espaço depois pra não confundir com
# "**negrito**" que a IA às vezes usa dentro do próprio texto. Os símbolos
# são os marcadores que aparecem nas apostilas reais (depois da limpeza de
# ``clean_display_text``, que troca os das fontes Symbol/Wingdings).
_BULLET_PREFIXES = ("•", "◦", "▪", "►", "➢", "✓", "- ", "* ")

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

# **negrito** | *itálico* | `código`. O itálico só vale com o asterisco
# colado no texto e fora de palavra — "5 * 3", "a*b" e "*args" sem par
# continuam como estão.
_INLINE_PATTERN = re.compile(
    r"\*\*(?P<bold>.+?)\*\*"
    r"|(?<![\w*])\*(?![\s*])(?P<italic>[^*\n]+?)(?<![\s*])\*(?![\w*])"
    r"|`(?P<code>[^`\n]+)`"
)


@dataclass(frozen=True)
class InlinePiece:
    text: str
    bold: bool = False
    italic: bool = False


def split_inline(line: str) -> list[InlinePiece]:
    """Pedaços de uma linha com a marcação de texto do markdown da IA.

    A IA marca à moda markdown (``**Método**``, ``*Título do livro*``,
    ```git commit```): a tela mostra certo, mas o PDF e o DOCX exibiam os
    asteriscos e as crases no meio do texto (levantado nos PDFs reais do
    usuário: 84 itálicos e 36 crases à mostra). Os geradores usam isto pra
    aplicar negrito e itálico de verdade; a crase só sai. Asterisco duplo
    sem par é descartado — nunca aparece solto no documento.
    """
    pieces: list[InlinePiece] = []
    last = 0
    for match in _INLINE_PATTERN.finditer(line):
        if match.start() > last:
            pieces.append(InlinePiece(line[last : match.start()]))
        if match.group("bold") is not None:
            pieces.append(InlinePiece(match.group("bold"), bold=True))
        elif match.group("italic") is not None:
            pieces.append(InlinePiece(match.group("italic"), italic=True))
        else:
            pieces.append(InlinePiece(match.group("code")))
        last = match.end()
    if last < len(line):
        pieces.append(InlinePiece(line[last:]))
    return [
        InlinePiece(piece.text.replace("**", ""), piece.bold, piece.italic)
        for piece in pieces
        if piece.text.replace("**", "")
    ]


def split_bold(line: str) -> list[tuple[str, bool]]:
    """``split_inline`` só com o negrito: (texto, está em negrito)."""
    return [(piece.text, piece.bold) for piece in split_inline(line)]


def strip_bold(line: str) -> str:
    """A linha sem as marcas de negrito/itálico (pra títulos, que já são negrito)."""
    return "".join(piece.text for piece in split_inline(line))


_MD_HEADING = re.compile(r"^\s*#{1,6}\s+(.*?)\s*#*\s*$")
_MD_RULE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
_MD_TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


def _table_cells(line: str) -> list[str] | None:
    stripped = line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 3):
        return None
    return [cell.strip() for cell in stripped[1:-1].split("|")]


def _normalize_markdown_blocks(text: str) -> str:
    """Títulos, linhas horizontais e tabelas do markdown da IA, linha a linha,
    no formato que os geradores entendem.

    O prompt pede pra IA não usar títulos markdown, mas ela às vezes usa
    (nos PDFs reais: "#### Cenário e Problema", "---" solto e uma tabela de
    referências impressa como "| --- | --- |" com as linhas grudadas). O
    prompt não muda — mudar o texto enviado faria as respostas guardadas
    serem pedidas de novo à IA (ver ``ai_caller.py``) — então o ajuste é
    aqui:

    * ``#### Título`` vira subtítulo (``SECTION_SUBHEADING_PREFIX``);
    * ``---`` / ``***`` sozinhos na linha somem (o relatório já separa as
      seções);
    * tabela: a linha de cabeçalho vira uma linha em negrito, a de traços
      some, e cada linha vira um item "• célula — célula" (o item é o que
      impede ``_reflow_paragraphs`` de grudar uma linha na outra).
    """
    lines = text.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    for index, line in enumerate(lines):
        heading = _MD_HEADING.match(line)
        if heading:
            out.append(f"{SECTION_SUBHEADING_PREFIX}{heading.group(1)}" if heading.group(1) else "")
            continue
        if _MD_RULE.match(line) or _MD_TABLE_SEPARATOR.match(line) and "|" in line:
            out.append("")
            continue
        cells = _table_cells(line)
        if cells is None:
            out.append(line)
            continue
        cells = [cell for cell in cells if cell]
        if not cells:
            continue
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        if "|" in next_line and _MD_TABLE_SEPARATOR.match(next_line):
            out.append("")
            out.append("**" + " — ".join(strip_bold(cell) for cell in cells) + "**")
        else:
            out.append("• " + " — ".join(cells))
    return "\n".join(out)


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
    insights_title: str = "Extrações da Apostila"


def insights_title(from_apostila: bool) -> str:
    """Título do bloco de referências/dicas/desafio extraídos. Sem apostila
    na análise, eles saíram de "Outros materiais" (ex: um Desafio
    Profissional) — falar em "apostila" ali seria errado."""
    return "Extrações da Apostila" if from_apostila else "Extrações do Material"


def build_report_outline(session: StudySession) -> ReportOutline:
    materials = [
        MaterialItem(
            filename=m.filename,
            type_label=_MATERIAL_TYPE_LABELS.get(m.material_type, m.material_type.value),
        )
        for m in session.materials
    ]

    insights: list[InsightItem] = []
    from_apostila = True
    if session.apostila_insights:
        from_apostila = session.apostila_insights.from_apostila
        pairs = (
            ("Referências Bibliográficas", session.apostila_insights.referencias_bibliograficas),
            ("Dicas / Indicações de Leitura", session.apostila_insights.dicas_leitura),
            ("Desafio Prático (norte para a resolução)", session.apostila_insights.desafio_pratico),
        )
        for label, section in pairs:
            if not from_apostila and section.method == ExtractionMethod.NAO_ENCONTRADO:
                continue  # sem apostila, o que não foi encontrado não aparece
            method_label = _EXTRACTION_METHOD_LABELS.get(section.method, "")
            if not from_apostila:
                method_label = method_label.replace("na apostila", "no material")
            insights.append(
                InsightItem(
                    label=label,
                    content=_reflow_paragraphs(clean_display_text(section.content)) or "(não encontrado)",
                    method_label=method_label,
                )
            )

    sections: list[tuple[str, str]] = []
    if session.analysis_result:
        sections = [
            (title, _reflow_paragraphs(_normalize_markdown_blocks(clean_display_text(content))))
            for title, content in session.analysis_result.ordered_sections()
        ]

    return ReportOutline(
        title=session.title,
        generated_at_label=format_brasilia(session.created_at),
        materials=materials,
        insights=insights,
        sections=sections,
        insights_title=insights_title(from_apostila),
    )

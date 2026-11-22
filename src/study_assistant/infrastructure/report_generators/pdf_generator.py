"""Gerador de relatório em PDF, usando reportlab (platypus).

Estilo visual: paleta "azul-petróleo + dourado" (mesma identidade usada no
resto do app — ver ``presentation/theme.py``), texto do corpo justificado,
títulos de seção destacados em bloco colorido e uma linha horizontal
dourada separando cada bloco, para deixar a divisão entre os assuntos mais
clara sem recorrer a nada chamativo (sem gradientes, sem imagens grandes).
"""

from __future__ import annotations

import functools
import io
import logging
import unicodedata
from pathlib import Path

from study_assistant.domain.entities import SECTION_SUBHEADING_PREFIX, StudySession
from study_assistant.domain.exceptions import ReportGenerationError
from study_assistant.domain.ports import ReportGenerator
from study_assistant.infrastructure.report_generators.report_content import (
    build_report_outline,
    split_inline,
    strip_bold,
)

# Mesma paleta de presentation/theme.py, repetida aqui (não importada
# diretamente) para manter o gerador de PDF independente do Streamlit —
# esta classe não pode depender de nada da camada de apresentação.
_NAVY_HEX = "#0a3f56"
_GOLD_HEX = "#c9a24d"
_GOLD_LIGHT_HEX = "#e6bf73"
_MUTED_HEX = "#5a5a5a"

logger = logging.getLogger(__name__)

# Fonte do PDF: DejaVu Sans Condensed, embutida no arquivo (só os
# caracteres usados). Antes era a Helvetica das 14 fontes padrão do PDF,
# que só cobre o alfabeto latino básico: tudo o que ficava de fora (o "ﬁ"
# do texto das apostilas, o hífen U+2011 da IA, marcadores do Word, caixas
# ┌─┐) saía como um quadrado preto, e cada caso pedia um remendo. A DejaVu
# cobre latim completo, grego, cirílico, setas, símbolos matemáticos, "✓"
# e caixas de desenho. A versão condensada tem largura próxima da
# Helvetica, então o relatório mantém o tamanho e a cara de antes. Licença
# livre (Bitstream Vera + domínio público): ``fonts/LICENSE-DejaVu.txt``.
_FONT_DIR = Path(__file__).resolve().parent / "fonts"
_FONT_FILES = {
    "normal": "DejaVuSansCondensed.ttf",
    "bold": "DejaVuSansCondensed-Bold.ttf",
    "italic": "DejaVuSansCondensed-Oblique.ttf",
    "boldItalic": "DejaVuSansCondensed-BoldOblique.ttf",
}
_FAMILY = "StudySans"
_FAMILY_NAMES = {
    "normal": _FAMILY,
    "bold": f"{_FAMILY}-Bold",
    "italic": f"{_FAMILY}-Oblique",
    "boldItalic": f"{_FAMILY}-BoldOblique",
}
# Sem os arquivos da fonte (ex: pasta faltando num deploy), o PDF continua
# saindo — com a Helvetica e a mesma proteção contra caracteres sem glifo.
_FALLBACK_NAMES = {
    "normal": "Helvetica",
    "bold": "Helvetica-Bold",
    "italic": "Helvetica-Oblique",
    "boldItalic": "Helvetica-BoldOblique",
}


@functools.lru_cache(maxsize=1)
def _fonts() -> dict[str, str]:
    """Registra a família da fonte no reportlab (uma vez por processo) e
    devolve o nome de cada variação: normal, bold, italic, boldItalic."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    try:
        for variant, filename in _FONT_FILES.items():
            pdfmetrics.registerFont(TTFont(_FAMILY_NAMES[variant], str(_FONT_DIR / filename)))
    except Exception as exc:  # noqa: BLE001 - qualquer falha ao ler a fonte cai na Helvetica
        logger.warning("Fonte do PDF indisponível (%s); usando Helvetica.", exc)
        return dict(_FALLBACK_NAMES)
    pdfmetrics.registerFontFamily(_FAMILY, **_FAMILY_NAMES)
    return dict(_FAMILY_NAMES)


# Equivalentes para o que a fonte não tiver. Com a DejaVu quase nada cai
# aqui; com a Helvetica de reserva, é o que evita os quadrados. Só entram
# depois de conferir que a fonte não desenha o caractere original.
_PDF_CHAR_REPLACEMENTS = str.maketrans(
    {
        "‒": "–",  # traço de algarismo -> meia-risca
        "―": "—",  # barra horizontal -> travessão
        "▪": "•",  # ▪ -> •
        "‣": "•",  # ‣ -> •
        "⁃": "•",  # ⁃ -> •
        "◦": "•",  # marcador vazado das apostilas
        "►": "•",
        "▶": "•",
        # Diagramas em texto (caixas desenhadas com ┌─┐ │ └─┘): o desenho
        # equivalente em ASCII.
        "─": "-",
        "━": "-",
        "│": "|",
        "┃": "|",
        **{corner: "+" for corner in "┌┐└┘├┤┬┴┼"},
    }
)


def _encodes(ch: str, encoding: str) -> bool:
    try:
        ch.encode(encoding)
        return True
    except UnicodeEncodeError:
        return False


@functools.lru_cache(maxsize=8192)
def _drawable(ch: str) -> bool:
    """As quatro variações da fonte (normal, negrito, itálico e negrito-
    itálico) desenham ``ch``? Fonte TrueType: o caractere tem de estar na
    tabela de caracteres de cada uma. Helvetica de reserva: a regra do
    reportlab, caber na codificação dela ou na de uma das fontes de
    substituição (Symbol e ZapfDingbats); o que não cabe vira "■"."""
    from reportlab.pdfbase import pdfmetrics

    for name in _fonts().values():
        font = pdfmetrics.getFont(name)
        char_to_glyph = getattr(font.face, "charToGlyph", None)
        if char_to_glyph is not None:
            if ord(ch) not in char_to_glyph:
                return False
        elif not any(
            _encodes(ch, encoding)
            for encoding in [font.encName, *(sub.encName for sub in font.substitutionFonts)]
        ):
            return False
    return True


# Trocados mesmo quando a fonte os tem, pra o texto do PDF continuar
# pesquisável e copiável: quem procura "definição" ou "cliente-servidor"
# não acha "deﬁnição" (ligadura) nem "cliente‑servidor" (hífen U+2011).
_ALWAYS_REPLACED = {
    **{code: unicodedata.normalize("NFKC", chr(code)) for code in range(0xFB00, 0xFB07)},
    0x2010: "-",  # hífen
    0x2011: "-",  # hífen que não quebra linha
    0x200B: "",  # espaço de largura zero
    0x2060: "",  # "word joiner"
    0xFEFF: "",  # BOM / espaço de largura zero sem quebra
}


@functools.lru_cache(maxsize=8192)
def _safe_char(ch: str) -> str:
    """O que vai pro PDF no lugar de ``ch``: nunca um caractere sem glifo.

    Ligaduras, hífens especiais e caracteres invisíveis são sempre trocados
    (``_ALWAYS_REPLACED``). Para o resto, nesta ordem: o próprio caractere,
    se a fonte tem; um equivalente conhecido (``_PDF_CHAR_REPLACEMENTS``);
    a forma de compatibilidade do Unicode (NFKC: espaços finos, letras de
    largura dupla etc.); a letra sem o acento que a fonte não tem. Sem
    nada disso (emoji, ideograma), o caractere sai.
    """
    if ord(ch) in _ALWAYS_REPLACED:
        return "".join(_safe_char(c) for c in _ALWAYS_REPLACED[ord(ch)])
    if _drawable(ch):
        return ch
    replaced = ch.translate(_PDF_CHAR_REPLACEMENTS)
    if replaced != ch:
        return "".join(_safe_char(c) for c in replaced)
    compatible = unicodedata.normalize("NFKC", ch)
    if compatible != ch:
        return "".join(_safe_char(c) for c in compatible)
    base = "".join(c for c in unicodedata.normalize("NFKD", ch) if not unicodedata.combining(c))
    if base and base != ch and all(_drawable(c) for c in base):
        return base
    return ""


def _pdf_safe(text: str) -> str:
    # NFC antes: texto extraído de PDF às vezes traz o acento separado da
    # letra ("e" + acento combinante); junto vira "é", um caractere só.
    return "".join(_safe_char(ch) for ch in unicodedata.normalize("NFC", text))


def _escape(text: str) -> str:
    return (
        _pdf_safe(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


class PdfReportGenerator(ReportGenerator):
    @property
    def format_name(self) -> str:
        return "pdf"

    @property
    def mime_type(self) -> str:
        return "application/pdf"

    def generate(self, session: StudySession) -> bytes:
        try:
            from reportlab.lib import colors
            from reportlab.lib.enums import TA_JUSTIFY
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
            from reportlab.lib.units import cm
            from reportlab.platypus import (
                HRFlowable,
                ListFlowable,
                ListItem,
                Paragraph,
                SimpleDocTemplate,
                Spacer,
            )
        except ImportError as exc:  # pragma: no cover
            raise ReportGenerationError(
                "Dependência 'reportlab' não instalada. Rode: pip install reportlab"
            ) from exc

        navy = colors.HexColor(_NAVY_HEX)
        gold = colors.HexColor(_GOLD_HEX)
        gold_light = colors.HexColor(_GOLD_LIGHT_HEX)
        muted = colors.HexColor(_MUTED_HEX)

        fonts = _fonts()
        base = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "SATitle", parent=base["Title"], textColor=navy, spaceAfter=2,
            fontName=fonts["bold"],
        )
        meta_style = ParagraphStyle(
            "SAMeta", parent=base["Normal"], textColor=muted, fontSize=9,
            fontName=fonts["italic"],
        )
        heading_style = ParagraphStyle(
            "SAHeading", parent=base["Heading1"], textColor=gold_light,
            backColor=navy, fontSize=13, leading=17, spaceBefore=2,
            spaceAfter=8, borderPadding=7, borderRadius=4,
            fontName=fonts["bold"],
        )
        subheading_style = ParagraphStyle(
            "SASubheading", parent=base["Heading2"], textColor=navy,
            fontSize=11, spaceBefore=4, spaceAfter=2, fontName=fonts["bold"],
        )
        body_style = ParagraphStyle(
            "SABody", parent=base["Normal"], alignment=TA_JUSTIFY,
            fontSize=10.2, leading=14.5, spaceAfter=5, fontName=fonts["normal"],
        )
        method_style = ParagraphStyle(
            "SAMethod", parent=meta_style, spaceAfter=3,
        )

        def hr() -> HRFlowable:
            return HRFlowable(
                width="100%", thickness=1, color=gold,
                spaceBefore=4, spaceAfter=12,
            )

        def heading(text: str) -> Paragraph:
            return Paragraph(_escape(text), heading_style)

        def with_bold(line: str) -> str:
            # "**Método**" e "*Livro*" da IA viram negrito e itálico de
            # verdade (antes os asteriscos apareciam no PDF), escapando
            # cada pedaço antes da marcação.
            def mark(piece) -> str:  # noqa: ANN001 - InlinePiece
                text = _escape(piece.text)
                if piece.italic:
                    text = f"<i>{text}</i>"
                return f"<b>{text}</b>" if piece.bold else text

            return "".join(mark(piece) for piece in split_inline(line))

        def body_paragraphs(text: str, style: ParagraphStyle = body_style) -> list[Paragraph]:
            # "### Parte 2 de 4 — ..." (análise em lotes) sai como subtítulo.
            return [
                Paragraph(_escape(strip_bold(chunk[len(SECTION_SUBHEADING_PREFIX):]).strip()), subheading_style)
                if chunk.startswith(SECTION_SUBHEADING_PREFIX)
                else Paragraph(with_bold(chunk), style)
                for chunk in text.split("\n")
                if chunk.strip()
            ]

        outline = build_report_outline(session)
        story: list = []

        story.append(Paragraph(_escape(outline.title), title_style))
        story.append(Paragraph(f"Gerado em: {_escape(outline.generated_at_label)}", meta_style))
        story.append(Spacer(1, 0.5 * cm))

        if outline.materials:
            story.append(heading("Materiais Analisados"))
            story.append(
                ListFlowable(
                    [
                        ListItem(Paragraph(_escape(f"{m.filename} — {m.type_label}"), body_style))
                        for m in outline.materials
                    ],
                    bulletType="bullet",
                    bulletFontName=fonts["normal"],
                )
            )
            story.append(hr())

        if outline.insights:
            story.append(heading(outline.insights_title))
            for insight in outline.insights:
                story.append(Paragraph(_escape(insight.label), subheading_style))
                story.append(Paragraph(f"({_escape(insight.method_label)})", method_style))
                story.extend(body_paragraphs(insight.content))
            story.append(hr())

        for index, (title, content) in enumerate(outline.sections):
            story.append(heading(title))
            story.extend(body_paragraphs(content))
            if index < len(outline.sections) - 1:
                story.append(hr())

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            topMargin=2.6 * cm,
            bottomMargin=2 * cm,
            leftMargin=2 * cm,
            rightMargin=2 * cm,
            title=outline.title,
        )
        doc.build(story, onFirstPage=_draw_page_chrome, onLaterPages=_draw_page_chrome)
        return buffer.getvalue()


def _draw_page_chrome(canvas, doc) -> None:  # noqa: ANN001 - assinatura exigida pelo reportlab
    """Barra superior azul-petróleo + friso dourado e numeração de página no
    rodapé, repetidos em toda página — dá uma identidade visual consistente
    ao documento sem depender de nenhuma imagem embutida."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm

    width, height = A4
    canvas.saveState()

    canvas.setFillColor(colors.HexColor(_NAVY_HEX))
    canvas.rect(0, height - 1.1 * cm, width, 1.1 * cm, fill=1, stroke=0)
    canvas.setFillColor(colors.HexColor(_GOLD_HEX))
    canvas.rect(0, height - 1.15 * cm, width, 0.06 * cm, fill=1, stroke=0)

    canvas.setFont(_fonts()["normal"], 8)
    canvas.setFillColor(colors.HexColor(_MUTED_HEX))
    canvas.drawRightString(width - 2 * cm, 1.2 * cm, f"Página {doc.page}")

    canvas.restoreState()

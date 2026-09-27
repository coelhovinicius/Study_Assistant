"""Gerador de relatório em PDF, usando reportlab (platypus).

Estilo visual: paleta "azul-petróleo + dourado" (mesma identidade usada no
resto do app — ver ``presentation/theme.py``), texto do corpo justificado,
títulos de seção destacados em bloco colorido e uma linha horizontal
dourada separando cada bloco, para deixar a divisão entre os assuntos mais
clara sem recorrer a nada chamativo (sem gradientes, sem imagens grandes).
"""

from __future__ import annotations

import io

from study_assistant.domain.entities import SECTION_SUBHEADING_PREFIX, StudySession
from study_assistant.domain.exceptions import ReportGenerationError
from study_assistant.domain.ports import ReportGenerator
from study_assistant.infrastructure.report_generators.report_content import build_report_outline

# Mesma paleta de presentation/theme.py, repetida aqui (não importada
# diretamente) para manter o gerador de PDF independente do Streamlit —
# esta classe não pode depender de nada da camada de apresentação.
_NAVY_HEX = "#0a3f56"
_GOLD_HEX = "#c9a24d"
_GOLD_LIGHT_HEX = "#e6bf73"
_MUTED_HEX = "#5a5a5a"


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
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

        base = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "SATitle", parent=base["Title"], textColor=navy, spaceAfter=2,
        )
        meta_style = ParagraphStyle(
            "SAMeta", parent=base["Normal"], textColor=muted, fontSize=9,
            fontName="Helvetica-Oblique",
        )
        heading_style = ParagraphStyle(
            "SAHeading", parent=base["Heading1"], textColor=gold_light,
            backColor=navy, fontSize=13, leading=17, spaceBefore=2,
            spaceAfter=8, borderPadding=7, borderRadius=4,
        )
        subheading_style = ParagraphStyle(
            "SASubheading", parent=base["Heading2"], textColor=navy,
            fontSize=11, spaceBefore=4, spaceAfter=2,
        )
        body_style = ParagraphStyle(
            "SABody", parent=base["Normal"], alignment=TA_JUSTIFY,
            fontSize=10.2, leading=14.5, spaceAfter=5,
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

        def body_paragraphs(text: str, style: ParagraphStyle = body_style) -> list[Paragraph]:
            # "### Parte 2 de 4 — ..." (análise em lotes) sai como subtítulo.
            return [
                Paragraph(_escape(chunk[len(SECTION_SUBHEADING_PREFIX):].strip()), subheading_style)
                if chunk.startswith(SECTION_SUBHEADING_PREFIX)
                else Paragraph(_escape(chunk), style)
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
                )
            )
            story.append(hr())

        if outline.insights:
            story.append(heading("Extrações da Apostila"))
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

    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor(_MUTED_HEX))
    canvas.drawRightString(width - 2 * cm, 1.2 * cm, f"Página {doc.page}")

    canvas.restoreState()

"""Gerador de relatório em Word (.docx), usando python-docx."""

from __future__ import annotations

import io

from study_assistant.domain.entities import SECTION_SUBHEADING_PREFIX, StudySession
from study_assistant.domain.exceptions import ReportGenerationError
from study_assistant.domain.ports import ReportGenerator
from study_assistant.infrastructure.report_generators.report_content import (
    build_report_outline,
    split_bold,
    strip_bold,
)


def _add_body_paragraph(document, text: str, alignment) -> None:  # noqa: ANN001 - tipos do python-docx
    # "**Método**" da IA vira negrito de verdade (antes os asteriscos
    # apareciam no documento).
    body = document.add_paragraph()
    for piece, bold in split_bold(text):
        run = body.add_run(piece)
        if bold:
            run.bold = True
    body.alignment = alignment


class DocxReportGenerator(ReportGenerator):
    @property
    def format_name(self) -> str:
        return "docx"

    @property
    def mime_type(self) -> str:
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    def generate(self, session: StudySession) -> bytes:
        try:
            import docx
        except ImportError as exc:  # pragma: no cover
            raise ReportGenerationError(
                "Dependência 'python-docx' não instalada. Rode: pip install python-docx"
            ) from exc

        from docx.enum.text import WD_ALIGN_PARAGRAPH

        outline = build_report_outline(session)
        document = docx.Document()

        document.add_heading(outline.title, level=0)
        meta = document.add_paragraph()
        meta.add_run(f"Gerado em: {outline.generated_at_label}").italic = True

        if outline.materials:
            document.add_heading("Materiais Analisados", level=1)
            for material in outline.materials:
                document.add_paragraph(
                    f"{material.filename} — {material.type_label}", style="List Bullet"
                )

        if outline.insights:
            document.add_heading("Extrações da Apostila", level=1)
            for insight in outline.insights:
                document.add_heading(f"{insight.label}", level=2)
                document.add_paragraph(f"({insight.method_label})").italic = True
                _add_body_paragraph(document, insight.content, WD_ALIGN_PARAGRAPH.JUSTIFY)

        for title, content in outline.sections:
            document.add_heading(title, level=1)
            for paragraph_text in content.split("\n"):
                if not paragraph_text.strip():
                    continue
                if paragraph_text.startswith(SECTION_SUBHEADING_PREFIX):
                    # "### Parte 2 de 4 — ..." (análise em lotes) sai como subtítulo.
                    heading = strip_bold(paragraph_text[len(SECTION_SUBHEADING_PREFIX):]).strip()
                    document.add_heading(heading, level=2)
                    continue
                _add_body_paragraph(document, paragraph_text, WD_ALIGN_PARAGRAPH.JUSTIFY)

        buffer = io.BytesIO()
        document.save(buffer)
        return buffer.getvalue()

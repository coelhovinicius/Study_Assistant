"""Gerador de relatório em texto puro (.txt)."""

from __future__ import annotations

from study_assistant.domain.entities import StudySession
from study_assistant.domain.ports import ReportGenerator
from study_assistant.infrastructure.report_generators.report_content import build_report_outline

_LINE = "=" * 78


class TxtReportGenerator(ReportGenerator):
    @property
    def format_name(self) -> str:
        return "txt"

    @property
    def mime_type(self) -> str:
        return "text/plain"

    def generate(self, session: StudySession) -> bytes:
        outline = build_report_outline(session)
        lines: list[str] = []

        lines.append(_LINE)
        lines.append(outline.title.upper())
        lines.append(_LINE)
        lines.append(f"Gerado em: {outline.generated_at_label}")
        lines.append("")

        if outline.materials:
            lines.append("MATERIAIS ANALISADOS")
            lines.append("-" * 40)
            for material in outline.materials:
                lines.append(f"- [{material.type_label}] {material.filename}")
            lines.append("")

        if outline.insights:
            lines.append(outline.insights_title.upper())
            lines.append("-" * 40)
            for insight in outline.insights:
                lines.append(f"### {insight.label} ({insight.method_label})")
                lines.append(insight.content)
                lines.append("")

        for title, content in outline.sections:
            lines.append(_LINE)
            lines.append(title.upper())
            lines.append(_LINE)
            lines.append(content)
            lines.append("")

        return "\n".join(lines).encode("utf-8")

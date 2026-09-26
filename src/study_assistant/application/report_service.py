"""Caso de uso: gerar o documento final para download (item 6.2 do fluxo)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from study_assistant.domain.entities import StudySession
from study_assistant.domain.exceptions import ReportGenerationError
from study_assistant.domain.ports import ReportGenerator


def _slugify(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text)
    ascii_only = "".join(ch for ch in folded if not unicodedata.combining(ch))
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_only).strip("_").lower()
    return slug or "relatorio_de_estudo"


def report_filename(title: str, format_name: str) -> str:
    """Nome do arquivo de download — também usado por HistoryService.rename()
    pra manter o nome do PDF guardado em sincronia com o título novo."""
    return f"{_slugify(title)}.{format_name}"


@dataclass(frozen=True)
class GeneratedReport:
    content: bytes
    filename: str
    mime_type: str


class GenerateReportUseCase:
    def __init__(self, generators: list[ReportGenerator]) -> None:
        self._generators_by_format = {g.format_name: g for g in generators}

    @property
    def available_formats(self) -> list[str]:
        return sorted(self._generators_by_format)

    def execute(self, session: StudySession, format_name: str) -> GeneratedReport:
        generator = self._generators_by_format.get(format_name)
        if generator is None:
            raise ReportGenerationError(
                f"Formato de relatório '{format_name}' não suportado. "
                f"Disponíveis: {', '.join(self.available_formats)}."
            )

        content = generator.generate(session)
        filename = report_filename(session.title, generator.format_name)
        return GeneratedReport(content=content, filename=filename, mime_type=generator.mime_type)

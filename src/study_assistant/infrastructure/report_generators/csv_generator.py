"""Gerador de relatório em CSV (.csv) — uma linha por seção/insight, boa
para quem quiser importar o resultado em uma planilha."""

from __future__ import annotations

import csv
import io

from study_assistant.domain.entities import StudySession
from study_assistant.domain.ports import ReportGenerator
from study_assistant.infrastructure.report_generators.report_content import build_report_outline

# Mitigação de "CSV injection": se um texto vindo da IA ou de um arquivo
# enviado pelo usuário (ex: nome de arquivo, conteúdo de referência) começar
# com um desses caracteres, Excel/Sheets podem interpretar a célula como
# fórmula ao abrir o CSV. Prefixar com aspas simples (recomendação da OWASP)
# neutraliza isso sem mudar o conteúdo de forma perceptível.
_FORMULA_TRIGGER_CHARS = ("=", "+", "-", "@", "\t", "\r")


def _sanitize_cell(value: str) -> str:
    if value and value[0] in _FORMULA_TRIGGER_CHARS:
        return "'" + value
    return value


class CsvReportGenerator(ReportGenerator):
    @property
    def format_name(self) -> str:
        return "csv"

    @property
    def mime_type(self) -> str:
        return "text/csv"

    def generate(self, session: StudySession) -> bytes:
        outline = build_report_outline(session)
        buffer = io.StringIO()
        writer = csv.writer(buffer, quoting=csv.QUOTE_ALL)

        writer.writerow(["categoria", "titulo", "conteudo"])

        for material in outline.materials:
            writer.writerow(["material", _sanitize_cell(material.filename), material.type_label])

        for insight in outline.insights:
            writer.writerow(["extracao_apostila", insight.label, _sanitize_cell(insight.content)])

        for title, content in outline.sections:
            writer.writerow(["analise", title, _sanitize_cell(content)])

        # utf-8-sig (BOM) para o Excel reconhecer acentuação em pt-BR automaticamente.
        return buffer.getvalue().encode("utf-8-sig")

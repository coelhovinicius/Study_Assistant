"""Geradores concretos de relatório final, um por formato de saída."""

from study_assistant.infrastructure.report_generators.csv_generator import CsvReportGenerator
from study_assistant.infrastructure.report_generators.docx_generator import DocxReportGenerator
from study_assistant.infrastructure.report_generators.pdf_generator import PdfReportGenerator
from study_assistant.infrastructure.report_generators.txt_generator import TxtReportGenerator

ALL_REPORT_GENERATORS = [
    DocxReportGenerator(),
    PdfReportGenerator(),
    TxtReportGenerator(),
    CsvReportGenerator(),
]

__all__ = [
    "CsvReportGenerator",
    "DocxReportGenerator",
    "PdfReportGenerator",
    "TxtReportGenerator",
    "ALL_REPORT_GENERATORS",
]

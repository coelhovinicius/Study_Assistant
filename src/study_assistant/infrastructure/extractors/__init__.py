"""Extratores concretos de texto por formato de arquivo, e um dispatcher
(``CompositeTextExtractor``) que escolhe o extrator certo automaticamente.
"""

from study_assistant.infrastructure.extractors.docx_extractor import DocxTextExtractor
from study_assistant.infrastructure.extractors.pdf_extractor import PdfTextExtractor
from study_assistant.infrastructure.extractors.txt_extractor import TxtTextExtractor
from study_assistant.infrastructure.extractors.composite_extractor import (
    CompositeTextExtractor,
)

__all__ = [
    "DocxTextExtractor",
    "PdfTextExtractor",
    "TxtTextExtractor",
    "CompositeTextExtractor",
]

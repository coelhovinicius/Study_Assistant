"""Extração de texto de arquivos PDF."""

from __future__ import annotations

import io

from study_assistant.domain.exceptions import EmptyDocumentError, TextExtractionError
from study_assistant.domain.ports import TextExtractor


class PdfTextExtractor(TextExtractor):
    """Extrai texto de PDFs "nativos" (com camada de texto).

    Observação: PDFs puramente escaneados (imagem sem OCR) não têm texto
    para extrair. Esse é um limite conhecido da v1 — se isso for um
    problema recorrente, um extrator com OCR (ex: via ``pytesseract``)
    pode ser adicionado depois implementando o mesmo port ``TextExtractor``,
    sem mexer em mais nada no sistema.
    """

    def supports(self, filename: str) -> bool:
        return filename.lower().endswith(".pdf")

    def extract(self, file_bytes: bytes, filename: str) -> str:
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover
            raise TextExtractionError(
                "Dependência 'pypdf' não instalada. Rode: pip install pypdf"
            ) from exc

        try:
            reader = PdfReader(io.BytesIO(file_bytes))
            pages_text = []
            for page in reader.pages:
                pages_text.append(page.extract_text() or "")
            text = "\n\n".join(pages_text).strip()
        except Exception as exc:  # noqa: BLE001 - queremos capturar qualquer erro da lib
            raise TextExtractionError(
                f"Falha ao extrair texto do PDF '{filename}': {exc}"
            ) from exc

        if not text:
            raise EmptyDocumentError(
                f"O PDF '{filename}' não contém texto extraível "
                "(pode ser um documento escaneado sem OCR)."
            )
        return text

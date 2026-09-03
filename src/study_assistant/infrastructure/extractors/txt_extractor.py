"""Extração de texto de arquivos TXT (texto puro)."""

from __future__ import annotations

from study_assistant.domain.exceptions import EmptyDocumentError, TextExtractionError
from study_assistant.domain.ports import TextExtractor

# Tenta as codificações mais comuns em materiais em português antes de desistir.
_ENCODINGS_TO_TRY = ("utf-8", "utf-8-sig", "latin-1", "cp1252")


class TxtTextExtractor(TextExtractor):
    """Lê arquivos .txt, tentando algumas codificações comuns em pt-BR."""

    def supports(self, filename: str) -> bool:
        return filename.lower().endswith(".txt")

    def extract(self, file_bytes: bytes, filename: str) -> str:
        last_error: Exception | None = None
        for encoding in _ENCODINGS_TO_TRY:
            try:
                text = file_bytes.decode(encoding).strip()
                if not text:
                    raise EmptyDocumentError(f"O arquivo '{filename}' está vazio.")
                return text
            except EmptyDocumentError:
                raise
            except UnicodeDecodeError as exc:
                last_error = exc
                continue

        raise TextExtractionError(
            f"Não foi possível decodificar o arquivo '{filename}' com nenhuma "
            f"codificação suportada ({', '.join(_ENCODINGS_TO_TRY)}): {last_error}"
        )

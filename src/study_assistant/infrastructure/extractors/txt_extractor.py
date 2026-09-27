"""Extração de texto de arquivos de texto puro (.txt e .md)."""

from __future__ import annotations

from study_assistant.domain.exceptions import EmptyDocumentError, TextExtractionError
from study_assistant.domain.ports import TextExtractor

# Tenta as codificações mais comuns em materiais em português antes de desistir.
# "utf-8-sig" primeiro: lê UTF-8 com ou sem BOM — com "utf-8" puro, o BOM de
# arquivos salvos pelo Bloco de Notas ficava grudado no começo do texto.
_ENCODINGS_TO_TRY = ("utf-8-sig", "latin-1", "cp1252")


def decode_text(file_bytes: bytes, filename: str) -> str:
    """Bytes de um arquivo de texto como string, tentando as codificações
    mais comuns em pt-BR (também usado pelo extrator de HTML)."""
    last_error: Exception | None = None
    for encoding in _ENCODINGS_TO_TRY:
        try:
            return file_bytes.decode(encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise TextExtractionError(
        f"Não foi possível decodificar o arquivo '{filename}' com nenhuma "
        f"codificação suportada ({', '.join(_ENCODINGS_TO_TRY)}): {last_error}"
    )


class TxtTextExtractor(TextExtractor):
    """Lê arquivos .txt e .md (Markdown também é texto puro — as marcações
    que sobram, como ``#`` e ``**``, não atrapalham a IA), tentando algumas
    codificações comuns em pt-BR."""

    def supports(self, filename: str) -> bool:
        return filename.lower().endswith((".txt", ".md"))

    def extract(self, file_bytes: bytes, filename: str) -> str:
        text = decode_text(file_bytes, filename).strip()
        if not text:
            raise EmptyDocumentError(f"O arquivo '{filename}' está vazio.")
        return text

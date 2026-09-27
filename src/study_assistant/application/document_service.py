"""Caso de uso: ingestão dos arquivos enviados pelo usuário (item 7 do fluxo).

Transforma bytes brutos de upload em entidades ``Material`` com o texto já
extraído, delegando a extração propriamente dita ao port ``TextExtractor``
(implementado por ``CompositeTextExtractor`` na infraestrutura).
"""

from __future__ import annotations

from dataclasses import dataclass

from study_assistant.domain.entities import Material, MaterialType, SourceFormat
from study_assistant.domain.exceptions import UnsupportedFileFormatError
from study_assistant.domain.ports import TextExtractor

_EXTENSION_TO_FORMAT: dict[str, SourceFormat] = {
    ".pdf": SourceFormat.PDF,
    ".docx": SourceFormat.DOCX,
    ".txt": SourceFormat.TXT,
    ".md": SourceFormat.MD,
    ".html": SourceFormat.HTML,
    ".htm": SourceFormat.HTML,
}


@dataclass(frozen=True)
class UploadedFile:
    """DTO simples representando um arquivo recém-enviado, antes da extração."""

    filename: str
    content: bytes
    material_type: MaterialType


class DocumentIngestionService:
    def __init__(self, text_extractor: TextExtractor) -> None:
        self._text_extractor = text_extractor

    def ingest(self, uploaded_files: list[UploadedFile]) -> list[Material]:
        """Extrai o texto de cada arquivo e retorna a lista de ``Material``.

        Levanta ``UnsupportedFileFormatError``, ``TextExtractionError`` ou
        ``EmptyDocumentError`` (todas em ``domain.exceptions``) se algum
        arquivo não puder ser processado — quem chama decide se aborta tudo
        ou segue sem aquele arquivo.
        """
        materials: list[Material] = []
        for uploaded in uploaded_files:
            source_format = self._infer_source_format(uploaded.filename)
            raw_text = self._text_extractor.extract(uploaded.content, uploaded.filename)
            materials.append(
                Material(
                    filename=uploaded.filename,
                    material_type=uploaded.material_type,
                    source_format=source_format,
                    raw_text=raw_text,
                )
            )
        return materials

    @staticmethod
    def _infer_source_format(filename: str) -> SourceFormat:
        lower_name = filename.lower()
        for extension, fmt in _EXTENSION_TO_FORMAT.items():
            if lower_name.endswith(extension):
                return fmt
        raise UnsupportedFileFormatError(
            f"Formato do arquivo '{filename}' não suportado. "
            f"Formatos aceitos: {', '.join(_EXTENSION_TO_FORMAT)}."
        )

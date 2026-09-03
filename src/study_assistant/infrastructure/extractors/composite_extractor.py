"""Dispatcher que escolhe automaticamente o extrator certo para cada arquivo.

Implementa o próprio port ``TextExtractor`` (padrão Composite): a camada de
aplicação não precisa saber quantos extratores existem nem como escolher
entre eles — só usa um ``CompositeTextExtractor`` como se fosse um único
extrator "universal". Adicionar suporte a um novo formato no futuro (ex:
.epub, .rtf) é só implementar mais um ``TextExtractor`` e registrá-lo aqui.
"""

from __future__ import annotations

from study_assistant.domain.exceptions import UnsupportedFileFormatError
from study_assistant.domain.ports import TextExtractor


class CompositeTextExtractor(TextExtractor):
    def __init__(self, extractors: list[TextExtractor]) -> None:
        if not extractors:
            raise ValueError("CompositeTextExtractor precisa de ao menos um extrator.")
        self._extractors = extractors

    def supports(self, filename: str) -> bool:
        return any(extractor.supports(filename) for extractor in self._extractors)

    def extract(self, file_bytes: bytes, filename: str) -> str:
        for extractor in self._extractors:
            if extractor.supports(filename):
                return extractor.extract(file_bytes, filename)

        supported = ", ".join(
            sorted({e.__class__.__name__ for e in self._extractors})
        )
        raise UnsupportedFileFormatError(
            f"Formato do arquivo '{filename}' não é suportado. "
            f"Extratores disponíveis: {supported}."
        )

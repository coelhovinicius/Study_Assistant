"""Extração de texto de páginas HTML (ex: um artigo salvo do navegador)."""

from __future__ import annotations

from html.parser import HTMLParser

from study_assistant.domain.exceptions import EmptyDocumentError
from study_assistant.domain.ports import TextExtractor
from study_assistant.infrastructure.extractors.txt_extractor import decode_text

# O conteúdo destas tags não é texto pra ler (código, estilo, metadados).
_SKIPPED_TAGS = frozenset({"script", "style", "noscript", "template", "head", "svg"})
# Tags que começam um bloco novo — viram quebra de linha, pra o texto não
# sair tudo emendado numa linha só (títulos, parágrafos, itens de lista...).
_BLOCK_TAGS = frozenset(
    {"p", "div", "br", "li", "ul", "ol", "tr", "table", "section", "article", "header",
     "footer", "blockquote", "pre", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "dt", "dd"}
)


class _TextCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001 - assinatura do HTMLParser
        if tag in _SKIPPED_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED_TAGS:
            self._skip_depth = max(self._skip_depth - 1, 0)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


class HtmlTextExtractor(TextExtractor):
    """Lê o texto visível de arquivos .html/.htm, sem as tags, scripts e estilos."""

    def supports(self, filename: str) -> bool:
        return filename.lower().endswith((".html", ".htm"))

    def extract(self, file_bytes: bytes, filename: str) -> str:
        collector = _TextCollector()
        collector.feed(decode_text(file_bytes, filename))
        collector.close()
        lines = (" ".join(line.split()) for line in "".join(collector.parts).split("\n"))
        # Uma linha em branco entre blocos (é o que separa os lotes da análise).
        text = "\n\n".join(line for line in lines if line)
        if not text:
            raise EmptyDocumentError(f"O arquivo '{filename}' não tem texto legível.")
        return text

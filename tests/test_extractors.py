"""Testes dos extratores de texto e da ingestão: formatos aceitos."""

from __future__ import annotations

import pytest

from study_assistant.application.document_service import DocumentIngestionService, UploadedFile
from study_assistant.domain.entities import MaterialType, SourceFormat
from study_assistant.domain.exceptions import EmptyDocumentError, UnsupportedFileFormatError
from study_assistant.infrastructure.extractors import (
    CompositeTextExtractor,
    DocxTextExtractor,
    HtmlTextExtractor,
    PdfTextExtractor,
    TxtTextExtractor,
)

_HTML = """<!DOCTYPE html>
<html><head><title>Título da aba</title><style>p { color: red; }</style>
<script>var x = "não é texto";</script></head>
<body>
  <h1>DevOps na pr&aacute;tica</h1>
  <p>Integração contínua <b>automatiza</b> o build.</p>
  <ul><li>Cultura</li><li>Automação</li></ul>
</body></html>"""


def _service() -> DocumentIngestionService:
    return DocumentIngestionService(
        CompositeTextExtractor([PdfTextExtractor(), TxtTextExtractor(), DocxTextExtractor(), HtmlTextExtractor()])
    )


def test_html_vira_o_texto_visivel_um_bloco_por_paragrafo() -> None:
    text = HtmlTextExtractor().extract(_HTML.encode("utf-8"), "artigo.html")

    assert text == "DevOps na prática\n\nIntegração contínua automatiza o build.\n\nCultura\n\nAutomação"


def test_html_sem_texto_visivel_e_documento_vazio() -> None:
    with pytest.raises(EmptyDocumentError):
        HtmlTextExtractor().extract(b"<html><script>x()</script></html>", "vazio.htm")


def test_markdown_e_lido_como_texto() -> None:
    text = TxtTextExtractor().extract("# Aula 1\n\nConteúdo **importante**.".encode("utf-8"), "notas.md")

    assert text == "# Aula 1\n\nConteúdo **importante**."


def test_txt_com_bom_do_bloco_de_notas_nao_leva_o_bom_pro_texto() -> None:
    text = TxtTextExtractor().extract("\ufeffTexto salvo no Bloco de Notas".encode("utf-8"), "notas.txt")

    assert text == "Texto salvo no Bloco de Notas"


@pytest.mark.parametrize(
    ("filename", "expected"),
    [("artigo.html", SourceFormat.HTML), ("ARTIGO.HTM", SourceFormat.HTML), ("notas.md", SourceFormat.MD)],
)
def test_ingestao_aceita_md_e_html(filename, expected) -> None:
    content = _HTML.encode("utf-8") if "htm" in filename.lower() else b"# Notas\n\nTexto."

    [material] = _service().ingest([UploadedFile(filename, content, MaterialType.OUTRO)])

    assert material.source_format is expected
    assert material.raw_text


def test_formato_nao_suportado_continua_sendo_recusado() -> None:
    with pytest.raises(UnsupportedFileFormatError):
        _service().ingest([UploadedFile("foto.jpg", b"\xff\xd8", MaterialType.OUTRO)])

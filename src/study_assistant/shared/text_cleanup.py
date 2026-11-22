"""Limpeza dos caracteres "de extração" no texto que o app MOSTRA (tela e
relatórios em docx/pdf/txt/csv).

O texto tirado dos PDFs das apostilas (pelo pypdf) traz caracteres que
não são o que o documento mostra — levantados nos 288 PDFs reais de
estudo do usuário:

* ligaduras tipográficas: "ﬁ" (U+FB01, em 97 arquivos), "ﬂ", "ﬀ", "ﬃ"...
  no lugar das letras ("deﬁnição", "ﬂuxo");
* "Ư" (U+01AF) no lugar da ligadura "ff" — "trade-oƯ", "Sign-OƯ",
  "baseTariƯ" (29 arquivos). A letra vietnamita não aparece em texto em
  português, então a troca é segura;
* marcadores de lista das fontes Symbol/Wingdings do Word, que o PDF
  guarda na área de uso privado do Unicode (U+F0B7 em 79 arquivos,
  U+F06C, U+F0A7, U+F071, U+F0FC...): em nenhuma fonte comum eles são um
  marcador — no PDF viravam quadrado preto, na tela um retângulo vazio;
* acento separado da letra ("e" + acento combinante).

A limpeza é só na saída, de propósito: o texto que vai pra IA continua
exatamente o extraído, porque as respostas guardadas são encontradas pela
impressão digital do pedido (``application/ai_caller.py``) — mudar o texto
enviado faria análises já respondidas (ou pausadas) serem refeitas.
"""

from __future__ import annotations

import unicodedata

# Marcadores das fontes Symbol/Wingdings (U+F000 a U+F0FF), com o símbolo
# que o documento original mostra quando há um equivalente claro; o resto
# desse bloco é marcador de lista.
_SYMBOL_FONT_GLYPHS = {
    0xF0FC: "✓",  # Wingdings "ü" = visto
    0xF0E0: "→",  # Wingdings "à" = seta
    0xF0E8: "→",
    0xF0D8: "➢",
}

_TRANSLATION = {
    **{code: unicodedata.normalize("NFKC", chr(code)) for code in range(0xFB00, 0xFB07)},
    0x01AF: "ff",
    **{code: _SYMBOL_FONT_GLYPHS.get(code, "•") for code in range(0xF000, 0xF100)},
}


def clean_display_text(text: str) -> str:
    """O texto como o documento de origem mostrava: ligaduras viram as
    letras, marcadores de fonte Symbol/Wingdings viram "•" (ou o símbolo
    equivalente) e acento separado volta a ser um caractere só ("é")."""
    if not text:
        return text
    return unicodedata.normalize("NFC", text.translate(_TRANSLATION))

"""Divisão do texto dos materiais em lotes que cabem numa chamada de IA.

Mesma ideia do qa_testgen (``_dividir_texto_em_lotes``): os provedores
gratuitos da cascata têm teto de tokens POR MINUTO (Groq: 8.000), e o
material inteiro numa chamada só (até 120 mil caracteres, ~30 mil tokens)
estourava esse teto. Cada lote tem no máximo ``max_chars`` caracteres e o
corte acontece sempre numa fronteira natural do texto — primeiro entre
parágrafos (o extrator de PDF separa as páginas com linha em branco),
depois entre linhas, depois entre palavras — nunca no meio de uma palavra,
a não ser que uma "palavra" sozinha já passe do limite.
"""

from __future__ import annotations

# Da fronteira mais natural pra mais "bruta": só desce pro próximo nível
# o pedaço que, sozinho, ainda passa do limite.
_SEPARATORS: tuple[str, ...] = ("\n\n", "\n", " ")


def split_into_batches(text: str, max_chars: int) -> list[str]:
    """Texto que já cabe no limite volta como um lote só — nenhuma
    mudança de comportamento pra material pequeno."""
    text = (text or "").strip()
    if not text:
        return []
    return _split(text, max_chars, level=0)


def _split(text: str, max_chars: int, *, level: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    if level >= len(_SEPARATORS):
        return [text[i : i + max_chars] for i in range(0, len(text), max_chars)]

    separator = _SEPARATORS[level]
    pieces: list[str] = []
    for part in text.split(separator):
        if part.strip():
            pieces.extend(_split(part, max_chars, level=level + 1))

    # Junta os pedaços de volta, em ordem, enquanto couberem no limite.
    batches: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current}{separator}{piece}" if current else piece
        if len(candidate) <= max_chars:
            current = candidate
        else:
            batches.append(current)
            current = piece
    if current:
        batches.append(current)
    return batches

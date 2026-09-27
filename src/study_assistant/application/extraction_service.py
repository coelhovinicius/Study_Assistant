"""Caso de uso: extrair as referências bibliográficas, as dicas de leitura e
o desafio prático (itens 3, 4 e 5 do fluxo manual original).

Estratégia em duas camadas, do mais barato para o mais caro:
1. Heurística por cabeçalhos (``apostila_heuristics``) — instantânea, sem
   custo de API.
2. Se a heurística não encontrar alguma seção, o documento é lido pela IA em
   lotes (os mesmos da análise, ~12 mil caracteres cada), com UMA chamada
   por lote pedindo todas as seções que faltam de uma vez. Antes eram até 3
   chamadas com 40 mil caracteres cada — o que sozinho já estourava a cota
   por minuto das IAs gratuitas.

O que cada lote encontra é juntado, em ordem (dicas de leitura, por
exemplo, costumam vir espalhadas pela apostila inteira).

Roda na apostila e também em cada documento de "Outros materiais": desde
que a apostila deixou de ser obrigatória, é comum a análise partir de um
"Desafio Profissional" ou de um "Reflita sobre a seguinte situação" — e o
desafio deles também tem que ser encontrado e resolvido. ``merge_insights``
junta o que cada documento encontrou.
"""

from __future__ import annotations

from study_assistant.application.ai_caller import ProgressFn, ResilientAICaller
from study_assistant.application.ai_json_utils import ai_text
from study_assistant.application.apostila_heuristics import extract_sections_heuristically
from study_assistant.application.text_batches import split_into_batches
from study_assistant.config.prompts import build_batch_extraction_prompt
from study_assistant.domain.entities import (
    SECTION_SUBHEADING_PREFIX,
    ApostilaInsights,
    ExtractedSection,
    ExtractionMethod,
)

_SECTION_LABELS: dict[str, str] = {
    "referencias_bibliograficas": "Referências Bibliográficas",
    "dicas_leitura": "Dicas/Indicações de Leitura",
    "desafio_pratico": "Desafio Prático (e norte para a resolução)",
}


class ExtractApostilaInsightsUseCase:
    def __init__(
        self, ai_caller: ResilientAICaller, *, batch_chars: int = 12_000, max_chars: int = 200_000
    ) -> None:
        self._ai_caller = ai_caller
        self._batch_chars = batch_chars
        self._max_chars = max_chars

    def execute(
        self,
        text: str,
        *,
        progress: ProgressFn | None = None,
        location: str = "na apostila",
        is_apostila: bool = True,
    ) -> ApostilaInsights:
        """``location`` só aparece nas mensagens de andamento ("na apostila",
        'em "desafio.pdf"'); ``is_apostila`` diz à IA que tipo de documento
        ela está lendo."""
        heuristic_hits = extract_sections_heuristically(text)

        sections: dict[str, ExtractedSection] = {
            key: ExtractedSection(content=heuristic_hits[key], method=ExtractionMethod.HEURISTICA)
            for key in _SECTION_LABELS
            if key in heuristic_hits
        }
        missing = {key: label for key, label in _SECTION_LABELS.items() if key not in sections}
        if missing:
            found_by_ai = self._extract_with_ai(text, missing, progress, location, is_apostila)
            for key in missing:
                content = "\n\n".join(found_by_ai[key])
                sections[key] = ExtractedSection(
                    content=content,
                    method=ExtractionMethod.IA if content else ExtractionMethod.NAO_ENCONTRADO,
                )

        return ApostilaInsights(
            referencias_bibliograficas=sections["referencias_bibliograficas"],
            dicas_leitura=sections["dicas_leitura"],
            desafio_pratico=sections["desafio_pratico"],
            from_apostila=is_apostila,
        )

    def _extract_with_ai(
        self,
        text: str,
        missing: dict[str, str],
        progress: ProgressFn | None,
        location: str,
        is_apostila: bool,
    ) -> dict[str, list[str]]:
        found: dict[str, list[str]] = {key: [] for key in missing}
        batches = split_into_batches(text[: self._max_chars], self._batch_chars)
        total = len(batches)
        for number, batch in enumerate(batches, start=1):
            label = f"Procurando referências, dicas e desafio {location}"
            if total > 1:
                label += f" — parte {number} de {total}"
            result = self._ai_caller.call_json(
                build_batch_extraction_prompt(
                    sections=missing,
                    part_number=number,
                    part_count=total,
                    text=batch,
                    document_kind="uma apostila" if is_apostila else "um material de estudo",
                ),
                required_keys=tuple(missing),
                label=label,
                progress=progress,
            )
            for key in missing:
                content = ai_text(result.data.get(key))
                if content:
                    found[key].append(content)
            if progress:
                progress(f"✅ {label}{' (já estava salva)' if result.from_saved else ''}", done=True)
        return found


def merge_insights(
    parts: list[tuple[str, ApostilaInsights]], *, from_apostila: bool
) -> ApostilaInsights | None:
    """Junta o que cada documento encontrou (``parts``: nome do documento e
    o que foi extraído dele), seção por seção.

    Um documento só: volta como está (com apostila, é exatamente o
    comportamento de antes). Mais de um contribuindo pra mesma seção: cada
    trecho vai com o nome do arquivo de onde saiu. Sem apostila e sem nada
    encontrado em lugar nenhum: None — a análise sai sem essas seções.
    """
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0][1] if (from_apostila or not _nothing_found(parts[0][1])) else None

    merged: dict[str, ExtractedSection] = {}
    for key in _SECTION_LABELS:
        found = [
            (name, getattr(insights, key))
            for name, insights in parts
            if getattr(insights, key).method != ExtractionMethod.NAO_ENCONTRADO
        ]
        if not found:
            merged[key] = ExtractedSection(content="", method=ExtractionMethod.NAO_ENCONTRADO)
        elif len(found) == 1:
            merged[key] = found[0][1]
        else:
            merged[key] = ExtractedSection(
                # Nome do arquivo como subtítulo (mesmo marcador das "Parte X
                # de Y" da análise): no PDF sai destacado, numa linha própria.
                content="\n\n".join(
                    f"{SECTION_SUBHEADING_PREFIX}{name}\n{section.content}" for name, section in found
                ),
                method=(
                    ExtractionMethod.IA
                    if any(section.method == ExtractionMethod.IA for _, section in found)
                    else ExtractionMethod.HEURISTICA
                ),
            )

    result = ApostilaInsights(
        referencias_bibliograficas=merged["referencias_bibliograficas"],
        dicas_leitura=merged["dicas_leitura"],
        desafio_pratico=merged["desafio_pratico"],
        from_apostila=from_apostila,
    )
    return None if not from_apostila and _nothing_found(result) else result


def _nothing_found(insights: ApostilaInsights) -> bool:
    return all(
        getattr(insights, key).method == ExtractionMethod.NAO_ENCONTRADO for key in _SECTION_LABELS
    )

"""Caso de uso: extrair da apostila as referências bibliográficas, as dicas
de leitura e o desafio prático (itens 3, 4 e 5 do fluxo manual original).

Estratégia em duas camadas, do mais barato para o mais caro:
1. Heurística por cabeçalhos (``apostila_heuristics``) — instantânea, sem
   custo de API.
2. Se a heurística não encontrar alguma seção, a apostila é lida pela IA em
   lotes (os mesmos da análise, ~12 mil caracteres cada), com UMA chamada
   por lote pedindo todas as seções que faltam de uma vez. Antes eram até 3
   chamadas com 40 mil caracteres cada — o que sozinho já estourava a cota
   por minuto das IAs gratuitas.

O que cada lote encontra é juntado, em ordem (dicas de leitura, por
exemplo, costumam vir espalhadas pela apostila inteira).
"""

from __future__ import annotations

from study_assistant.application.ai_caller import ProgressFn, ResilientAICaller
from study_assistant.application.apostila_heuristics import extract_sections_heuristically
from study_assistant.application.text_batches import split_into_batches
from study_assistant.config.prompts import build_batch_extraction_prompt
from study_assistant.domain.entities import ApostilaInsights, ExtractedSection, ExtractionMethod

_SECTION_LABELS: dict[str, str] = {
    "referencias_bibliograficas": "Referências Bibliográficas",
    "dicas_leitura": "Dicas/Indicações de Leitura",
    "desafio_pratico": "Desafio Prático (e norte para a resolução)",
}


class ExtractApostilaInsightsUseCase:
    def __init__(
        self, ai_caller: ResilientAICaller, *, batch_chars: int = 12_000, max_chars: int = 120_000
    ) -> None:
        self._ai_caller = ai_caller
        self._batch_chars = batch_chars
        self._max_chars = max_chars

    def execute(self, apostila_text: str, *, progress: ProgressFn | None = None) -> ApostilaInsights:
        heuristic_hits = extract_sections_heuristically(apostila_text)

        sections: dict[str, ExtractedSection] = {
            key: ExtractedSection(content=heuristic_hits[key], method=ExtractionMethod.HEURISTICA)
            for key in _SECTION_LABELS
            if key in heuristic_hits
        }
        missing = {key: label for key, label in _SECTION_LABELS.items() if key not in sections}
        if missing:
            found_by_ai = self._extract_with_ai(apostila_text, missing, progress)
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
        )

    def _extract_with_ai(
        self, apostila_text: str, missing: dict[str, str], progress: ProgressFn | None
    ) -> dict[str, list[str]]:
        found: dict[str, list[str]] = {key: [] for key in missing}
        batches = split_into_batches(apostila_text[: self._max_chars], self._batch_chars)
        total = len(batches)
        for number, batch in enumerate(batches, start=1):
            label = (
                f"Procurando referências, dicas e desafio na apostila — parte {number} de {total}"
                if total > 1
                else "Procurando referências, dicas e desafio na apostila"
            )
            result = self._ai_caller.call_json(
                build_batch_extraction_prompt(
                    sections=missing, part_number=number, part_count=total, text=batch
                ),
                required_keys=tuple(missing),
                label=label,
                progress=progress,
            )
            for key in missing:
                content = str(result.data.get(key) or "").strip()
                if content:
                    found[key].append(content)
            if progress:
                progress(f"✅ {label}{' (já estava salva)' if result.from_saved else ''}", done=True)
        return found

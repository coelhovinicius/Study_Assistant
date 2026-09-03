"""Caso de uso: extrair da apostila as referências bibliográficas, as dicas
de leitura e o desafio prático (itens 3, 4 e 5 do fluxo manual original).

Estratégia em duas camadas, do mais barato para o mais caro:
1. Heurística por cabeçalhos (``apostila_heuristics``) — instantânea, sem
   custo de API.
2. Se a heurística não encontrar uma seção com confiança, cai para uma
   chamada de IA dedicada e pequena, pedindo só aquele trecho específico
   (reaproveita o mesmo ``AIProvider``/cascata usado na análise final).

Isso é intencionalmente independente da análise completa (item 6): mesmo
que a análise final falhe por algum motivo, as extrações já feitas aqui
não se perdem.
"""

from __future__ import annotations

from study_assistant.application.ai_json_utils import parse_json_response
from study_assistant.application.apostila_heuristics import extract_sections_heuristically
from study_assistant.config.prompts import build_section_extraction_prompt
from study_assistant.domain.entities import ApostilaInsights, ExtractedSection, ExtractionMethod
from study_assistant.domain.exceptions import (
    AIProviderError,
    AllProvidersFailedError,
    InvalidAIResponseError,
)
from study_assistant.domain.ports import AIProvider

_SECTION_LABELS: dict[str, str] = {
    "referencias_bibliograficas": "Referências Bibliográficas",
    "dicas_leitura": "Dicas/Indicações de Leitura",
    "desafio_pratico": "Desafio Prático (e norte para a resolução)",
}

# Evita mandar apostilas gigantescas repetidas vezes para a IA de extração;
# a análise completa (item 6) ainda recebe o texto completo.
_MAX_CHARS_FOR_EXTRACTION_FALLBACK = 40_000


class ExtractApostilaInsightsUseCase:
    def __init__(self, ai_provider: AIProvider) -> None:
        self._ai_provider = ai_provider

    def execute(self, apostila_text: str) -> ApostilaInsights:
        heuristic_hits = extract_sections_heuristically(apostila_text)

        sections: dict[str, ExtractedSection] = {}
        for key, label in _SECTION_LABELS.items():
            if key in heuristic_hits:
                sections[key] = ExtractedSection(
                    content=heuristic_hits[key], method=ExtractionMethod.HEURISTICA
                )
            else:
                sections[key] = self._extract_with_ai_fallback(key, label, apostila_text)

        return ApostilaInsights(
            referencias_bibliograficas=sections["referencias_bibliograficas"],
            dicas_leitura=sections["dicas_leitura"],
            desafio_pratico=sections["desafio_pratico"],
        )

    def _extract_with_ai_fallback(
        self, key: str, label: str, apostila_text: str
    ) -> ExtractedSection:
        truncated_text = apostila_text[:_MAX_CHARS_FOR_EXTRACTION_FALLBACK]
        prompt = build_section_extraction_prompt(section_label=label, apostila_text=truncated_text)

        try:
            raw_response = self._ai_provider.generate(prompt, response_format="json")
            data = parse_json_response(raw_response)
        except (AIProviderError, AllProvidersFailedError, InvalidAIResponseError):
            return ExtractedSection(content="", method=ExtractionMethod.NAO_ENCONTRADO)

        content = str(data.get("conteudo") or "").strip()
        if data.get("encontrado") and content:
            return ExtractedSection(content=content, method=ExtractionMethod.IA)
        return ExtractedSection(content="", method=ExtractionMethod.NAO_ENCONTRADO)

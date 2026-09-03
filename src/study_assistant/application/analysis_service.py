"""Caso de uso: análise expandida final, dividida por assunto, e resolução
do desafio prático (itens 6, 9 e 10 do fluxo original do usuário).

Depende do orquestrador de cascata (não só de um ``AIProvider`` genérico)
porque o relatório final precisa registrar qual provedor efetivamente
respondeu e quais falharam antes — essa transparência é parte do que o
usuário pediu ao mostrar o fluxo de fallback em n8n.
"""

from __future__ import annotations

from study_assistant.application.ai_json_utils import parse_json_response
from study_assistant.config.prompts import build_analysis_prompt
from study_assistant.domain.entities import (
    ANALYSIS_SECTION_ORDER,
    AnalysisResult,
    ApostilaInsights,
    ExtractionMethod,
    Material,
    MaterialType,
)
from study_assistant.domain.exceptions import InvalidAIResponseError
from study_assistant.infrastructure.ai_providers.cascade import AIProviderCascade

_MATERIAL_TYPE_LABELS: dict[MaterialType, str] = {
    MaterialType.APOSTILA: "Apostila",
    MaterialType.LIVRO: "Livro",
    MaterialType.AUDIODESCRICAO_PODCAST: "Audiodescrição do Podcast",
    MaterialType.OUTRO: "Outro material",
}

_INSIGHT_LABELS: dict[str, str] = {
    "referencias_bibliograficas": "Referências Bibliográficas",
    "dicas_leitura": "Dicas/Indicações de Leitura",
    "desafio_pratico": "Desafio Prático",
}

# Limite de segurança para não estourar a janela de contexto dos modelos
# menores da cascata (ex: modelos Groq). Ajuste conforme necessário.
_MAX_CHARS_FOR_MATERIALS_CONTEXT = 120_000


class AnalyzeStudyMaterialsUseCase:
    def __init__(self, ai_cascade: AIProviderCascade) -> None:
        self._ai_cascade = ai_cascade

    def execute(self, materials: list[Material], insights: ApostilaInsights) -> AnalysisResult:
        prompt = build_analysis_prompt(
            materials_context=self._build_materials_context(materials),
            insights_context=self._build_insights_context(insights),
        )

        run_result = self._ai_cascade.generate_with_details(prompt, response_format="json")

        try:
            raw_sections = parse_json_response(run_result.text)
        except InvalidAIResponseError:
            # Não descarta a resposta da IA só porque o JSON veio malformado:
            # guarda o texto bruto na síntese geral pra não perder o trabalho.
            raw_sections = {"sintese_geral": run_result.text}

        normalized_sections = {
            key: str(raw_sections.get(key, "")).strip() for key in ANALYSIS_SECTION_ORDER
        }

        return AnalysisResult(
            sections=normalized_sections,
            generated_by_provider=run_result.provider_name,
            generated_by_model=run_result.model,
            provider_attempts=run_result.attempts,
        )

    @staticmethod
    def _build_materials_context(materials: list[Material]) -> str:
        parts = []
        for material in materials:
            label = _MATERIAL_TYPE_LABELS.get(material.material_type, material.material_type.value)
            parts.append(
                f"===== INÍCIO DO DOCUMENTO: {material.filename} (TIPO: {label}) =====\n"
                f"{material.raw_text}\n"
                f"===== FIM DO DOCUMENTO: {material.filename} =====\n"
            )
        context = "\n".join(parts)

        if len(context) > _MAX_CHARS_FOR_MATERIALS_CONTEXT:
            context = (
                context[:_MAX_CHARS_FOR_MATERIALS_CONTEXT]
                + "\n\n[... conteúdo truncado por limite de tamanho ...]"
            )
        return context

    @staticmethod
    def _build_insights_context(insights: ApostilaInsights) -> str:
        pairs = (
            ("referencias_bibliograficas", insights.referencias_bibliograficas),
            ("dicas_leitura", insights.dicas_leitura),
            ("desafio_pratico", insights.desafio_pratico),
        )
        lines = []
        for key, section in pairs:
            label = _INSIGHT_LABELS[key]
            if section.method == ExtractionMethod.NAO_ENCONTRADO:
                lines.append(f"- {label}: não encontrado(a) no material enviado.")
            else:
                lines.append(f"- {label}:\n{section.content}")
        return "\n\n".join(lines)

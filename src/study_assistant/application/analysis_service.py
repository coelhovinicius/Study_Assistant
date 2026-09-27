"""Caso de uso: análise expandida final, dividida por assunto, e resolução
do desafio prático (itens 6, 9 e 10 do fluxo original do usuário).

Feita em lotes, pra caber na cota por minuto das IAs gratuitas (ver
``ai_caller.py``) — mas o resultado continua sendo UMA análise, com as
mesmas 8 seções de sempre, num PDF só:

1. cada material é dividido em lotes de ~12 mil caracteres (sempre entre
   parágrafos) e cada lote recebe sua análise detalhada, um título curto e
   um resumo curto;
2. a seção de cada material (apostila, livro, podcast, outros) junta as
   análises dos seus lotes em ordem, cada uma sob um subtítulo "Parte X de
   Y — título" — material de um lote só não ganha subtítulo;
3. as 4 seções finais (referências, dicas, desafio, síntese) saem de
   chamadas pequenas, feitas a partir dos trechos extraídos da apostila e
   dos resumos curtos de cada lote.

Nenhum lote fica sem análise: se a IA falhar num lote mesmo depois das
retentativas, a análise pausa (``AnalysisPausedError``) e, ao continuar,
os lotes já respondidos voltam do banco sem nova chamada à IA.
"""

from __future__ import annotations

from dataclasses import dataclass

from study_assistant.application.ai_caller import AICallResult, ProgressFn, ResilientAICaller
from study_assistant.application.ai_json_utils import ai_text
from study_assistant.application.text_batches import split_into_batches
from study_assistant.config.prompts import (
    BATCH_ANALYSIS_KEYS,
    build_batch_analysis_prompt,
    build_challenge_prompt,
    build_reading_tips_prompt,
    build_references_prompt,
    build_synthesis_prompt,
)
from study_assistant.domain.entities import (
    ANALYSIS_SECTION_ORDER,
    SECTION_SUBHEADING_PREFIX,
    AnalysisResult,
    ApostilaInsights,
    ExtractedSection,
    ExtractionMethod,
    Material,
    MaterialType,
)

_MATERIAL_TYPE_LABELS: dict[MaterialType, str] = {
    MaterialType.APOSTILA: "Apostila",
    MaterialType.LIVRO: "Livro",
    MaterialType.AUDIODESCRICAO_PODCAST: "Audiodescrição do Podcast",
    MaterialType.OUTRO: "Outro material",
}

_MATERIAL_SECTION_KEYS: dict[MaterialType, str] = {
    MaterialType.APOSTILA: "analise_apostila",
    MaterialType.LIVRO: "analise_livro",
    MaterialType.AUDIODESCRICAO_PODCAST: "analise_podcast",
    MaterialType.OUTRO: "analise_outros_materiais",
}

# O que o prompt original pedia de cada tipo de material, agora por lote.
_MATERIAL_FOCUS: dict[MaterialType, str] = {
    MaterialType.APOSTILA: (
        "resumo aprofundado, conceitos-chave, pontos de atenção e conexões entre os temas."
    ),
    MaterialType.LIVRO: (
        "os conceitos que o livro traz para complementar a apostila da disciplina — "
        "aprofunde o que é próprio do livro."
    ),
    MaterialType.AUDIODESCRICAO_PODCAST: (
        "as principais ideias do podcast e como elas se relacionam com o conteúdo da disciplina."
    ),
    MaterialType.OUTRO: (
        "as principais ideias deste material e como elas se relacionam com o conteúdo da disciplina."
    ),
}

# Quem entra primeiro no limite de caracteres por análise. Antes era a
# ordem de envio (apostila, livros, podcast): numa análise real do usuário,
# os dois livros da disciplina (~158 mil caracteres) gastaram o limite e o
# podcast — curto e central pra aula — ficou de fora. Livros vão por
# último: são opcionais, complementares e, de longe, os maiores.
_BUDGET_PRIORITY: dict[MaterialType, int] = {
    MaterialType.APOSTILA: 0,
    MaterialType.AUDIODESCRICAO_PODCAST: 1,
    MaterialType.OUTRO: 2,
    MaterialType.LIVRO: 3,
}

# Seção final sem o trecho correspondente na apostila: vai uma frase fixa,
# sem gastar uma chamada de IA só pra ela dizer que não há o que analisar.
_NOT_FOUND_NOTES: dict[str, str] = {
    "analise_referencias_bibliograficas": "Não foram encontradas referências bibliográficas na apostila enviada.",
    "analise_dicas_leitura": "Não foram encontradas dicas ou indicações de leitura na apostila enviada.",
    "analise_e_resolucao_desafio": "Não foi encontrado um desafio prático na apostila enviada.",
}


def _format_count(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def _cap(text: str, limit: int) -> str:
    """Trechos extraídos da apostila vão inteiros pras seções finais, a não
    ser que passem do tamanho de um lote (ex: uma heurística que pegou do
    cabeçalho "Referências" até o fim do arquivo)."""
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "\n[... texto cortado por tamanho ...]"


@dataclass(frozen=True)
class _Batch:
    material: Material
    number: int
    total: int
    text: str


@dataclass(frozen=True)
class _BatchAnalysis:
    batch: _Batch
    title: str
    analysis: str
    summary: str


@dataclass(frozen=True)
class _FinalCall:
    section_key: str
    description: str
    prompt: str


class AnalyzeStudyMaterialsUseCase:
    def __init__(
        self,
        ai_caller: ResilientAICaller,
        *,
        batch_chars: int = 12_000,
        max_total_chars: int = 200_000,
    ) -> None:
        self._ai_caller = ai_caller
        self._batch_chars = batch_chars
        self._max_total_chars = max_total_chars

    def execute(
        self,
        materials: list[Material],
        insights: ApostilaInsights,
        *,
        progress: ProgressFn | None = None,
    ) -> AnalysisResult:
        batches, notes = self._plan(materials)
        multi_file_types = self._types_with_several_files(batches)

        # As 4 chamadas finais só dependem dos lotes, então dá pra saber o
        # total de etapas antes de começar — "etapa 3 de 12" na tela.
        final_steps = sum(1 for s in self._final_sources(insights).values() if s is not None)
        total_steps = len(batches) + final_steps + (1 if batches else 0)
        step = 0

        results: list[AICallResult] = []
        analyses: list[_BatchAnalysis] = []
        for batch in batches:
            step += 1
            label = f"Etapa {step} de {total_steps}: {self._batch_label(batch, multi_file_types)}"
            result = self._ai_caller.call_json(
                build_batch_analysis_prompt(
                    material_label=_MATERIAL_TYPE_LABELS[batch.material.material_type],
                    filename=batch.material.filename,
                    focus=_MATERIAL_FOCUS[batch.material.material_type],
                    part_number=batch.number,
                    part_count=batch.total,
                    text=batch.text,
                ),
                required_keys=BATCH_ANALYSIS_KEYS,
                label=label,
                progress=progress,
            )
            results.append(result)
            analyses.append(
                _BatchAnalysis(
                    batch=batch,
                    title=ai_text(result.data.get("titulo")),
                    analysis=ai_text(result.data.get("analise")),
                    summary=ai_text(result.data.get("resumo")),
                )
            )
            _report_done(progress, label, result)

        sections = {key: "" for key in ANALYSIS_SECTION_ORDER}
        for material_type, section_key in _MATERIAL_SECTION_KEYS.items():
            sections[section_key] = self._assemble_material_section(
                material_type, materials, analyses, notes, multi_file_types
            )

        for final_call in self._final_calls(insights, analyses, multi_file_types):
            if final_call.prompt == "":
                sections[final_call.section_key] = _NOT_FOUND_NOTES.get(final_call.section_key, "")
                continue
            step += 1
            label = f"Etapa {step} de {total_steps}: {final_call.description}"
            result = self._ai_caller.call_json(
                final_call.prompt,
                required_keys=(final_call.section_key,),
                label=label,
                progress=progress,
            )
            results.append(result)
            sections[final_call.section_key] = ai_text(result.data.get(final_call.section_key))
            _report_done(progress, label, result)

        return AnalysisResult(
            sections=sections,
            generated_by_provider=", ".join(dict.fromkeys(r.provider_name for r in results if r.provider_name)),
            generated_by_model=", ".join(dict.fromkeys(r.model for r in results if r.model)),
            provider_attempts=tuple(attempt for r in results for attempt in r.attempts),
        )

    def _plan(self, materials: list[Material]) -> tuple[list[_Batch], dict[str, str]]:
        """Lotes de cada material, dentro do limite total de caracteres por
        análise, repartido por prioridade (``_BUDGET_PRIORITY``): apostila,
        podcast e outros materiais primeiro, livros por último. O que passa
        do limite não some calado: vira uma observação no fim da seção."""
        remaining = self._max_total_chars
        batches: list[_Batch] = []
        notes: dict[str, str] = {}
        for material in sorted(materials, key=lambda m: _BUDGET_PRIORITY[m.material_type]):
            text = material.raw_text.strip()
            taken = text[: max(remaining, 0)]
            remaining -= len(taken)
            cut = len(text) - len(taken)
            if cut and taken:
                notes[material.id] = (
                    f'Observação: "{material.filename}" passou do limite de '
                    f"{_format_count(self._max_total_chars)} caracteres por análise — os últimos "
                    f"{_format_count(cut)} caracteres não foram analisados."
                )
            elif cut:
                notes[material.id] = (
                    f'Observação: "{material.filename}" não foi analisado — o limite de '
                    f"{_format_count(self._max_total_chars)} caracteres por análise já tinha sido "
                    "usado pelos materiais anteriores."
                )
            parts = split_into_batches(taken, self._batch_chars)
            batches.extend(
                _Batch(material=material, number=number, total=len(parts), text=part)
                for number, part in enumerate(parts, start=1)
            )
        return batches, notes

    @staticmethod
    def _types_with_several_files(batches: list[_Batch]) -> set[MaterialType]:
        files_by_type: dict[MaterialType, set[str]] = {}
        for batch in batches:
            files_by_type.setdefault(batch.material.material_type, set()).add(batch.material.id)
        return {material_type for material_type, ids in files_by_type.items() if len(ids) > 1}

    @staticmethod
    def _batch_label(batch: _Batch, multi_file_types: set[MaterialType]) -> str:
        label = _MATERIAL_TYPE_LABELS[batch.material.material_type]
        if batch.material.material_type in multi_file_types:
            label += f" ({batch.material.filename})"
        if batch.total > 1:
            label += f", parte {batch.number} de {batch.total}"
        return label

    @staticmethod
    def _part_heading(item: _BatchAnalysis, multi_file_types: set[MaterialType]) -> str:
        pieces = []
        if item.batch.material.material_type in multi_file_types:
            pieces.append(item.batch.material.filename)
        if item.batch.total > 1:
            pieces.append(f"Parte {item.batch.number} de {item.batch.total}")
        if item.title:
            pieces.append(item.title)
        return " — ".join(pieces)

    def _assemble_material_section(
        self,
        material_type: MaterialType,
        materials: list[Material],
        analyses: list[_BatchAnalysis],
        notes: dict[str, str],
        multi_file_types: set[MaterialType],
    ) -> str:
        blocks: list[str] = []
        for material in materials:
            if material.material_type is not material_type:
                continue
            for item in (a for a in analyses if a.batch.material.id == material.id):
                if item.batch.total == 1 and material_type not in multi_file_types:
                    blocks.append(item.analysis)
                else:
                    heading = self._part_heading(item, multi_file_types)
                    blocks.append(f"{SECTION_SUBHEADING_PREFIX}{heading}\n{item.analysis}")
            if material.id in notes:
                blocks.append(notes[material.id])
        return "\n\n".join(block for block in blocks if block.strip())

    @staticmethod
    def _final_sources(insights: ApostilaInsights) -> dict[str, ExtractedSection | None]:
        """Trecho da apostila de cada seção final — None quando não foi
        encontrado (a seção sai com uma frase fixa, sem chamar a IA). A
        síntese não depende de trecho nenhum, só dos resumos."""

        def found(section: ExtractedSection) -> ExtractedSection | None:
            if section.method == ExtractionMethod.NAO_ENCONTRADO or not section.content.strip():
                return None
            return section

        return {
            "analise_referencias_bibliograficas": found(insights.referencias_bibliograficas),
            "analise_dicas_leitura": found(insights.dicas_leitura),
            "analise_e_resolucao_desafio": found(insights.desafio_pratico),
        }

    def _final_calls(
        self,
        insights: ApostilaInsights,
        analyses: list[_BatchAnalysis],
        multi_file_types: set[MaterialType],
    ) -> list[_FinalCall]:
        topics = "\n".join(
            f"- {self._batch_label(a.batch, multi_file_types)}: {a.title or '(sem título)'}"
            for a in analyses
        )
        summaries = _cap(
            "\n\n".join(
                f"[{self._batch_label(a.batch, multi_file_types)} — {a.title or 'sem título'}]\n{a.summary}"
                for a in analyses
            ),
            self._batch_chars * 2,
        )
        sources = self._final_sources(insights)
        references = sources["analise_referencias_bibliograficas"]
        tips = sources["analise_dicas_leitura"]
        challenge = sources["analise_e_resolucao_desafio"]

        # prompt "" = trecho não encontrado na apostila (ver _NOT_FOUND_NOTES)
        calls = [
            _FinalCall(
                "analise_referencias_bibliograficas",
                "analisando as referências bibliográficas",
                build_references_prompt(references_text=_cap(references.content, self._batch_chars), topics=topics)
                if references
                else "",
            ),
            _FinalCall(
                "analise_dicas_leitura",
                "analisando as dicas de leitura",
                build_reading_tips_prompt(tips_text=_cap(tips.content, self._batch_chars), topics=topics)
                if tips
                else "",
            ),
            _FinalCall(
                "analise_e_resolucao_desafio",
                "resolvendo o desafio prático",
                build_challenge_prompt(challenge_text=_cap(challenge.content, self._batch_chars), summaries=summaries)
                if challenge
                else "",
            ),
        ]
        if analyses:
            calls.append(
                _FinalCall("sintese_geral", "escrevendo a síntese geral", build_synthesis_prompt(summaries=summaries))
            )
        return calls


def _report_done(progress: ProgressFn | None, label: str, result: AICallResult) -> None:
    if progress:
        suffix = " (já estava salva — sem nova chamada à IA)" if result.from_saved else ""
        progress(f"✅ {label}{suffix}", done=True)

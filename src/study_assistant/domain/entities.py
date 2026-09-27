"""Entidades e objetos de valor do domínio.

Todas as classes aqui são simples (dataclasses), imutáveis quando possível,
e não sabem nada sobre Streamlit, Turso, PDFs ou APIs de IA. Isso é o que
torna o domínio fácil de testar e de reaproveitar caso a interface (hoje
Streamlit) mude no futuro.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


class MaterialType(str, Enum):
    """Tipo de material de estudo, conforme o fluxo manual descrito pelo usuário."""

    APOSTILA = "apostila"
    LIVRO = "livro"
    AUDIODESCRICAO_PODCAST = "audiodescricao_podcast"
    OUTRO = "outro"


class SourceFormat(str, Enum):
    """Formato de origem do arquivo enviado."""

    PDF = "pdf"
    TXT = "txt"
    DOCX = "docx"


class ExtractionMethod(str, Enum):
    """Como um trecho (referências, dicas, desafio) foi extraído da apostila."""

    HEURISTICA = "heuristica"
    IA = "ia"
    NAO_ENCONTRADO = "nao_encontrado"


@dataclass(frozen=True)
class Material:
    """Um arquivo enviado pelo usuário (apostila, livro, podcast, outro)."""

    filename: str
    material_type: MaterialType
    source_format: SourceFormat
    raw_text: str
    id: str = field(default_factory=_new_id)
    uploaded_at: datetime = field(default_factory=_now)

    @property
    def char_count(self) -> int:
        return len(self.raw_text)


@dataclass(frozen=True)
class ExtractedSection:
    """Um trecho extraído da apostila (referências, dicas ou desafio)."""

    content: str
    method: ExtractionMethod


@dataclass(frozen=True)
class ApostilaInsights:
    """Os três itens que hoje o usuário extrai manualmente da apostila."""

    referencias_bibliograficas: ExtractedSection
    dicas_leitura: ExtractedSection
    desafio_pratico: ExtractedSection

    @property
    def is_complete(self) -> bool:
        return all(
            section.method != ExtractionMethod.NAO_ENCONTRADO
            for section in (
                self.referencias_bibliograficas,
                self.dicas_leitura,
                self.desafio_pratico,
            )
        )


@dataclass(frozen=True)
class ProviderAttempt:
    """Registro de uma tentativa de chamada a um provedor de IA na cascata."""

    provider_name: str
    model: str
    success: bool
    duration_ms: float
    error_message: str | None = None
    attempted_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class SavedAIResponse:
    """Uma resposta da IA já recebida e guardada, pra não ter que pedir de
    novo o mesmo lote (ver ``AIResponseStore``)."""

    text: str
    provider_name: str
    model: str


# Linha que abre uma subdivisão dentro de uma seção da análise (ex: "###
# Parte 2 de 4 — Direitos Fundamentais", uma por lote do material). Mesmo
# prefixo de título do markdown, então a tela já mostra como subtítulo; os
# geradores de PDF/DOCX reconhecem esse prefixo e fazem o mesmo.
SECTION_SUBHEADING_PREFIX = "### "


# Ordem e nomes das seções do relatório final, na ordem em que devem
# aparecer no documento entregue ao usuário (item 6.1 do fluxo original).
ANALYSIS_SECTION_ORDER: tuple[str, ...] = (
    "analise_apostila",
    "analise_livro",
    "analise_podcast",
    "analise_outros_materiais",
    "analise_referencias_bibliograficas",
    "analise_dicas_leitura",
    "analise_e_resolucao_desafio",
    "sintese_geral",
)

ANALYSIS_SECTION_TITLES: dict[str, str] = {
    "analise_apostila": "Análise da Apostila",
    "analise_livro": "Análise do Livro",
    "analise_podcast": "Análise do Podcast (Audiodescrição)",
    "analise_outros_materiais": "Análise de Outros Materiais",
    "analise_referencias_bibliograficas": "Análise das Referências Bibliográficas",
    "analise_dicas_leitura": "Análise das Dicas/Indicações de Leitura",
    "analise_e_resolucao_desafio": "Análise e Resolução do Desafio Prático",
    "sintese_geral": "Síntese Geral",
}


@dataclass(frozen=True)
class AnalysisResult:
    """Resultado final da análise expandida feita pela IA (item 6 do fluxo)."""

    sections: dict[str, str]
    generated_by_provider: str
    generated_by_model: str
    provider_attempts: tuple[ProviderAttempt, ...]
    generated_at: datetime = field(default_factory=_now)

    def ordered_sections(self) -> list[tuple[str, str]]:
        """Retorna (título, conteúdo) na ordem de exibição, pulando seções vazias."""
        result = []
        for key in ANALYSIS_SECTION_ORDER:
            content = self.sections.get(key, "").strip()
            if content:
                result.append((ANALYSIS_SECTION_TITLES.get(key, key), content))
        return result


@dataclass
class StudySession:
    """Agregado raiz: uma "rodada" completa do fluxo, do upload ao resultado final."""

    title: str
    materials: list[Material]
    apostila_insights: ApostilaInsights | None = None
    analysis_result: AnalysisResult | None = None
    id: str = field(default_factory=_new_id)
    created_at: datetime = field(default_factory=_now)
    saved: bool = False
    # Preenchidos só por TursoSessionRepository.get(), e só quando a sessão
    # foi salva DEPOIS da mudança pra o histórico guardar somente o PDF
    # (não mais materiais/análise estruturada). Uma sessão recém-analisada
    # (ainda não salva) ou uma salva ANTES dessa mudança (legado, ainda
    # reconstruída a partir de materiais + análise) nunca tem isto
    # preenchido — ver comentário em session_repository.py:get().
    stored_pdf_bytes: bytes | None = None
    stored_pdf_filename: str | None = None

    def material_by_type(self, material_type: MaterialType) -> list[Material]:
        return [m for m in self.materials if m.material_type is material_type]


@dataclass(frozen=True)
class AdminUser:
    """O único usuário administrador do app (uso pessoal)."""

    username: str
    password_hash: str
    id: str = field(default_factory=_new_id)
    created_at: datetime = field(default_factory=_now)
    failed_login_attempts: int = 0
    locked_until: datetime | None = None

    def is_locked(self, now: datetime | None = None) -> bool:
        if self.locked_until is None:
            return False
        return (now or _now()) < self.locked_until

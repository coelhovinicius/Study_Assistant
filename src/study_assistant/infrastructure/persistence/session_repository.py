"""Repositório do histórico de sessões de estudo, persistido no Turso.

Só é usado quando o usuário decide explicitamente "salvar" o resultado de
uma rodada de análise (ver ``application/history_service.py``) — o app
funciona normalmente sem nunca gravar nada aqui, se o usuário preferir.
"""

from __future__ import annotations

import gzip
import json

from study_assistant.domain.entities import (
    AnalysisResult,
    ApostilaInsights,
    ExtractedSection,
    ExtractionMethod,
    Material,
    MaterialType,
    ProviderAttempt,
    SourceFormat,
    StudySession,
)
from study_assistant.domain.ports import SessionRepository
from study_assistant.infrastructure.persistence.datetime_utils import from_iso, to_iso
from study_assistant.infrastructure.persistence.turso_client import TursoHttpClient


def _section_to_dict(section: ExtractedSection) -> dict:
    return {"content": section.content, "method": section.method.value}


def _section_from_dict(data: dict | None) -> ExtractedSection:
    data = data or {}
    return ExtractedSection(
        content=data.get("content", ""),
        method=ExtractionMethod(data.get("method", ExtractionMethod.NAO_ENCONTRADO.value)),
    )


def _insights_to_json(insights: ApostilaInsights | None) -> str | None:
    if insights is None:
        return None
    return json.dumps(
        {
            "referencias_bibliograficas": _section_to_dict(insights.referencias_bibliograficas),
            "dicas_leitura": _section_to_dict(insights.dicas_leitura),
            "desafio_pratico": _section_to_dict(insights.desafio_pratico),
        },
        ensure_ascii=False,
    )


_GZIP_MAGIC = b"\x1f\x8b"


def _compress_pdf(pdf_bytes: bytes) -> bytes:
    # A causa real do "Ver/baixar" falhando com blob truncado (investigada
    # a fundo com scripts/diagnosticar_leitura_pdf.py) não era tamanho —
    # era o Turso devolvendo o base64 sem o padding final, já corrigido
    # direto em turso_client.py (_pad_base64). Compressão não resolvia
    # aquilo (aliás continuou falhando depois dela ter sido adicionada) e
    # continua aqui só pelo motivo original, independente do bug: reduzir
    # o volume de dados que trafega e fica guardado — testado com um PDF
    # real gerado por este app: ~45-50% menor.
    return gzip.compress(pdf_bytes, compresslevel=6)


def _decompress_pdf(stored: bytes) -> bytes:
    # Compatível com as sessões já salvas ANTES dessa mudança (sem gzip):
    # só tenta descomprimir se os bytes realmente começam com a assinatura
    # gzip; qualquer coisa diferente disso (ou uma descompressão que falha)
    # é tratada como um PDF cru mesmo, sem quebrar a leitura.
    if stored[:2] == _GZIP_MAGIC:
        try:
            return gzip.decompress(stored)
        except OSError:
            pass
    return stored


def _insights_from_json(raw: str | None) -> ApostilaInsights | None:
    if not raw:
        return None
    data = json.loads(raw)
    return ApostilaInsights(
        referencias_bibliograficas=_section_from_dict(data.get("referencias_bibliograficas")),
        dicas_leitura=_section_from_dict(data.get("dicas_leitura")),
        desafio_pratico=_section_from_dict(data.get("desafio_pratico")),
    )


class TursoSessionRepository(SessionRepository):
    def __init__(self, client: TursoHttpClient) -> None:
        self._client = client

    def save(self, session: StudySession, *, pdf_bytes: bytes, pdf_filename: str) -> None:
        # Desde o pedido do usuário pra guardar SOMENTE o PDF: nada de
        # materiais (com o texto bruto inteiro extraído de cada arquivo) nem
        # de análise estruturada vai mais pro Turso — só id/título/data e o
        # PDF já pronto (gerado por HistoryService ANTES de chamar isto
        # aqui). Isso também é uma otimização e tanto de quebra: o que
        # fazia "Salvar no histórico" ser lento não era só o número de
        # requisições HTTP (já resolvido com execute_batch), era sobretudo
        # o VOLUME de texto (potencialmente vários materiais grandes)
        # indo pela rede a cada save() — um INSERT só, com o PDF (tipicamente
        # bem menor que o texto bruto de origem, já que é só o conteúdo
        # relevante formatado) resolve os dois problemas de uma vez.
        #
        # sa_materials e sa_provider_attempts não recebem mais linhas
        # (ver comentário no schema.sql) — continuam existindo só pra
        # sessões salvas ANTES dessa mudança.
        self._client.execute(
            """
            INSERT INTO sa_study_sessions (id, title, created_at, pdf_bytes, pdf_filename)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                pdf_bytes = excluded.pdf_bytes,
                pdf_filename = excluded.pdf_filename
            """,
            [
                session.id,
                session.title,
                to_iso(session.created_at),
                _compress_pdf(pdf_bytes),
                pdf_filename,
            ],
        )

    def list_summaries(self, limit: int = 50) -> list[dict]:
        result = self._client.execute(
            "SELECT id, title, created_at, generated_by_provider, generated_by_model "
            "FROM sa_study_sessions ORDER BY created_at DESC LIMIT ?",
            [limit],
        )
        return result.rows

    def get(self, session_id: str) -> StudySession | None:
        # As 3 SELECTs (sessão, materiais, tentativas) não dependem umas das
        # outras — todas só filtram por session_id, que já temos de cara —
        # então também viram um único execute_batch() em vez de 3 chamadas
        # sequenciais. É o que fazia abrir uma sessão no histórico demorar
        # (cada SELECT pagando o round-trip de rede inteiro, um atrás do
        # outro).
        session_result, materials_result, attempts_result = self._client.execute_batch(
            [
                ("SELECT * FROM sa_study_sessions WHERE id = ?", [session_id]),
                ("SELECT * FROM sa_materials WHERE session_id = ?", [session_id]),
                (
                    "SELECT * FROM sa_provider_attempts WHERE session_id = ? ORDER BY attempted_at",
                    [session_id],
                ),
            ]
        )
        row = session_result.first()
        if row is None:
            return None

        pdf_bytes = row.get("pdf_bytes")
        if pdf_bytes:
            # Salva DEPOIS da mudança pra guardar só o PDF: não tem
            # materiais nem análise estruturada pra reconstruir (as duas
            # outras consultas do batch acima voltam vazias pra esse caso,
            # já que nada foi inserido em sa_materials/sa_provider_attempts
            # pra ela) — só o PDF pronto mesmo, que é tudo que a tela de
            # histórico precisa pra esse caso.
            return StudySession(
                id=row["id"],
                title=row["title"],
                materials=[],
                created_at=from_iso(row["created_at"]),  # type: ignore[arg-type]
                saved=True,
                stored_pdf_bytes=_decompress_pdf(pdf_bytes),
                stored_pdf_filename=row.get("pdf_filename") or f"{row['title']}.pdf",
            )

        # Legado: sessão salva ANTES da mudança pra guardar só o PDF — ainda
        # reconstruída a partir de materiais + análise estruturada, do jeito
        # que sempre funcionou, pra não perder o que já tinha sido salvo.
        materials = [
            Material(
                id=m["id"],
                filename=m["filename"],
                material_type=MaterialType(m["material_type"]),
                source_format=SourceFormat(m["source_format"]),
                raw_text=m["raw_text"],
                uploaded_at=from_iso(m["uploaded_at"]) or from_iso(row["created_at"]),  # type: ignore[arg-type]
            )
            for m in materials_result.rows
        ]

        attempts = tuple(
            ProviderAttempt(
                provider_name=a["provider_name"],
                model=a["model"],
                success=bool(a["success"]),
                duration_ms=a["duration_ms"],
                error_message=a["error_message"],
                attempted_at=from_iso(a["attempted_at"]) or from_iso(row["created_at"]),  # type: ignore[arg-type]
            )
            for a in attempts_result.rows
        )

        analysis_result = None
        if row.get("analysis_sections_json"):
            analysis_result = AnalysisResult(
                sections=json.loads(row["analysis_sections_json"]),
                generated_by_provider=row.get("generated_by_provider") or "",
                generated_by_model=row.get("generated_by_model") or "",
                provider_attempts=attempts,
                generated_at=from_iso(row["created_at"]),  # type: ignore[arg-type]
            )

        return StudySession(
            id=row["id"],
            title=row["title"],
            materials=materials,
            apostila_insights=_insights_from_json(row.get("apostila_insights_json")),
            analysis_result=analysis_result,
            created_at=from_iso(row["created_at"]),  # type: ignore[arg-type]
            saved=True,
        )

    def delete(self, session_id: str) -> None:
        # As 3 instruções num único execute_batch() — 1 request HTTP em vez
        # de 3 — pelo mesmo motivo do save(): menos round-trips de rede.
        self._client.execute_batch(
            [
                ("DELETE FROM sa_provider_attempts WHERE session_id = ?", [session_id]),
                ("DELETE FROM sa_materials WHERE session_id = ?", [session_id]),
                ("DELETE FROM sa_study_sessions WHERE id = ?", [session_id]),
            ]
        )

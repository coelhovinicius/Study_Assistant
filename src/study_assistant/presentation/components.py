"""Componentes de UI reaproveitados por mais de uma página do Streamlit.

Extrair esses blocos evita duplicar a renderização do resultado de uma
sessão de estudo entre a página de análise (sessão recém-gerada, ainda não
salva) e a página de histórico (sessão já salva, recuperada do Turso) —
ambas mostram exatamente a mesma coisa.
"""

from __future__ import annotations

import streamlit as st

from study_assistant.domain.entities import ExtractionMethod, StudySession
from study_assistant.presentation.di_container import AppContainer

_METHOD_LABELS = {
    ExtractionMethod.HEURISTICA: "🟢 encontrado diretamente na apostila",
    ExtractionMethod.IA: "🟡 identificado por interpretação automática do texto",
    ExtractionMethod.NAO_ENCONTRADO: "🔴 não encontrado",
}


def render_generation_details(session: StudySession) -> None:
    """Informações técnicas de como a análise foi gerada — de propósito
    discretas (dentro de um expander fechado por padrão, sem badge/emoji de
    destaque), já que o usuário sabe que é IA por trás e não quer isso
    anunciado a cada seção da tela."""
    if not session.analysis_result:
        return
    with st.expander("Detalhes técnicos da geração"):
        st.caption(
            f"Modelo: {session.analysis_result.generated_by_provider} "
            f"({session.analysis_result.generated_by_model})"
        )
        for attempt in session.analysis_result.provider_attempts:
            icon = "✅" if attempt.success else "❌"
            detail = "" if attempt.success else f" — {attempt.error_message}"
            st.write(
                f"{icon} {attempt.provider_name} ({attempt.model}) "
                f"— {attempt.duration_ms:.0f}ms{detail}"
            )


def render_insights(session: StudySession) -> None:
    if not session.apostila_insights:
        return
    with st.expander("📎 Extrações da apostila (referências, dicas, desafio)"):
        pairs = (
            ("Referências Bibliográficas", session.apostila_insights.referencias_bibliograficas),
            ("Dicas / Indicações de Leitura", session.apostila_insights.dicas_leitura),
            ("Desafio Prático", session.apostila_insights.desafio_pratico),
        )
        for label, extracted in pairs:
            st.markdown(f"**{label}** — {_METHOD_LABELS[extracted.method]}")
            st.write(extracted.content or "_(não encontrado)_")


def render_analysis_sections(session: StudySession) -> None:
    if not session.analysis_result:
        return
    for section_title, content in session.analysis_result.ordered_sections():
        expanded = section_title == "Análise e Resolução do Desafio Prático"
        with st.expander(section_title, expanded=expanded):
            st.markdown(content)


# Formatos escondidos da tela de download, mas que continuam registrados
# em ``report_generators/__init__.py`` (ALL_REPORT_GENERATORS) e totalmente
# funcionais por trás — só o botão some da UI. Pedido do usuário: "pode
# ocultar a opção de baixar csv, porém, mantém no código [...] que está
# inativo no momento e que pode ser reativada". Pra reativar, basta remover
# o formato deste conjunto (ou esvaziá-lo).
_HIDDEN_FORMATS: frozenset[str] = frozenset({"csv"})


def render_download_buttons(container: AppContainer, session: StudySession, *, key_prefix: str) -> None:
    formats = [f for f in container.report_use_case.available_formats if f not in _HIDDEN_FORMATS]
    columns = st.columns(len(formats))
    for column, fmt in zip(columns, formats):
        with column:
            try:
                report = container.report_use_case.execute(session, fmt)
            except Exception as exc:  # noqa: BLE001 - fronteira de UI: nunca deixa
                # um gerador quebrado (dependência ausente, conteúdo inesperado)
                # derrubar a tela inteira nem impedir os OUTROS formatos e os
                # botões de Salvar/Descartar (renderizados logo depois) de
                # aparecerem — só esse botão de download vira um aviso.
                st.error(f"Não foi possível gerar o .{fmt} agora.")
                with st.expander("Detalhes técnicos"):
                    st.code(str(exc))
                continue
            st.download_button(
                f"Baixar .{fmt}",
                data=report.content,
                file_name=report.filename,
                mime=report.mime_type,
                use_container_width=True,
                key=f"{key_prefix}_download_{fmt}",
            )


def render_full_result(container: AppContainer, session: StudySession, *, key_prefix: str) -> None:
    """Renderiza o resultado completo de uma sessão (usado tanto para uma
    sessão recém-analisada quanto para uma recuperada do histórico)."""
    render_insights(session)
    render_analysis_sections(session)
    render_generation_details(session)
    st.divider()
    st.markdown("#### 💾 Download")
    render_download_buttons(container, session, key_prefix=key_prefix)

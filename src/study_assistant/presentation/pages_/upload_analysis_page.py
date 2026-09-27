"""Página principal: upload dos materiais, extração, análise via cascata
de IA e download do relatório final (itens 7 a 10 do fluxo do usuário).
"""

from __future__ import annotations

import streamlit as st

from study_assistant.application.document_service import UploadedFile
from study_assistant.domain.entities import MaterialType, StudySession
from study_assistant.domain.exceptions import (
    AllProvidersFailedError,
    AnalysisPausedError,
    ReportGenerationError,
    RepositoryError,
    StudyAssistantError,
)
from study_assistant.presentation.components import render_full_result
from study_assistant.presentation.di_container import AppContainer
from study_assistant.presentation.theme import render_unsaved_changes_guard, themed_button

_ACCEPTED_TYPES = ["pdf", "txt", "docx"]
_SESSION_STATE_KEY = "current_study_session"
# Sufixo numérico anexado à key= do título e dos 4 uploaders. O Streamlit
# mantém o valor de um widget associado à sua key= entre reruns — recriar o
# widget com o MESMO nome não o esvazia. Incrementar este contador (via
# _reset_form_widgets) muda a key=, e o Streamlit trata isso como um widget
# novo, sem o arquivo/texto anterior. É o que faltava para "Descartar" e o
# novo botão "Nova análise" realmente limparem a tela, e não só o resultado.
_UPLOADER_VERSION_KEY = "uploader_widget_version"
# Flags de "isto está processando agora" — usadas pra bloquear a interação
# (desabilitar botões/uploaders) enquanto a cascata de IA ou a gravação no
# Turso estão rodando, em vez de deixar tudo clicável durante uma chamada
# que pode levar vários segundos. As duas operações rodam de forma síncrona
# (bloqueando a thread principal do script) DE PROPÓSITO — um esquema com
# thread separada + botão de cancelar foi tentado e voltou atrás: trazia
# mais problema visual (tela piscando, sidebar não escurecendo, botão de
# cancelar com o tamanho errado) do que valia a pena resolver agora.
_IS_ANALYZING_KEY = "is_analyzing"
_IS_SAVING_KEY = "is_saving"
_SAVE_NOTICE_KEY = "save_notice"
_ANALYSIS_NOTICE_KEY = "analysis_notice"
# Análise pausada num lote que falhou (ver AnalysisPausedError): o botão
# de analisar vira "Continuar análise" — os lotes já respondidos ficam
# salvos, então continuar só manda pra IA o que falta.
_ANALYSIS_PAUSED_KEY = "analysis_paused"


def has_unsaved_analysis() -> bool:
    """Usado pelo botão "Sair" (``streamlit_app.py``) pra decidir se avisa
    sobre perda de trabalho antes de encerrar a sessão — evita que
    ``streamlit_app.py`` precise conhecer a key= interna de session_state
    usada por esta página."""
    session: StudySession | None = st.session_state.get(_SESSION_STATE_KEY)
    return session is not None and not session.saved


def _missing_for_analysis(title: str, apostila_files) -> list[str]:
    """O que ainda falta pra liberar "Analisar materiais". O título é
    obrigatório (pedido do usuário) — antes, sem título, a sessão ganhava
    um genérico "Sessão de estudo — <data>", difícil de achar depois no
    histórico."""
    missing = []
    if not title.strip():
        missing.append("preencha o título da sessão")
    if not apostila_files:
        missing.append("envie ao menos um arquivo de Apostila")
    return missing


def _uploader_version() -> int:
    return st.session_state.get(_UPLOADER_VERSION_KEY, 0)


def _reset_form_widgets() -> None:
    st.session_state[_UPLOADER_VERSION_KEY] = _uploader_version() + 1


def _render_notice(notice: dict) -> None:
    """Mostra uma mensagem de resultado (sucesso/erro) UMA vez.

    Erros não podem ser exibidos na mesma passada em que acontecem, porque
    logo depois chamamos ``st.rerun()`` (pra desbloquear a tela) — e isso
    apagaria a mensagem antes do usuário ver. Por isso ela fica guardada no
    session_state e só é lida (e removida, daí o "uma vez") na passada
    seguinte, já com a tela toda liberada de novo.
    """
    kind = notice["kind"]
    if kind == "success":
        st.success(notice["message"])
    elif kind == "paused":
        st.warning(notice["message"])
        if notice.get("detail"):
            with st.expander("Detalhes técnicos"):
                st.code(notice["detail"])
    else:
        st.error(notice["message"])
        if notice.get("detail"):
            with st.expander("Detalhes técnicos"):
                st.code(notice["detail"])


@st.dialog("Começar uma nova análise?")
def _confirm_new_analysis_dialog(*, has_unsaved_result: bool) -> None:
    st.write("Isso limpa o título, os arquivos enviados e o resultado atual da tela.")
    if has_unsaved_result:
        st.warning("A análise atual ainda não foi salva no histórico — ela será perdida.")
    confirm_col, cancel_col = st.columns(2)
    with confirm_col:
        if themed_button("🆕 Confirmar", variant="delete", use_container_width=True):
            st.session_state.pop(_SESSION_STATE_KEY, None)
            st.session_state.pop(_ANALYSIS_PAUSED_KEY, None)
            _reset_form_widgets()
            st.rerun()
    with cancel_col:
        if st.button("Cancelar", use_container_width=True):
            st.rerun()


@st.dialog("Descartar esta análise?")
def _confirm_discard_dialog(*, has_unsaved_result: bool) -> None:
    st.write("Isso limpa o resultado desta tela.")
    if has_unsaved_result:
        st.warning("Esta análise ainda não foi salva no histórico — ela será perdida.")
    confirm_col, cancel_col = st.columns(2)
    with confirm_col:
        if themed_button("🗑️ Confirmar", variant="delete", use_container_width=True):
            st.session_state.pop(_SESSION_STATE_KEY, None)
            st.session_state.pop(_ANALYSIS_PAUSED_KEY, None)
            _reset_form_widgets()
            st.rerun()
    with cancel_col:
        if st.button("Cancelar", use_container_width=True):
            st.rerun()


def render_upload_analysis_page(container: AppContainer) -> None:
    session: StudySession | None = st.session_state.get(_SESSION_STATE_KEY)
    is_analyzing = st.session_state.get(_IS_ANALYZING_KEY, False)
    is_saving = st.session_state.get(_IS_SAVING_KEY, False)
    # "Ocupado" cobre as DUAS operações que mexem em rede (cascata de IA e
    # gravação no Turso) — enquanto qualquer uma delas estiver rodando, a
    # tela inteira (uploaders, título, os 3 botões) fica bloqueada, não só
    # o botão que disparou a ação.
    is_busy = is_analyzing or is_saving

    st.header("📚 Nova análise de estudo")
    st.caption(
        "Dê um título à sessão e suba os materiais desta matéria/aula. O "
        "título e a apostila são obrigatórios (é da apostila que as "
        "referências, dicas e o desafio são extraídos); os demais são "
        "opcionais."
    )

    _, new_analysis_col = st.columns([4, 1])
    with new_analysis_col:
        if st.button(
            "🆕 Nova análise",
            use_container_width=True,
            key="btn_open_new_analysis",
            disabled=is_busy,
        ):
            _confirm_new_analysis_dialog(
                has_unsaved_result=session is not None and not session.saved
            )

    version = _uploader_version()
    title = st.text_input(
        "Título desta sessão (matéria / aula / módulo)",
        placeholder="Ex: Direito Constitucional — Unidade 3",
        key=f"title_input_{version}",
        disabled=is_busy,
    )

    col1, col2 = st.columns(2)
    with col1:
        apostila_files = st.file_uploader(
            "Apostila",
            type=_ACCEPTED_TYPES,
            accept_multiple_files=True,
            key=f"uploader_apostila_{version}",
            disabled=is_busy,
        )
        podcast_files = st.file_uploader(
            "Audiodescrição do Podcast",
            type=_ACCEPTED_TYPES,
            accept_multiple_files=True,
            key=f"uploader_podcast_{version}",
            disabled=is_busy,
        )
    with col2:
        livro_files = st.file_uploader(
            "Livro (opcional)",
            type=_ACCEPTED_TYPES,
            accept_multiple_files=True,
            key=f"uploader_livro_{version}",
            disabled=is_busy,
        )
        outros_files = st.file_uploader(
            "Outros materiais (opcional)",
            type=_ACCEPTED_TYPES,
            accept_multiple_files=True,
            key=f"uploader_outros_{version}",
            disabled=is_busy,
        )

    missing = _missing_for_analysis(title, apostila_files)
    can_analyze = not missing
    if not is_analyzing and not can_analyze:
        st.info(f"Para habilitar a análise, {' e '.join(missing)}.")

    if is_analyzing:
        analyze_label = "⏳ Analisando..."
    elif st.session_state.get(_ANALYSIS_PAUSED_KEY, False):
        analyze_label = "▶️ Continuar análise"
    else:
        analyze_label = "🚀 Analisar materiais"
    analyze_clicked = st.button(
        analyze_label,
        type="primary",
        disabled=not can_analyze or is_busy,
        key="btn_analyze",
    )
    if analyze_clicked and not is_analyzing:
        # Esquema de 2 fases: liga o flag e recarrega ANTES de fazer
        # qualquer chamada de rede — é só assim que os widgets acima já
        # aparecem desabilitados quando a chamada de verdade começa a
        # rodar (senão eles só ficariam desabilitados DEPOIS que a análise
        # inteira já tivesse terminado, o que não bloqueia nada).
        st.session_state[_IS_ANALYZING_KEY] = True
        st.rerun()

    if notice := st.session_state.pop(_ANALYSIS_NOTICE_KEY, None):
        _render_notice(notice)

    if is_analyzing:
        _run_analysis(
            container,
            title=title.strip(),
            apostila_files=apostila_files,
            livro_files=livro_files,
            podcast_files=podcast_files,
            outros_files=outros_files,
        )

    render_unsaved_changes_guard(active=session is not None and not session.saved)
    if session is not None:
        _render_result(container, session, is_busy=is_busy)


def _build_uploaded_files(apostila_files, livro_files, podcast_files, outros_files) -> list[UploadedFile]:
    uploaded_files = [
        UploadedFile(f.name, f.getvalue(), MaterialType.APOSTILA) for f in apostila_files
    ]
    uploaded_files += [UploadedFile(f.name, f.getvalue(), MaterialType.LIVRO) for f in livro_files]
    uploaded_files += [
        UploadedFile(f.name, f.getvalue(), MaterialType.AUDIODESCRICAO_PODCAST)
        for f in podcast_files
    ]
    uploaded_files += [UploadedFile(f.name, f.getvalue(), MaterialType.OUTRO) for f in outros_files]
    return uploaded_files


def _do_pipeline_work(container: AppContainer, uploaded_files: list[UploadedFile], progress=None):
    materials = container.document_service.ingest(uploaded_files)
    # Respostas de IA guardadas há mais de alguns dias não servem mais pra
    # continuar nada — limpa antes de começar (falha aqui não trava nada).
    container.ai_caller.purge_expired()
    apostila_text = "\n\n".join(
        m.raw_text for m in materials if m.material_type is MaterialType.APOSTILA
    )
    insights = container.extraction_use_case.execute(apostila_text, progress=progress)
    analysis = container.analysis_use_case.execute(materials, insights, progress=progress)
    return materials, insights, analysis


def _run_analysis(
    container: AppContainer,
    *,
    title: str,
    apostila_files,
    livro_files,
    podcast_files,
    outros_files,
) -> None:
    """Roda a análise em lotes de forma síncrona (bloqueia o script até
    terminar) — o ``st.status`` mostra em que lote está, as esperas entre
    lotes (cota por minuto das IAs gratuitas) e a lista do que já ficou
    pronto. Os widgets acima já estão desabilitados (``is_busy=True`` desde
    o rerun anterior), então não dá pra mexer em mais nada enquanto isto
    roda, mesmo sem uma tela escurecida por cima.
    """
    with st.status(
        "Analisando os materiais em lotes — pode levar alguns minutos...", expanded=True
    ) as status:

        def progress(message: str, *, done: bool = False) -> None:
            if done:
                status.write(message)
            else:
                status.update(label=message)

        uploaded_files = _build_uploaded_files(apostila_files, livro_files, podcast_files, outros_files)
        try:
            materials, insights, analysis = _do_pipeline_work(container, uploaded_files, progress)
        except AnalysisPausedError as exc:
            # Nada se perde: cada lote respondido já está salvo. Continuar
            # (com os mesmos arquivos) só manda pra IA o que falta.
            st.session_state[_ANALYSIS_PAUSED_KEY] = True
            cause = exc.cause or "A IA não conseguiu responder depois de 3 tentativas."
            notice = {
                "kind": "paused",
                "message": (
                    f"⏸️ A análise foi pausada em **{exc.step_label}**. {cause} "
                    "Tudo o que já foi analisado ficou salvo — clique em **▶️ Continuar "
                    "análise** quando quiser: com os mesmos arquivos, só o que falta vai "
                    "para a IA."
                ),
                "detail": exc.detail,
            }
        except AllProvidersFailedError as exc:
            notice = {
                "kind": "error",
                "message": (
                    "Não foi possível concluir a análise agora. Verifique a "
                    "configuração em `.streamlit/secrets.toml` e tente novamente."
                ),
                "detail": str(exc),
            }
        except StudyAssistantError as exc:
            notice = {"kind": "error", "message": str(exc), "detail": None}
        except Exception:
            # Erro inesperado (bug de verdade, não um erro de negócio já
            # tratado) — deixa estourar em vez de esconder atrás de uma
            # mensagem genérica (melhor um traceback visível que um bug
            # silencioso), mas ainda assim desliga o flag antes: senão a
            # tela ficaria "ocupada" pra sempre depois que o usuário
            # recarregasse a página passado o erro.
            st.session_state[_IS_ANALYZING_KEY] = False
            raise
        else:
            st.session_state[_SESSION_STATE_KEY] = StudySession(
                title=title, materials=materials, apostila_insights=insights, analysis_result=analysis
            )
            st.session_state.pop(_ANALYSIS_PAUSED_KEY, None)
            notice = {"kind": "success", "message": "Análise concluída!"}

    if warning := container.ai_caller.persistence_warning:
        notice["message"] = f"{notice['message']}\n\n⚠️ {warning}"
        container.ai_caller.persistence_warning = None

    st.session_state[_IS_ANALYZING_KEY] = False
    st.session_state[_ANALYSIS_NOTICE_KEY] = notice
    st.rerun()


def _render_result(container: AppContainer, session: StudySession, *, is_busy: bool) -> None:
    st.divider()
    st.subheader(f"📄 Resultado — {session.title}")

    render_full_result(container, session, key_prefix="current")

    if notice := st.session_state.pop(_SAVE_NOTICE_KEY, None):
        _render_notice(notice)

    is_saving = st.session_state.get(_IS_SAVING_KEY, False)

    st.markdown("#### 🗃️ Histórico")
    # Os DOIS botões são desenhados primeiro (com o disabled= já correto),
    # e só DEPOIS disso é que uma chamada de rede é feita. Se a chamada ao
    # Turso (abaixo) rodasse dentro do "with save_col:", o "with
    # discard_col:" só seria alcançado (e o Descartar só apareceria
    # desabilitado no navegador) DEPOIS da chamada terminar — a tela
    # ficaria com o Descartar clicável durante o "Salvando..." inteiro.
    save_col, discard_col = st.columns(2)
    with save_col:
        # Mesmo azul do botão "Entrar" (type="primary") — não precisa se
        # distinguir dele, os dois são só "a ação positiva da tela".
        save_clicked = st.button(
            "⏳ Salvando..." if is_saving else "💾 Salvar no histórico",
            type="primary",
            disabled=session.saved or is_busy,
            use_container_width=True,
            key="btn_save_history",
        )
    with discard_col:
        # Mesma cor do "Excluir" no histórico — descartar uma sessão ainda
        # não salva e excluir uma já salva são, na prática, a mesma ação
        # (jogar fora o resultado).
        discard_clicked = themed_button(
            "🗑️ Descartar (não salvar)",
            variant="delete",
            use_container_width=True,
            disabled=is_busy,
        )

    if save_clicked and not is_saving:
        # Mesmo esquema de 2 fases do "Analisar materiais": liga o flag,
        # recarrega com os dois botões já desabilitados, e só DEPOIS chama
        # o Turso de verdade.
        st.session_state[_IS_SAVING_KEY] = True
        st.rerun()

    if is_saving:
        with st.spinner("Salvando no histórico..."):
            try:
                container.history_service.save(session)
            except RepositoryError as exc:
                st.session_state[_IS_SAVING_KEY] = False
                st.session_state[_SAVE_NOTICE_KEY] = {
                    "kind": "error",
                    "message": (
                        "Não foi possível salvar no histórico agora (falha ao acessar "
                        "o banco Turso). O resultado continua aqui na tela — tente "
                        "salvar de novo em instantes."
                    ),
                    "detail": str(exc),
                }
            except ReportGenerationError as exc:
                # O histórico guarda só o PDF agora, então salvar inclui
                # gerar o PDF primeiro (ver HistoryService.save) — se isso
                # falhar (ex: reportlab não instalado), salvar falha junto,
                # mesmo sem nenhum problema no Turso.
                st.session_state[_IS_SAVING_KEY] = False
                st.session_state[_SAVE_NOTICE_KEY] = {
                    "kind": "error",
                    "message": (
                        "Não foi possível gerar o PDF para salvar no histórico. O "
                        "resultado continua aqui na tela — tente salvar de novo."
                    ),
                    "detail": str(exc),
                }
            else:
                st.session_state[_IS_SAVING_KEY] = False
                st.session_state[_SAVE_NOTICE_KEY] = {"kind": "success", "message": "Sessão salva no histórico."}
        # Sempre recarrega (sucesso OU erro) — é o que tira os botões do
        # estado desabilitado; a mensagem guardada acima aparece na passada
        # seguinte, já com a tela liberada de novo.
        st.rerun()

    if discard_clicked:
        _confirm_discard_dialog(has_unsaved_result=not session.saved)

    if session.saved:
        st.caption("✅ Esta sessão já está salva no histórico.")

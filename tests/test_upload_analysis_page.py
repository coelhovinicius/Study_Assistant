"""Testes de presentation/pages_/upload_analysis_page.py.

``st.session_state`` funciona em "bare mode" (fora de ``streamlit run``,
como o pytest roda) — só emite avisos no log, não quebra — então dá pra
testar a lógica de estado desta página diretamente, sem precisar de um
servidor Streamlit de verdade rodando. ``st.button``/``st.rerun()`` também
não quebram em bare mode: botões sempre retornam False (não tem como
simular um clique de verdade sem um navegador) e rerun() é um no-op.

Contexto da regra de versionamento dos uploaders: o Streamlit mantém o
valor de um widget associado à sua ``key=`` entre reruns — recriar o
widget com o MESMO nome não o esvazia. "Descartar" e o novo botão "Nova
análise" precisam limpar de verdade os uploaders e o título, então a
key= desses widgets carrega um sufixo numérico (``_UPLOADER_VERSION_KEY``)
que é incrementado a cada reset.

Contexto do bloqueio de interação: "Analisar materiais" e "Salvar no
histórico" rodam de forma SÍNCRONA (bloqueando o script até terminar,
com ``st.spinner`` como feedback visual) — um esquema com thread separada
e botão de cancelar foi tentado e revertido: trazia mais problema visual
em produção (tela piscando, sidebar não escurecendo, botão de tamanho
errado) do que valia a pena resolver agora. O bloqueio de interação em si
continua via widgets desabilitados (``disabled=is_busy``), com o esquema
de 2 fases: o clique liga um flag em session_state e recarrega ANTES de
qualquer chamada de rede, pra que os widgets já apareçam desabilitados
quando a chamada de verdade começa.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import streamlit as st

from study_assistant.domain.entities import MaterialType, StudySession
from study_assistant.domain.exceptions import (
    AllProvidersFailedError,
    ReportGenerationError,
    RepositoryError,
)
from study_assistant.presentation.pages_ import upload_analysis_page as page
from study_assistant.shared.timezone_format import format_brasilia


def setup_function() -> None:
    # st.session_state é um estado global compartilhado pelo processo —
    # cada teste começa do zero pra não vazar contador/flag de um teste
    # pro outro.
    st.session_state.clear()


# --- título padrão da sessão (quando o usuário não digita um) ------------


def test_default_session_title_usa_horario_de_brasilia_nao_utc_cru(monkeypatch) -> None:
    """Regressão: o título padrão ("Sessão de estudo — dd/mm/aaaa hh:mm")
    formatava ``datetime.now(timezone.utc)`` DIRETO, sem converter pro fuso
    de Brasília — resultando num horário 3h ADIANTADO em relação ao "Gerado
    em" do relatório final (que já usava ``format_brasilia``). O título e o
    relatório precisam mostrar o MESMO horário de parede."""
    fixed_utc = datetime(2026, 9, 3, 0, 36, tzinfo=timezone.utc)

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_utc

    monkeypatch.setattr(page, "datetime", _FixedDatetime)

    title = page._default_session_title()

    assert title == f"Sessão de estudo — {format_brasilia(fixed_utc)}"
    assert "02/09/2026 21:36" in title  # Brasília = UTC-3
    assert "03/09/2026 00:36" not in title  # não pode sobrar o horário UTC cru


# --- versionamento dos widgets de upload ----------------------------------


def test_versao_inicial_dos_widgets_e_zero() -> None:
    assert page._uploader_version() == 0


def test_reset_incrementa_a_versao() -> None:
    assert page._uploader_version() == 0
    page._reset_form_widgets()
    assert page._uploader_version() == 1
    page._reset_form_widgets()
    assert page._uploader_version() == 2


def test_reset_muda_a_key_efetiva_dos_widgets() -> None:
    """A key= de cada widget usa a versão atual — é isso que força o
    Streamlit a tratar o widget como novo (sem o arquivo/texto anterior)
    depois de "Descartar" ou "Nova análise"."""
    v0 = page._uploader_version()
    key_before = f"uploader_apostila_{v0}"

    page._reset_form_widgets()

    v1 = page._uploader_version()
    key_after = f"uploader_apostila_{v1}"

    assert key_before != key_after


# --- _do_pipeline_work: a parte pura, sem Streamlit -----------------------


def test_do_pipeline_work_encadeia_ingest_extracao_e_analise() -> None:
    calls = []

    fake_material = SimpleNamespace(material_type=MaterialType.APOSTILA, raw_text="texto da apostila")

    def ingest(files):
        calls.append(("ingest", files))
        return [fake_material]

    def extract(text):
        calls.append(("extract", text))
        return "insights-fake"

    def analyze(materials, insights):
        calls.append(("analyze", materials, insights))
        return "analysis-fake"

    container = SimpleNamespace(
        document_service=SimpleNamespace(ingest=ingest),
        extraction_use_case=SimpleNamespace(execute=extract),
        analysis_use_case=SimpleNamespace(execute=analyze),
    )

    materials, insights, analysis = page._do_pipeline_work(container, uploaded_files=[])

    assert materials == [fake_material]
    assert insights == "insights-fake"
    assert analysis == "analysis-fake"
    assert [c[0] for c in calls] == ["ingest", "extract", "analyze"]


# --- _run_analysis: execução síncrona + tratamento de erro ---------------


def test_run_analysis_com_sucesso_cria_a_sessao_e_desliga_o_flag() -> None:
    fake_material = SimpleNamespace(material_type=MaterialType.APOSTILA, raw_text="texto")

    container = SimpleNamespace(
        document_service=SimpleNamespace(ingest=lambda files: [fake_material]),
        extraction_use_case=SimpleNamespace(execute=lambda text: "insights"),
        analysis_use_case=SimpleNamespace(execute=lambda materials, insights: "analysis"),
    )
    st.session_state[page._IS_ANALYZING_KEY] = True

    page._run_analysis(
        container,
        title="Minha sessão",
        apostila_files=[],
        livro_files=[],
        podcast_files=[],
        outros_files=[],
    )

    assert st.session_state[page._IS_ANALYZING_KEY] is False
    session: StudySession = st.session_state[page._SESSION_STATE_KEY]
    assert session.title == "Minha sessão"
    assert session.materials == [fake_material]
    notice = st.session_state[page._ANALYSIS_NOTICE_KEY]
    assert notice["kind"] == "success"


def test_run_analysis_com_erro_de_negocio_guarda_aviso_sem_criar_sessao() -> None:
    def falha(materials, insights):
        raise AllProvidersFailedError("todos os provedores falharam")

    container = SimpleNamespace(
        document_service=SimpleNamespace(ingest=lambda files: []),
        extraction_use_case=SimpleNamespace(execute=lambda text: None),
        analysis_use_case=SimpleNamespace(execute=falha),
    )
    st.session_state[page._IS_ANALYZING_KEY] = True

    page._run_analysis(
        container, title="t", apostila_files=[], livro_files=[], podcast_files=[], outros_files=[]
    )

    assert st.session_state[page._IS_ANALYZING_KEY] is False
    assert page._SESSION_STATE_KEY not in st.session_state
    notice = st.session_state[page._ANALYSIS_NOTICE_KEY]
    assert notice["kind"] == "error"
    assert "todos os provedores falharam" in notice["detail"]


def test_run_analysis_com_erro_inesperado_deixa_estourar_mas_desliga_o_flag() -> None:
    """Um bug de verdade (não um erro de negócio já tratado) precisa
    continuar visível como um traceback, não virar uma mensagem genérica
    de "algo deu errado" que esconderia o problema real — mas o flag
    ``is_analyzing`` ainda precisa ser desligado antes, senão a tela fica
    "ocupada" pra sempre depois que o usuário recarregar a página."""
    def bug(materials, insights):
        raise RuntimeError("bug inesperado")

    container = SimpleNamespace(
        document_service=SimpleNamespace(ingest=lambda files: []),
        extraction_use_case=SimpleNamespace(execute=lambda text: None),
        analysis_use_case=SimpleNamespace(execute=bug),
    )
    st.session_state[page._IS_ANALYZING_KEY] = True

    with pytest.raises(RuntimeError, match="bug inesperado"):
        page._run_analysis(
            container, title="t", apostila_files=[], livro_files=[], podcast_files=[], outros_files=[]
        )

    assert st.session_state[page._IS_ANALYZING_KEY] is False


# --- _render_result: salvar/descartar, incluindo o aviso pós-rerun -------


def test_render_result_desliga_is_saving_e_guarda_aviso_apos_erro_do_turso() -> None:
    st.session_state[page._IS_SAVING_KEY] = True
    session = StudySession(title="t", materials=[])

    class _FailingHistoryService:
        def save(self, session):  # noqa: ANN001, ANN201 - assinatura de teste
            raise RepositoryError("turso fora do ar")

    container = SimpleNamespace(
        report_use_case=SimpleNamespace(available_formats=["pdf"]),
        history_service=_FailingHistoryService(),
    )

    page._render_result(container, session, is_busy=False)

    assert st.session_state[page._IS_SAVING_KEY] is False
    assert session.saved is False
    notice = st.session_state[page._SAVE_NOTICE_KEY]
    assert notice["kind"] == "error"
    assert "turso fora do ar" in notice["detail"]


def test_render_result_desliga_is_saving_e_guarda_aviso_apos_erro_de_geracao_do_pdf() -> None:
    """Desde que o histórico passou a guardar só o PDF, salvar inclui gerar
    o PDF primeiro (dentro de history_service.save()) — se isso falhar
    (ex: reportlab não instalado), a tela precisa se comportar igual a uma
    falha do Turso: liberar os botões e mostrar um aviso, sem quebrar."""
    st.session_state[page._IS_SAVING_KEY] = True
    session = StudySession(title="t", materials=[])

    class _FailingHistoryService:
        def save(self, session):  # noqa: ANN001, ANN201 - assinatura de teste
            raise ReportGenerationError("Dependência 'reportlab' não instalada.")

    container = SimpleNamespace(
        report_use_case=SimpleNamespace(available_formats=["pdf"]),
        history_service=_FailingHistoryService(),
    )

    page._render_result(container, session, is_busy=False)

    assert st.session_state[page._IS_SAVING_KEY] is False
    assert session.saved is False
    notice = st.session_state[page._SAVE_NOTICE_KEY]
    assert notice["kind"] == "error"
    assert "reportlab" in notice["detail"]


def test_render_result_desliga_is_saving_e_guarda_aviso_apos_sucesso() -> None:
    st.session_state[page._IS_SAVING_KEY] = True
    session = StudySession(title="t", materials=[])

    class _WorkingHistoryService:
        def save(self, session):  # noqa: ANN001, ANN201 - assinatura de teste
            session.saved = True

    container = SimpleNamespace(
        report_use_case=SimpleNamespace(available_formats=["pdf"]),
        history_service=_WorkingHistoryService(),
    )

    page._render_result(container, session, is_busy=False)

    assert st.session_state[page._IS_SAVING_KEY] is False
    assert session.saved is True
    notice = st.session_state[page._SAVE_NOTICE_KEY]
    assert notice["kind"] == "success"


# --- confirmação antes de descartar / sair --------------------------------


def test_discard_clicado_abre_dialogo_em_vez_de_descartar_direto(monkeypatch) -> None:
    """Regressão: clicar em "Descartar" apagava a sessão atual na hora, sem
    pedir confirmação — o usuário pediu confirmação pra qualquer ação que
    perca informação já inserida. Agora o clique só abre o diálogo de
    confirmação (``_confirm_discard_dialog``); quem realmente limpa a
    sessão é o "Confirmar" DENTRO do diálogo."""
    session = StudySession(title="t", materials=[])
    st.session_state[page._SESSION_STATE_KEY] = session

    # st.button()/themed_button() sempre retornam False em bare mode — não
    # tem como simular um clique de verdade. Pra testar o que acontece
    # QUANDO o usuário clica em "Descartar", forçamos themed_button()
    # (usado só por esse botão dentro de _render_result) a retornar True.
    monkeypatch.setattr(page, "themed_button", lambda *args, **kwargs: True)

    dialog_calls = []
    monkeypatch.setattr(
        page, "_confirm_discard_dialog", lambda **kwargs: dialog_calls.append(kwargs)
    )

    container = SimpleNamespace(report_use_case=SimpleNamespace(available_formats=["pdf"]))
    page._render_result(container, session, is_busy=False)

    assert dialog_calls == [{"has_unsaved_result": True}]
    # a sessão não pode ter sido apagada só pelo clique — só o "Confirmar"
    # DENTRO do diálogo (testado abaixo) faz isso.
    assert st.session_state[page._SESSION_STATE_KEY] is session


def test_confirm_discard_dialog_ao_confirmar_limpa_a_sessao_e_reseta_uploaders(monkeypatch) -> None:
    """O corpo do diálogo é decorado com ``@st.dialog``, que quebra se
    chamado direto fora de um app rodando de verdade (levanta
    ``StreamlitAPIException`` em bare mode) — por isso o teste chama
    ``.__wrapped__``, a função original sem a decoração, jeito padrão de
    testar o CONTEÚDO de um diálogo sem precisar de navegador."""
    st.session_state[page._SESSION_STATE_KEY] = StudySession(title="t", materials=[])
    version_before = page._uploader_version()

    monkeypatch.setattr(page, "themed_button", lambda *args, **kwargs: True)

    page._confirm_discard_dialog.__wrapped__(has_unsaved_result=True)

    assert page._SESSION_STATE_KEY not in st.session_state
    assert page._uploader_version() == version_before + 1


def test_has_unsaved_analysis_reflete_a_sessao_atual() -> None:
    assert page.has_unsaved_analysis() is False

    st.session_state[page._SESSION_STATE_KEY] = StudySession(title="t", materials=[], saved=False)
    assert page.has_unsaved_analysis() is True

    st.session_state[page._SESSION_STATE_KEY] = StudySession(title="t", materials=[], saved=True)
    assert page.has_unsaved_analysis() is False

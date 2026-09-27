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

from types import SimpleNamespace

import pytest
import streamlit as st

from study_assistant.domain.entities import MaterialType, StudySession
from study_assistant.domain.exceptions import (
    AllProvidersFailedError,
    AnalysisPausedError,
    ReportGenerationError,
    RepositoryError,
)
from study_assistant.presentation.pages_ import upload_analysis_page as page


def setup_function() -> None:
    # st.session_state é um estado global compartilhado pelo processo —
    # cada teste começa do zero pra não vazar contador/flag de um teste
    # pro outro.
    st.session_state.clear()


# --- título obrigatório pra liberar "Analisar materiais" -----------------


def _render_form(monkeypatch, *, title: str, apostila_files: list) -> dict:
    """Renderiza a página em bare mode com o título e a apostila dados, e
    devolve o que interessa: os kwargs do botão "Analisar materiais" e os
    avisos st.info exibidos."""
    captured = {"analyze_button": None, "infos": []}

    def _button(label, *args, **kwargs):
        if kwargs.get("key") == "btn_analyze":
            captured["analyze_button"] = {"label": label, **kwargs}
        return False

    monkeypatch.setattr(st, "text_input", lambda *a, **k: title)
    monkeypatch.setattr(
        st,
        "file_uploader",
        lambda label, *a, **k: apostila_files if k["key"].startswith("uploader_apostila_") else [],
    )
    monkeypatch.setattr(st, "button", _button)
    monkeypatch.setattr(st, "info", lambda text, *a, **k: captured["infos"].append(text))
    monkeypatch.setattr(page, "render_unsaved_changes_guard", lambda **kwargs: None)

    page.render_upload_analysis_page(SimpleNamespace())
    return captured


@pytest.mark.parametrize("title", ["", "   "])
def test_analisar_fica_desabilitado_sem_titulo_mesmo_com_apostila(monkeypatch, title) -> None:
    captured = _render_form(monkeypatch, title=title, apostila_files=["apostila.pdf"])

    assert captured["analyze_button"]["disabled"] is True
    assert captured["infos"] == ["Para habilitar a análise, preencha o título da sessão."]


def test_analisar_fica_desabilitado_sem_apostila_mesmo_com_titulo(monkeypatch) -> None:
    captured = _render_form(monkeypatch, title="Direito Constitucional", apostila_files=[])

    assert captured["analyze_button"]["disabled"] is True
    assert captured["infos"] == ["Para habilitar a análise, envie ao menos um arquivo de Apostila."]


def test_aviso_lista_titulo_e_apostila_quando_faltam_os_dois(monkeypatch) -> None:
    captured = _render_form(monkeypatch, title="", apostila_files=[])

    assert captured["infos"] == [
        "Para habilitar a análise, preencha o título da sessão e envie ao menos um arquivo de Apostila."
    ]


def test_botao_vira_continuar_analise_quando_a_analise_esta_pausada(monkeypatch) -> None:
    st.session_state[page._ANALYSIS_PAUSED_KEY] = True

    captured = _render_form(monkeypatch, title="Direito Constitucional", apostila_files=["apostila.pdf"])

    assert captured["analyze_button"]["label"] == "▶️ Continuar análise"
    assert captured["analyze_button"]["disabled"] is False


def test_analisar_habilitado_com_titulo_e_apostila(monkeypatch) -> None:
    captured = _render_form(monkeypatch, title="Direito Constitucional", apostila_files=["apostila.pdf"])

    assert captured["analyze_button"]["disabled"] is False
    assert captured["infos"] == []


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


def _pipeline_container(
    *,
    ingest=lambda files: [],
    extract=lambda text, progress=None: None,
    analyze=lambda materials, insights, progress=None: None,
    persistence_warning=None,
) -> SimpleNamespace:
    return SimpleNamespace(
        document_service=SimpleNamespace(ingest=ingest),
        extraction_use_case=SimpleNamespace(execute=extract),
        analysis_use_case=SimpleNamespace(execute=analyze),
        ai_caller=SimpleNamespace(purge_expired=lambda: None, persistence_warning=persistence_warning),
    )


def test_do_pipeline_work_encadeia_ingest_extracao_e_analise() -> None:
    calls = []

    fake_material = SimpleNamespace(material_type=MaterialType.APOSTILA, raw_text="texto da apostila")

    def ingest(files):
        calls.append(("ingest", files))
        return [fake_material]

    def extract(text, progress=None):
        calls.append(("extract", text))
        return "insights-fake"

    def analyze(materials, insights, progress=None):
        calls.append(("analyze", materials, insights))
        return "analysis-fake"

    container = _pipeline_container(ingest=ingest, extract=extract, analyze=analyze)
    container.ai_caller.purge_expired = lambda: calls.append(("purge",))

    materials, insights, analysis = page._do_pipeline_work(container, uploaded_files=[])

    assert materials == [fake_material]
    assert insights == "insights-fake"
    assert analysis == "analysis-fake"
    # Respostas de IA antigas são limpas antes de qualquer chamada à IA.
    assert [c[0] for c in calls] == ["ingest", "purge", "extract", "analyze"]


def test_do_pipeline_work_repassa_o_progresso_para_a_extracao_e_a_analise() -> None:
    received = []
    progress = object()
    container = _pipeline_container(
        extract=lambda text, progress=None: received.append(progress),
        analyze=lambda materials, insights, progress=None: received.append(progress),
    )

    page._do_pipeline_work(container, uploaded_files=[], progress=progress)

    assert received == [progress, progress]


# --- _run_analysis: execução síncrona + tratamento de erro ---------------


def test_run_analysis_com_sucesso_cria_a_sessao_e_desliga_o_flag() -> None:
    fake_material = SimpleNamespace(material_type=MaterialType.APOSTILA, raw_text="texto")

    container = _pipeline_container(
        ingest=lambda files: [fake_material],
        extract=lambda text, progress=None: "insights",
        analyze=lambda materials, insights, progress=None: "analysis",
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
    def falha(materials, insights, progress=None):
        raise AllProvidersFailedError("todos os provedores falharam")

    container = _pipeline_container(analyze=falha)
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
    def bug(materials, insights, progress=None):
        raise RuntimeError("bug inesperado")

    container = _pipeline_container(analyze=bug)
    st.session_state[page._IS_ANALYZING_KEY] = True

    with pytest.raises(RuntimeError, match="bug inesperado"):
        page._run_analysis(
            container, title="t", apostila_files=[], livro_files=[], podcast_files=[], outros_files=[]
        )

    assert st.session_state[page._IS_ANALYZING_KEY] is False


# --- análise pausada: nada se perde, continuar retoma de onde parou -------


def _run(container) -> None:
    page._run_analysis(
        container, title="t", apostila_files=[], livro_files=[], podcast_files=[], outros_files=[]
    )


def test_lote_que_falhou_pausa_a_analise_com_o_motivo_e_sem_resultado_pela_metade() -> None:
    def pausa(materials, insights, progress=None):
        raise AnalysisPausedError(
            "Etapa 3 de 8: Apostila, parte 3 de 4",
            "A cota por minuto da IA gratuita estourou.",
            "Request too large ... tokens per minute",
        )

    st.session_state[page._IS_ANALYZING_KEY] = True

    _run(_pipeline_container(analyze=pausa))

    assert st.session_state[page._IS_ANALYZING_KEY] is False
    assert st.session_state[page._ANALYSIS_PAUSED_KEY] is True
    assert page._SESSION_STATE_KEY not in st.session_state  # nunca um resultado com buraco
    notice = st.session_state[page._ANALYSIS_NOTICE_KEY]
    assert notice["kind"] == "paused"
    assert "Apostila, parte 3 de 4" in notice["message"]
    assert "cota por minuto" in notice["message"]
    assert "Continuar análise" in notice["message"]
    assert "tokens per minute" in notice["detail"]


def test_continuar_ate_o_fim_tira_a_analise_do_estado_pausado() -> None:
    st.session_state[page._ANALYSIS_PAUSED_KEY] = True
    st.session_state[page._IS_ANALYZING_KEY] = True

    _run(_pipeline_container(analyze=lambda materials, insights, progress=None: "analysis"))

    assert page._ANALYSIS_PAUSED_KEY not in st.session_state
    assert st.session_state[page._ANALYSIS_NOTICE_KEY]["kind"] == "success"


def test_aviso_de_progresso_nao_salvo_no_banco_aparece_na_mensagem_final() -> None:
    container = _pipeline_container(
        analyze=lambda materials, insights, progress=None: "analysis",
        persistence_warning="Não foi possível salvar o progresso no banco (Turso) agora.",
    )
    st.session_state[page._IS_ANALYZING_KEY] = True

    _run(container)

    assert "Turso" in st.session_state[page._ANALYSIS_NOTICE_KEY]["message"]
    assert container.ai_caller.persistence_warning is None  # avisa uma vez só


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

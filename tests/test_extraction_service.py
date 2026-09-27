"""Testes da extração heurística e do fallback com IA (em lotes) para as
três seções que o usuário hoje recorta manualmente da apostila."""

from __future__ import annotations

import json

from study_assistant.application.ai_caller import ResilientAICaller
from study_assistant.application.apostila_heuristics import extract_sections_heuristically
from study_assistant.application.extraction_service import ExtractApostilaInsightsUseCase, merge_insights
from study_assistant.domain.entities import ApostilaInsights, ExtractedSection, ExtractionMethod
from study_assistant.infrastructure.ai_providers.cascade import AIProviderCascade
from tests.fixtures.fake_ai_provider import ScriptedAIProvider
from tests.fixtures.in_memory_ai_response_store import FakeClock, InMemoryAIResponseStore

_APOSTILA_COM_CABECALHOS = """
Unidade 3 — Introdução ao Direito Constitucional

Conteúdo teórico da unidade, bastante extenso, falando sobre princípios
fundamentais e organização do Estado.

Referências Bibliográficas
MENDES, Gilmar. Curso de Direito Constitucional. São Paulo: Saraiva, 2020.
BARROSO, Luís Roberto. Curso de Direito Constitucional Contemporâneo.

Dicas de Leitura
Para aprofundar, veja o texto complementar sobre federalismo no portal
da disciplina.

Desafio Prático
Elabore um parecer sobre a constitucionalidade de uma lei estadual que
contrarie norma federal, aplicando os conceitos desta unidade.
""".strip()

_APOSTILA_SEM_CABECALHOS = """
Só um texto corrido qualquer, sem nenhuma seção identificável de
referências, dicas de leitura ou desafio prático.
""".strip()

_ALL_KEYS = ("referencias_bibliograficas", "dicas_leitura", "desafio_pratico")


def _use_case(provider: ScriptedAIProvider, **kwargs) -> ExtractApostilaInsightsUseCase:
    clock = FakeClock()
    caller = ResilientAICaller(
        AIProviderCascade([provider]), InMemoryAIResponseStore(), sleep=clock.sleep, clock=clock
    )
    return ExtractApostilaInsightsUseCase(caller, **kwargs)


def _answer(**found: str) -> str:
    return json.dumps({key: found.get(key, "") for key in _ALL_KEYS})


def test_extracao_heuristica_encontra_as_tres_secoes() -> None:
    sections = extract_sections_heuristically(_APOSTILA_COM_CABECALHOS)

    assert "referencias_bibliograficas" in sections
    assert "MENDES, Gilmar" in sections["referencias_bibliograficas"]

    assert "dicas_leitura" in sections
    assert "federalismo" in sections["dicas_leitura"]

    assert "desafio_pratico" in sections
    assert "parecer" in sections["desafio_pratico"]


def test_extracao_heuristica_retorna_vazio_sem_cabecalhos() -> None:
    sections = extract_sections_heuristically(_APOSTILA_SEM_CABECALHOS)
    assert sections == {}


def test_use_case_usa_heuristica_quando_encontra_cabecalhos() -> None:
    provider = ScriptedAIProvider(lambda prompt: _answer())

    insights = _use_case(provider).execute(_APOSTILA_COM_CABECALHOS)

    assert insights.referencias_bibliograficas.method == ExtractionMethod.HEURISTICA
    assert insights.dicas_leitura.method == ExtractionMethod.HEURISTICA
    assert insights.desafio_pratico.method == ExtractionMethod.HEURISTICA
    assert provider.prompts == []  # não precisou cair para IA
    assert insights.is_complete


def test_use_case_cai_para_ia_com_uma_chamada_por_lote_para_todas_as_secoes() -> None:
    provider = ScriptedAIProvider(lambda prompt: _answer(referencias_bibliograficas="extraído pela IA"))

    insights = _use_case(provider).execute(_APOSTILA_SEM_CABECALHOS)

    assert insights.referencias_bibliograficas.method == ExtractionMethod.IA
    assert insights.referencias_bibliograficas.content == "extraído pela IA"
    assert len(provider.prompts) == 1  # apostila pequena = 1 lote, as 3 seções numa chamada só
    assert provider.required_keys == [_ALL_KEYS]


def test_use_case_junta_o_que_cada_lote_encontrou_em_ordem() -> None:
    """Dicas de leitura costumam vir espalhadas pela apostila inteira."""
    pages = [f"[pagina{i}] " + "texto " * 40 for i in range(4)]

    def responder(prompt: str) -> str:
        page = next(p for p in ("pagina0", "pagina1", "pagina2", "pagina3") if p in prompt)
        return _answer(dicas_leitura=f"dica da {page}")

    provider = ScriptedAIProvider(responder)
    insights = _use_case(provider, batch_chars=300).execute("\n\n".join(pages))

    assert len(provider.prompts) == 4
    assert insights.dicas_leitura.content == "dica da pagina0\n\ndica da pagina1\n\ndica da pagina2\n\ndica da pagina3"


def test_so_pede_a_ia_as_secoes_que_a_heuristica_nao_achou() -> None:
    apostila = _APOSTILA_SEM_CABECALHOS + "\n\nDesafio Prático\nResolva o caso X."
    provider = ScriptedAIProvider(lambda prompt: json.dumps({"referencias_bibliograficas": "", "dicas_leitura": ""}))

    insights = _use_case(provider).execute(apostila)

    assert insights.desafio_pratico.method == ExtractionMethod.HEURISTICA
    assert provider.required_keys == [("referencias_bibliograficas", "dicas_leitura")]


def test_use_case_marca_nao_encontrado_quando_ia_tambem_nao_acha() -> None:
    provider = ScriptedAIProvider(lambda prompt: _answer())

    insights = _use_case(provider).execute(_APOSTILA_SEM_CABECALHOS)

    assert insights.referencias_bibliograficas.method == ExtractionMethod.NAO_ENCONTRADO
    assert not insights.is_complete


# --- cabeçalhos reais das apostilas Kroton/Anhanguera do usuário ----------
#
# Trechos copiados da estrutura das apostilas dele (ex: 5_4 Projetos com
# DevOps): "Dica do Professor" e "Leitura Fundamental"/"Indicação de
# leitura 1" não eram reconhecidos — a dica ia parar dentro do Desafio e a
# IA tinha que procurá-la.

_APOSTILA_KROTON_DICA_DO_PROFESSOR = """
Conteúdo da unidade sobre DevOps.

Norte para a resolução...
• Mudança cultural e não apenas um
método.
• Garantia de qualidade é para todos!

Dica do Professor
Bloco 5
Anderson da Silva Marcolino

Como as práticas DevOps têm sido utilizadas?
• Busque na internet a dissertação referenciada a seguir e
realize a leitura:
BRAGA, Filipe Antônio Motta. Um panorama sobre o uso de
práticas DevOps nas indústrias de software. 2015.

Referências
SATO, D. DevOps na prática. São Paulo: Casa do Código, 2014.
""".strip()


def test_dica_do_professor_vira_a_dica_e_nao_entra_no_desafio() -> None:
    sections = extract_sections_heuristically(_APOSTILA_KROTON_DICA_DO_PROFESSOR)

    assert "BRAGA, Filipe" in sections["dicas_leitura"]
    assert "Dica do Professor" not in sections["desafio_pratico"]
    assert "BRAGA" not in sections["desafio_pratico"]
    assert sections["desafio_pratico"].startswith("• Mudança cultural")
    assert sections["referencias_bibliograficas"].startswith("SATO, D.")


def test_leitura_fundamental_e_indicacao_de_leitura_sao_reconhecidas() -> None:
    apostila = """
Desafio Prático
Monte um plano de testes.

Leitura Fundamental
Prezado estudante, as indicações a seguir estão na Biblioteca Virtual.

Indicação de leitura 1
Livro sobre testes automatizados.

Referências
ANICHE, Mauricio. Testes automatizados de software. 2015.
""".strip()

    sections = extract_sections_heuristically(apostila)

    assert "Indicação de leitura 1" in sections["dicas_leitura"]
    assert sections["desafio_pratico"] == "Monte um plano de testes."
    assert sections["referencias_bibliograficas"].startswith("ANICHE")


def test_preferencias_nao_e_confundida_com_referencias() -> None:
    """Regressão: "referencias" casava dentro de "preferências"."""
    apostila = "Recolher preferências e\nrestrições = requisitos!\n\nReferências\nDEVMEDIA. Requisitos. 2008."

    assert extract_sections_heuristically(apostila)["referencias_bibliograficas"] == "DEVMEDIA. Requisitos. 2008."


def test_frase_terminada_em_ponto_nao_e_cabecalho() -> None:
    """Regressão: "exemplos e referências na história." (meio do texto) era
    tomado pelo cabeçalho, e a lista de verdade, no fim, ficava de fora."""
    apostila = (
        "Conheça exemplos e referências na história.\n• Usabilidade: princípios.\n\n"
        "Referências\nBARRETO, J. Interface humano-computador. 2018."
    )

    refs = extract_sections_heuristically(apostila)["referencias_bibliograficas"]

    assert refs == "BARRETO, J. Interface humano-computador. 2018."


def test_referencias_que_continuam_na_pagina_seguinte_ficam_inteiras() -> None:
    apostila = "Referências\nANICHE, M. Testes. 2015.\n\nReferências\nSANTOS, L. Qualidade. 2020."

    refs = extract_sections_heuristically(apostila)["referencias_bibliograficas"]

    assert "ANICHE" in refs and "SANTOS" in refs


def test_reticencias_de_um_caractere_nao_cortam_o_comeco_dos_trechos() -> None:
    """Regressão: "…" virava "..." na normalização e desalinhava o texto —
    os trechos saíam cortados ("oco 5" em vez de "Bloco 5")."""
    apostila = "Introdução… com reticências… no meio.\n\nDica do Professor\nBloco 5\nRecomendação de filme."

    assert extract_sections_heuristically(apostila)["dicas_leitura"].startswith("Bloco 5")


def test_marca_de_layout_bloco_e_professor_sai_da_dica() -> None:
    """"Bloco 5" + o nome do professor vêm logo abaixo de "Dica do Professor"
    nas apostilas Kroton — não são conteúdo da dica."""
    dica = extract_sections_heuristically(_APOSTILA_KROTON_DICA_DO_PROFESSOR)["dicas_leitura"]

    assert dica.startswith("Como as práticas DevOps têm sido utilizadas?")
    assert "Anderson" not in dica


def test_linha_bloco_seguida_de_frase_nao_e_removida() -> None:
    apostila = "Dica do Professor\nBloco 5\nLeia o capítulo 3 do livro.\n\nReferências\nSATO, D. 2014."

    assert extract_sections_heuristically(apostila)["dicas_leitura"].startswith("Bloco 5")


# --- "Outros materiais": o desafio de um Desafio Profissional é achado ------


def _insights(*, refs="", dicas="", desafio="", method=ExtractionMethod.HEURISTICA, from_apostila=True):
    def section(content):
        return ExtractedSection(content, method if content else ExtractionMethod.NAO_ENCONTRADO)

    return ApostilaInsights(section(refs), section(dicas), section(desafio), from_apostila=from_apostila)


def test_merge_com_so_a_apostila_devolve_ela_mesma() -> None:
    apostila = _insights(refs="SATO, D. 2014.")

    assert merge_insights([("apostila.pdf", apostila)], from_apostila=True) is apostila


def test_merge_sem_apostila_e_sem_nada_encontrado_devolve_none() -> None:
    nothing = _insights(from_apostila=False)

    assert merge_insights([("artigo.pdf", nothing), ("notas.md", nothing)], from_apostila=False) is None
    assert merge_insights([("artigo.pdf", nothing)], from_apostila=False) is None
    assert merge_insights([], from_apostila=False) is None


def test_merge_junta_o_desafio_da_apostila_e_o_de_outros_com_o_nome_de_cada_arquivo() -> None:
    merged = merge_insights(
        [
            ("apostila.pdf", _insights(refs="SATO, D. 2014.", desafio="Desafio da apostila.")),
            ("desafio_profissional.pdf", _insights(desafio="Caso da startup.", method=ExtractionMethod.IA, from_apostila=False)),
        ],
        from_apostila=True,
    )

    assert merged.desafio_pratico.content == (
        "### apostila.pdf\nDesafio da apostila.\n\n### desafio_profissional.pdf\nCaso da startup."
    )
    assert merged.desafio_pratico.method == ExtractionMethod.IA
    assert merged.referencias_bibliograficas.content == "SATO, D. 2014."  # uma fonte só: sem o nome do arquivo
    assert merged.dicas_leitura.method == ExtractionMethod.NAO_ENCONTRADO
    assert merged.from_apostila is True


def test_desafio_de_outros_materiais_sem_apostila_e_encontrado_pela_ia() -> None:
    """Um enunciado sem cabeçalho nenhum (como "Desafio 1 Software
    Financeiro.pdf" do usuário): a IA acha o enunciado; e o prompt diz a ela
    que é um material de estudo, não uma apostila, e que uma Proposta de
    Resolução não é o desafio."""
    provider = ScriptedAIProvider(lambda prompt: _answer(desafio_pratico="Reflita: startup de e-commerce."))
    documento = "Você foi contratado como consultor por uma startup de e-commerce.\nProponha a divisão das equipes."

    insights = _use_case(provider).execute(documento, location='em "desafio.pdf"', is_apostila=False)

    assert insights.from_apostila is False
    assert insights.desafio_pratico.method == ExtractionMethod.IA
    assert insights.desafio_pratico.content == "Reflita: startup de e-commerce."
    assert "é um material de estudo" in provider.prompts[0]
    assert "Proposta de Resolução" not in provider.prompts[0] or "RESOLUÇÃO de um desafio" in provider.prompts[0]
    assert "Reflita sobre a seguinte" in provider.prompts[0]


def test_prompt_de_extracao_da_apostila_continua_exatamente_igual() -> None:
    """As respostas já salvas no banco são reaproveitadas pela impressão
    digital do prompt: com apostila, ele não pode mudar nem uma vírgula."""
    from study_assistant.config.prompts import build_batch_extraction_prompt

    prompt = build_batch_extraction_prompt(
        sections={"dicas_leitura": "Dicas"}, part_number=1, part_count=2, text="TEXTO"
    )

    assert prompt == (
        "IMPORTANTE: responda exclusivamente em Português do Brasil (pt-BR).\n\n"
        "O texto abaixo é a parte 1 de 2 de uma apostila. Procure nele as seções listadas e transcreva literalmente (ou\n"
        "resuma de forma fiel, se o conteúdo estiver espalhado) o que encontrar.\n\n"
        "SEÇÕES PROCURADAS (chave do JSON: seção):\n"
        '- "dicas_leitura": Dicas\n\n'
        "Responda apenas com um objeto JSON com exatamente essas chaves. Use string\n"
        'vazia "" para a seção que NÃO aparece neste texto — não invente.\n\n'
        "TEXTO:\n"
        "TEXTO\n"
    )


# --- o enunciado do desafio (e não só a orientação) -----------------------


def test_desafio_comeca_no_enunciado_e_nao_so_no_norte_para_a_resolucao() -> None:
    """Regressão da apostila 5_4 DevOps: só o "Norte para a resolução" (a
    orientação) era extraído — a situação proposta ficava de fora e a IA
    resolvia um desafio que não conhecia."""
    apostila = """
Reflexão
Qual a principal dificuldade em se adotar o DevOps?

Teoria em Prática
Desenvolvimento e gestão de
projetos com DevOps
Bloco 4
Anderson da Silva Marcolino

Reflita sobre a seguinte situação
Um gerente tem dificuldades com duas equipes que se reúnem a cada quinze dias.

Norte para a resolução...
• Mudança cultural e não apenas um método.

Dica do Professor
Bloco 5
Anderson da Silva Marcolino
Leia a dissertação de Braga (2015).
""".strip()

    desafio = extract_sections_heuristically(apostila)["desafio_pratico"]

    assert desafio.startswith("Reflita sobre a seguinte situação")  # sem título do slide nem "Bloco 4"
    assert "duas equipes" in desafio
    assert "Mudança cultural" in desafio  # a orientação continua junto
    assert "Braga" not in desafio


def test_documento_de_desafio_profissional_e_reconhecido_pelo_cabecalho() -> None:
    documento = """
EVOLUÇÃO DOS SOFTWARES
WBA0452_v1.0
Desafio Profissional
Autoria: Anderson da Silva Marcolino
Caro aluno, o presente Desafio Profissional é um material de auto estudo. A
resolução do Desafio não precisará ser postada ou
compartilhada no ambiente virtual.
1. Caso – Ciclo de desenvolvimento de software
""".strip()

    desafio = extract_sections_heuristically(documento)["desafio_pratico"]

    assert desafio.startswith("Autoria: Anderson")
    assert "1. Caso" in desafio


def test_trecho_depois_do_fim_de_uma_frase_na_mesma_linha_nao_e_cabecalho() -> None:
    """Regressão: "...profissional. A resolução do Desafio não precisará ser
    postada ou" era tomado como cabeçalho, e o desafio começava no meio de
    uma frase."""
    texto = "fazendo uma conexão com a prática profissional. A resolução do Desafio não precisará ser postada ou\ncompartilhada."

    assert extract_sections_heuristically(texto) == {}

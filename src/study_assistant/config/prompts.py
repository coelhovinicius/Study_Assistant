"""Prompts-base usados nas chamadas à IA.

Existe UM prompt de negócio por tarefa — não um por provedor. Cada provedor
concreto (``infrastructure/ai_providers/*``) recebe o mesmo texto e só
adapta a *forma* da chamada (SDK, parâmetros), nunca o conteúdo do pedido.
Isso é o que o usuário pediu ao mostrar o fluxo em n8n: "o prompt deve ser
adaptado em cada um dos fluxos de IA" — a adaptação é de encapsulamento
técnico, não de conteúdo de negócio, garantindo que os provedores da
cascata sejam avaliados nas mesmas condições.

Desde a análise em lotes (pra caber na cota por minuto das IAs gratuitas),
a análise não é mais UM prompt gigante com o material inteiro pedindo as 8
seções de uma vez. São prompts pequenos:

* ``build_batch_analysis_prompt`` — um por lote de ~12 mil caracteres de
  cada material: título curto, análise detalhada daquele trecho e um resumo
  curto (que alimenta as seções finais);
* ``build_batch_extraction_prompt`` — um por lote da apostila, só quando a
  heurística não achou referências/dicas/desafio;
* ``build_references_prompt``, ``build_reading_tips_prompt``,
  ``build_challenge_prompt`` e ``build_synthesis_prompt`` — as 4 seções
  finais, a partir dos trechos extraídos da apostila e dos resumos curtos.

Cada um pede um JSON com poucas chaves — e são essas chaves que o workflow
do n8n (nós "JSON ...") confere antes de aceitar a resposta.
"""

from __future__ import annotations

_LANGUAGE_AND_TONE = """IMPORTANTE: Todo o conteúdo gerado DEVE estar exclusivamente em Português
do Brasil (pt-BR), com tom natural, didático e profissional — como um
tutor experiente explicando o conteúdo a um estudante."""

_FORMATTING_RULES = """Escreva em parágrafos, separados por quebra de linha. Não use títulos em
markdown (linhas começando com #) — a organização em partes já é feita
pelo app."""

BATCH_ANALYSIS_KEYS: tuple[str, ...] = ("titulo", "analise", "resumo")


def build_batch_analysis_prompt(
    *,
    material_label: str,
    filename: str,
    focus: str,
    part_number: int,
    part_count: int,
    text: str,
) -> str:
    """Análise de UM lote de um material (apostila, livro, podcast, outro)."""
    if part_count > 1:
        where = (
            f'O material "{filename}" ({material_label}) foi dividido em {part_count} partes, '
            f"para caber no limite das IAs. Você vai analisar SOMENTE a parte {part_number} "
            f"de {part_count}."
        )
        text_header = f"TEXTO DA PARTE {part_number} DE {part_count}:"
    else:
        where = f'Você vai analisar o material "{filename}" ({material_label}).'
        text_header = "TEXTO DO MATERIAL:"

    return f"""{_LANGUAGE_AND_TONE}

Você é um tutor especialista, responsável por analisar o material de
estudo de uma disciplina. {where}

FOCO DA ANÁLISE: {focus}

{text_header}
{text}

TAREFA:
Responda com um objeto JSON com exatamente estas chaves:
  "titulo": título curto (até 8 palavras) com o assunto principal deste texto;
  "analise": análise aprofundada e didática deste texto — conceitos-chave,
    definições, exemplos e pontos de atenção. {_FORMATTING_RULES}
  "resumo": resumo de até 120 palavras dos assuntos deste texto (será usado
    depois para conectar esta parte às demais e resolver o desafio prático).

Não invente conteúdo que não esteja no texto. Não comente que o texto é uma
parte ou um trecho — escreva a análise como um estudo daquele conteúdo.
"""


def build_batch_extraction_prompt(
    *, sections: dict[str, str], part_number: int, part_count: int, text: str
) -> str:
    """Procura, num lote da apostila, as seções que a heurística por
    cabeçalhos não encontrou (``sections``: chave do JSON -> nome da seção)."""
    wanted = "\n".join(f'- "{key}": {label}' for key, label in sections.items())
    where = (
        f"O texto abaixo é a parte {part_number} de {part_count} de uma apostila."
        if part_count > 1
        else "O texto abaixo é uma apostila."
    )
    return f"""IMPORTANTE: responda exclusivamente em Português do Brasil (pt-BR).

{where} Procure nele as seções listadas e transcreva literalmente (ou
resuma de forma fiel, se o conteúdo estiver espalhado) o que encontrar.

SEÇÕES PROCURADAS (chave do JSON: seção):
{wanted}

Responda apenas com um objeto JSON com exatamente essas chaves. Use string
vazia "" para a seção que NÃO aparece neste texto — não invente.

TEXTO:
{text}
"""


def _single_text_answer(key: str) -> str:
    # Sem isto, a análise das referências veio como uma LISTA de objetos
    # ({"referencia": ..., "conteudo": ...}) numa análise real do usuário.
    return (
        f'Responda apenas com um objeto JSON com a chave "{key}", cujo valor é um\n'
        "único texto corrido (string) — não uma lista nem um objeto."
    )


def build_references_prompt(*, references_text: str, topics: str) -> str:
    return f"""{_LANGUAGE_AND_TONE}

Você é um tutor especialista. Abaixo estão as referências bibliográficas
indicadas na apostila de uma disciplina e os assuntos que a disciplina cobre.

ASSUNTOS DA DISCIPLINA (só contexto):
{topics}

REFERÊNCIAS BIBLIOGRÁFICAS DA APOSTILA:
{references_text}

TAREFA:
Analise SOMENTE as referências bibliográficas listadas acima. Para cada
referência, traga o conteúdo técnico do assunto que ela aborda (conceitos,
técnicas, definições, exemplos), não um parágrafo genérico de "por que foi
indicada". Não invente citações literais nem afirmações sobre o que a
obra exata "diz" — fique no nível do assunto geral que ela cobre. Os
assuntos da disciplina servem só pra relacionar cada referência ao que foi
estudado — não são referências e não devem ser comentados um a um.
{_FORMATTING_RULES}

{_single_text_answer("analise_referencias_bibliograficas")}
"""


def build_reading_tips_prompt(*, tips_text: str, topics: str) -> str:
    return f"""{_LANGUAGE_AND_TONE}

Você é um tutor especialista. Abaixo estão as dicas/indicações de leitura
da apostila de uma disciplina e os assuntos que a disciplina cobre.

ASSUNTOS DA DISCIPLINA (só contexto):
{topics}

DICAS / INDICAÇÕES DE LEITURA DA APOSTILA:
{tips_text}

TAREFA:
Analise SOMENTE as indicações listadas em "DICAS / INDICAÇÕES DE LEITURA
DA APOSTILA": o que cada uma acrescenta ao estudo e como aproveitá-la da
melhor forma. Os assuntos da disciplina servem só pra relacionar as
indicações ao conteúdo — NÃO são indicações de leitura: não os comente um a
um nem os apresente como leituras recomendadas. Se houver uma indicação só,
a análise é só dela. Ignore nomes de professor, números de bloco e outras
marcas de layout que tenham vindo junto com o texto. Não invente conteúdo
que não esteja nas dicas. {_FORMATTING_RULES}

{_single_text_answer("analise_dicas_leitura")}
"""


def build_challenge_prompt(*, challenge_text: str, summaries: str) -> str:
    return f"""{_LANGUAGE_AND_TONE}

Você é um tutor especialista. Abaixo está o desafio prático proposto na
apostila de uma disciplina e um resumo de cada parte do material estudado.

RESUMO DO MATERIAL, PARTE A PARTE:
{summaries}

DESAFIO PRÁTICO DA APOSTILA:
{challenge_text}

TAREFA:
Analise e RESOLVA o desafio prático — explique seu raciocínio
passo a passo e entregue a resolução completa, fundamentada no material
resumido acima. {_FORMATTING_RULES}

{_single_text_answer("analise_e_resolucao_desafio")}
"""


def build_synthesis_prompt(*, summaries: str) -> str:
    return f"""{_LANGUAGE_AND_TONE}

Você é um tutor especialista. Abaixo está um resumo de cada parte do
material de estudo de uma disciplina (apostila, livro, podcast e outros,
quando houver).

RESUMO DO MATERIAL, PARTE A PARTE:
{summaries}

TAREFA:
Escreva uma síntese geral que conecte todos esses pontos: como os
assuntos se relacionam, o que é central e o que é complementar, e o que o
estudante precisa dominar ao final. Não invente conteúdo que não esteja
nos resumos. {_FORMATTING_RULES}

{_single_text_answer("sintese_geral")}
"""

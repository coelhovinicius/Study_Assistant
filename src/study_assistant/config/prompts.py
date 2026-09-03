"""Prompts-base usados nas chamadas à IA.

Existe UM prompt de negócio por tarefa (análise completa / extração de
seção específica) — não um por provedor. Cada provedor concreto
(``infrastructure/ai_providers/*``) recebe o mesmo texto e só adapta a
*forma* da chamada (SDK, parâmetros), nunca o conteúdo do pedido. Isso é o
que o usuário pediu ao mostrar o fluxo em n8n: "o prompt deve ser adaptado
em cada um dos fluxos de IA" — a adaptação é de encapsulamento técnico, não
de conteúdo de negócio, garantindo que os quatro provedores da cascata
sejam avaliados nas mesmas condições.
"""

from __future__ import annotations

from study_assistant.domain.entities import ANALYSIS_SECTION_ORDER, ANALYSIS_SECTION_TITLES

_ANALYSIS_JSON_SCHEMA_HINT = "\n".join(
    f'  "{key}": "análise em português (pt-BR) sobre: {ANALYSIS_SECTION_TITLES[key]}"'
    for key in ANALYSIS_SECTION_ORDER
)


def build_analysis_prompt(*, materials_context: str, insights_context: str) -> str:
    """Monta o prompt de análise expandida (item 6.1 do fluxo original do usuário)."""
    return f"""IMPORTANTE: Todo o conteúdo gerado DEVE estar exclusivamente em Português
do Brasil (pt-BR), com tom natural, didático e profissional — como um
tutor experiente explicando o conteúdo a um estudante.

Você é um tutor especialista, responsável por analisar o material de
estudo de uma disciplina e apresentar uma análise detalhada e expandida,
organizada por assunto, além de resolver o desafio prático proposto.

MATERIAIS DA DISCIPLINA (apostila, livro, podcast e outros, quando houver):
{materials_context}

TRECHOS JÁ EXTRAÍDOS DA APOSTILA (referências bibliográficas, dicas de
leitura e o enunciado do desafio prático):
{insights_context}

TAREFA:
Produza uma análise completa, dividida por assunto, cobrindo (quando o
material correspondente existir):
1. Análise da apostila — resumo aprofundado, conceitos-chave, pontos de
   atenção, conexões entre os temas.
2. Análise do livro (se houver) — complementando a apostila, sem repetir
   o que já foi dito.
3. Análise do podcast (audiodescrição) — principais ideias e como se
   relacionam com a apostila.
4. Análise de outros materiais (se houver).
5. Análise das referências bibliográficas — para cada referência, traga o
   conteúdo técnico do assunto que ela aborda (conceitos, técnicas,
   definições, exemplos), não um parágrafo genérico de "por que foi
   indicada". Não invente citações literais nem afirmações sobre o que a
   obra exata "diz" — fique no nível do assunto geral que ela cobre.
6. Análise das dicas/indicações de leitura — como aproveitá-las.
7. Análise e RESOLUÇÃO do desafio prático — explique seu raciocínio passo
   a passo e entregue a resolução completa, fundamentada no material.
8. Uma síntese geral conectando todos os pontos acima.

Não invente conteúdo que não esteja no material fornecido; quando faltar
informação para alguma seção (ex: não há livro nesta rodada), diga isso
brevemente na seção correspondente em vez de inventar.

ATENÇÃO — OBRIGATÓRIO: as 8 seções acima são TODAS obrigatórias e
independentes entre si. Produza TODAS elas, na íntegra, mesmo que o texto
da seção 5 fique mais longo que o das outras — não deixe de desenvolver
qualquer uma das demais (1, 2, 3, 4, 6, 7, 8) por causa disso. Uma resposta
que preencha só uma das chaves do JSON e deixe as outras vazias está
ERRADA, mesmo que o material daquela seção esteja ótimo.

FORMATO DA RESPOSTA:
Responda APENAS com um objeto JSON válido, sem markdown, com exatamente
estas chaves (use string vazia "" se genuinamente não houver o que dizer
em alguma):
{{
{_ANALYSIS_JSON_SCHEMA_HINT}
}}
"""


def build_section_extraction_prompt(*, section_label: str, apostila_text: str) -> str:
    """Prompt de fallback: pede à IA para extrair uma seção específica da
    apostila quando a extração heurística (regex por cabeçalhos) não
    encontrou nada com confiança suficiente.
    """
    return f"""IMPORTANTE: responda exclusivamente em Português do Brasil (pt-BR).

Leia o texto da apostila abaixo e extraia literalmente (ou resuma de
forma fiel, se o conteúdo estiver espalhado) a seção "{section_label}".

Se a apostila genuinamente não contiver essa seção, responda apenas com:
{{"encontrado": false, "conteudo": ""}}

Caso contrário, responda apenas com:
{{"encontrado": true, "conteudo": "texto extraído/resumido aqui"}}

TEXTO DA APOSTILA:
{apostila_text}
"""

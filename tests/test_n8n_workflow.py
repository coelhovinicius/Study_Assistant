"""Trava a estrutura de n8n/study_assistant_ai_cascade.json — o workflow
que o usuário importa no n8n, no mesmo padrão do Doc_QA_Generation_HA:

* cascata Gemini -> Groq -> Groq 2 -> Mistral -> OpenAI -> Groq 3;
* cada IA passa por um nó "JSON ..." que confere o formato e as chaves que
  o app pediu; resposta ruim vai pra próxima IA;
* erro 5xx espera 5s e tenta a MESMA IA de novo (até 2 vezes);
* só depois da última IA falhar é que responde 502 com o motivo.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_WORKFLOW_PATH = Path(__file__).resolve().parent.parent / "n8n" / "study_assistant_ai_cascade.json"
_WEBHOOK = "Webhook - Cascata IA"
_CASCADE = ["Gemini Chain", "Groq Chain", "Groq Chain1", "Mistral Chain", "OpenAI Chain", "Groq Chain2"]


@pytest.fixture(scope="module")
def workflow() -> dict:
    return json.loads(_WORKFLOW_PATH.read_text(encoding="utf-8"))


def _outputs(workflow: dict, node: str) -> list[list[str]]:
    return [[link["node"] for link in output] for output in workflow["connections"][node]["main"]]


def _node(workflow: dict, name: str) -> dict:
    return next(n for n in workflow["nodes"] if n["name"] == name)


def test_toda_conexao_aponta_para_um_no_que_existe(workflow: dict) -> None:
    names = {n["name"] for n in workflow["nodes"]}
    for source, kinds in workflow["connections"].items():
        assert source in names
        for outputs in kinds.values():
            for output in outputs:
                for link in output:
                    assert link["node"] in names, f"{source} -> {link['node']}"


def test_cascata_na_ordem_do_doc_qa(workflow: dict) -> None:
    assert _outputs(workflow, _WEBHOOK) == [[_CASCADE[0]]]
    for current, following in zip(_CASCADE, _CASCADE[1:] + ["Responder Erro"]):
        assert _outputs(workflow, current) == [[f"JSON {current}"], [f"Erro 5xx? ({current})"]]
        assert _outputs(workflow, f"JSON {current}") == [["Responder Sucesso"], [following]]
        assert _outputs(workflow, f"Erro 5xx? ({current})") == [[f"Aguardar 5s ({current})"], [following]]
        assert _outputs(workflow, f"Aguardar 5s ({current})") == [[current]]


def test_prompt_vem_sempre_do_webhook(workflow: dict) -> None:
    """Quando uma chain é chamada pela saída de erro de um nó "JSON ...", o
    item que chega é a resposta ruim da IA anterior (sem o body do pedido)
    — por isso o prompt é lido direto do Webhook, e não de $json."""
    for chain in _CASCADE:
        assert _WEBHOOK in _node(workflow, chain)["parameters"]["text"]


def test_no_json_usa_as_chaves_que_o_app_manda(workflow: dict) -> None:
    for chain in _CASCADE:
        code = _node(workflow, f"JSON {chain}")["parameters"]["jsCode"]
        assert "chaves_obrigatorias" in code
        assert "formato" in code


def test_groq_3_e_a_ultima_tentativa(workflow: dict) -> None:
    model = _node(workflow, "Groq Model2")
    assert model["parameters"]["model"] == "openai/gpt-oss-20b"
    assert model["credentials"]["groqApi"]["name"] == "Groq account 3"

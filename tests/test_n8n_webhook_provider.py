"""Testes do provedor que delega para o webhook n8n
(infrastructure/ai_providers/n8n_webhook_provider.py) — sem nenhuma chamada
de rede de verdade, só `requests.post` trocado por um dublê via monkeypatch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from study_assistant.domain.exceptions import AIProviderError
from study_assistant.infrastructure.ai_providers.n8n_webhook_provider import N8nWebhookProvider


@dataclass
class _FakeResponse:
    status_code: int = 200
    _json: Any = None
    text: str = ""
    _raise_on_json: bool = False

    def json(self) -> Any:
        if self._raise_on_json:
            raise ValueError("corpo não é JSON")
        return self._json


@dataclass
class _FakePost:
    """Dublê de `requests.post`: grava a última chamada e devolve uma
    resposta pré-programada, na ordem em que forem enfileiradas."""

    responses: list[_FakeResponse] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    def __call__(self, url: str, json: Any, headers: dict, timeout: float) -> _FakeResponse:
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return self.responses.pop(0)


def _provider(**kwargs: Any) -> N8nWebhookProvider:
    return N8nWebhookProvider(webhook_url="https://n8n.example.com/webhook/study", **kwargs)


def test_extrai_texto_do_campo_output(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_post = _FakePost([_FakeResponse(200, {"output": '{"ok": true}'})])
    monkeypatch.setattr("requests.post", fake_post)

    result = _provider().generate("pergunta")

    assert result == '{"ok": true}'
    assert fake_post.calls[0]["json"] == {"prompt": "pergunta"}


def test_extrai_texto_do_campo_response_aninhado(monkeypatch: pytest.MonkeyPatch) -> None:
    # Formato que o chainLlm do n8n costuma devolver quando não tem
    # Output Parser: {"response": {"text": "..."}}.
    fake_post = _FakePost([_FakeResponse(200, {"response": {"text": "resposta aninhada"}})])
    monkeypatch.setattr("requests.post", fake_post)

    assert _provider().generate("pergunta") == "resposta aninhada"


def test_aceita_string_pura_como_corpo(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_post = _FakePost([_FakeResponse(200, "resposta crua")])
    monkeypatch.setattr("requests.post", fake_post)

    assert _provider().generate("pergunta") == "resposta crua"


def test_aceita_corpo_nao_json_como_texto_puro(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_post = _FakePost([_FakeResponse(200, None, text="texto cru sem JSON", _raise_on_json=True)])
    monkeypatch.setattr("requests.post", fake_post)

    assert _provider().generate("pergunta") == "texto cru sem JSON"


def test_objeto_sem_campo_conhecido_cai_para_json_bruto(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_post = _FakePost([_FakeResponse(200, {"algo_inesperado": "valor"})])
    monkeypatch.setattr("requests.post", fake_post)

    result = _provider().generate("pergunta")

    assert "algo_inesperado" in result
    assert "valor" in result


def test_erro_no_corpo_vira_ai_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_post = _FakePost([_FakeResponse(200, {"error": "todos os provedores falharam"})])
    monkeypatch.setattr("requests.post", fake_post)

    with pytest.raises(AIProviderError):
        _provider().generate("pergunta")


def test_http_erro_vira_ai_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_post = _FakePost([_FakeResponse(502, None, text="Bad Gateway")])
    monkeypatch.setattr("requests.post", fake_post)

    with pytest.raises(AIProviderError):
        _provider().generate("pergunta")


def test_envia_headers_de_autenticacao_quando_configurados(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_post = _FakePost([_FakeResponse(200, {"output": "ok"})])
    monkeypatch.setattr("requests.post", fake_post)

    _provider(auth_header_name="X-Auth", auth_header_value="segredo").generate("pergunta")

    assert fake_post.calls[0]["headers"]["X-Auth"] == "segredo"


def test_nao_envia_header_de_auth_quando_nao_configurado(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_post = _FakePost([_FakeResponse(200, {"output": "ok"})])
    monkeypatch.setattr("requests.post", fake_post)

    _provider().generate("pergunta")

    headers = fake_post.calls[0]["headers"]
    assert list(headers.keys()) == ["Content-Type"]


def test_provider_name_e_n8n() -> None:
    assert _provider().provider_name == "n8n"

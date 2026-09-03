"""Testes de infrastructure/persistence/turso_client.py — sem nenhuma
chamada de rede de verdade, só `requests.post` trocado por um dublê via
monkeypatch (mesmo padrão de test_n8n_webhook_provider.py).

Foco principal: confirmar que `execute_batch` manda TODAS as instruções
recebidas num único request HTTP (um único item em `fake_post.calls`, com
uma entrada "execute" por instrução dentro do payload) — é essa a
otimização que resolveu o "Salvar no histórico" levando minutos com
sessões de vários materiais. Também confirma que `execute` (usado por
código que só precisa de uma instrução por vez) continua se comportando
como antes, agora por baixo dos panos delegando pra `execute_batch`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from study_assistant.domain.exceptions import RepositoryError
from study_assistant.infrastructure.persistence.turso_client import TursoHttpClient


@dataclass
class _FakeResponse:
    status_code: int = 200
    _json: Any = None
    text: str = ""

    def json(self) -> Any:
        return self._json


@dataclass
class _FakePost:
    responses: list[_FakeResponse] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    def __call__(self, url: str, json: Any, headers: dict, timeout: float) -> _FakeResponse:
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return self.responses.pop(0)


def _client() -> TursoHttpClient:
    return TursoHttpClient("libsql://minha-base.turso.io", "token-fake")


def _execute_result(cols: list[str], rows: list[list[dict]], affected: int = 0) -> dict:
    return {
        "type": "ok",
        "response": {
            "result": {
                "cols": [{"name": c} for c in cols],
                "rows": rows,
                "affected_row_count": affected,
            }
        },
    }


def test_execute_batch_manda_todas_as_instrucoes_num_unico_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_post = _FakePost(
        [
            _FakeResponse(
                200,
                {
                    "results": [
                        _execute_result([], [], affected=1),
                        _execute_result([], [], affected=3),
                        _execute_result([], [], affected=1),
                        {"type": "ok"},  # entrada correspondente ao "close"
                    ]
                },
            )
        ]
    )
    monkeypatch.setattr("requests.post", fake_post)

    results = _client().execute_batch(
        [
            ("DELETE FROM sa_provider_attempts WHERE session_id = ?", ["s1"]),
            ("DELETE FROM sa_materials WHERE session_id = ?", ["s1"]),
            ("DELETE FROM sa_study_sessions WHERE id = ?", ["s1"]),
        ]
    )

    # Só UM request HTTP pras 3 instruções — esse é o ponto da otimização.
    assert len(fake_post.calls) == 1

    payload = fake_post.calls[0]["json"]
    assert [r["type"] for r in payload["requests"]] == ["execute", "execute", "execute", "close"]
    assert [r["stmt"]["sql"] for r in payload["requests"][:3]] == [
        "DELETE FROM sa_provider_attempts WHERE session_id = ?",
        "DELETE FROM sa_materials WHERE session_id = ?",
        "DELETE FROM sa_study_sessions WHERE id = ?",
    ]

    # E os resultados voltam na mesma ordem das instruções enviadas.
    assert [r.affected_row_count for r in results] == [1, 3, 1]


def test_execute_delega_para_execute_batch_com_uma_instrucao_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_post = _FakePost(
        [
            _FakeResponse(
                200,
                {
                    "results": [
                        _execute_result(
                            ["id", "title"], [[{"type": "text", "value": "s1"}, {"type": "text", "value": "Título"}]]
                        ),
                        {"type": "ok"},
                    ]
                },
            )
        ]
    )
    monkeypatch.setattr("requests.post", fake_post)

    result = _client().execute("SELECT id, title FROM sa_study_sessions WHERE id = ?", ["s1"])

    assert len(fake_post.calls) == 1
    assert result.first() == {"id": "s1", "title": "Título"}


def test_execute_batch_com_lista_vazia_nao_faz_request(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_post = _FakePost([])
    monkeypatch.setattr("requests.post", fake_post)

    assert _client().execute_batch([]) == []
    assert fake_post.calls == []


def test_execute_batch_propaga_erro_do_turso_numa_das_instrucoes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_post = _FakePost(
        [
            _FakeResponse(
                200,
                {
                    "results": [
                        _execute_result([], [], affected=1),
                        {"type": "error", "error": {"message": "UNIQUE constraint failed"}},
                        {"type": "ok"},
                    ]
                },
            )
        ]
    )
    monkeypatch.setattr("requests.post", fake_post)

    with pytest.raises(RepositoryError, match="UNIQUE constraint failed"):
        _client().execute_batch(
            [
                ("INSERT INTO a VALUES (1)", None),
                ("INSERT INTO a VALUES (1)", None),
            ]
        )


def test_execute_batch_com_resposta_http_de_erro_levanta_repository_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_post = _FakePost([_FakeResponse(500, text="internal error")])
    monkeypatch.setattr("requests.post", fake_post)

    with pytest.raises(RepositoryError, match="HTTP 500"):
        _client().execute_batch([("SELECT 1", None)])


def test_execute_batch_com_resposta_incompleta_levanta_repository_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Se o Turso devolver menos resultados do que instruções enviadas
    (resposta truncada/malformada), isso não pode ser confundido
    silenciosamente com sucesso."""
    fake_post = _FakePost([_FakeResponse(200, {"results": [_execute_result([], [])]})])
    monkeypatch.setattr("requests.post", fake_post)

    with pytest.raises(RepositoryError, match="incompleta"):
        _client().execute_batch([("SELECT 1", None), ("SELECT 2", None)])

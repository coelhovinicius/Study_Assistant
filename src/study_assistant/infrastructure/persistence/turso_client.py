"""Cliente HTTP mínimo para o Turso (SQLite servido via HTTP / API "v2/pipeline").

Implementado com ``requests`` puro, seguindo a API oficial documentada em
https://docs.turso.tech/sdk/http/quickstart, em vez de depender de um SDK
específico — assim o projeto tem uma única dependência estável (requests)
para falar com o banco, fácil de auditar e sem risco de quebrar por causa
de mudanças de API de um pacote de terceiros ainda em evolução rápida.

Este cliente é deliberadamente pequeno: expõe só o que os repositórios da
aplicação precisam. ``execute_batch`` manda várias instruções SQL numa
ÚNICA requisição HTTP (o pipeline do Turso aceita uma lista de
instruções por request) — é o que ``execute`` usa por baixo dos panos
para uma instrução só. Isso importa pra latência: salvar uma sessão com
vários materiais e várias tentativas de provider, por exemplo, virava uma
requisição HTTP separada pra CADA linha (e cada uma paga o round-trip de
rede inteiro, não só o tempo de banco) — o que fazia o "Salvar no
histórico" demorar minutos com sessões maiores. Cada chamada (de
``execute`` ou ``execute_batch``) abre e fecha sua própria conexão lógica
no Turso (via o campo ``{"type": "close"}`` ao final do pipeline) — não
há transação multi-statement nem reaproveitamento de "baton" entre
chamadas diferentes, o que é suficiente para o volume de uso de um app
pessoal (dentro de uma mesma chamada, as instruções do pipeline rodam em
sequência no mesmo request).
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from typing import Any, Sequence

import requests

from study_assistant.domain.exceptions import RepositoryError

logger = logging.getLogger(__name__)


@dataclass
class TursoQueryResult:
    """Resultado de uma única instrução SQL executada no Turso."""

    columns: list[str]
    rows: list[dict[str, Any]] = field(default_factory=list)
    affected_row_count: int = 0
    last_insert_rowid: int | None = None

    def first(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None


def _to_turso_arg(value: Any) -> dict[str, Any]:
    """Converte um valor Python para o formato de argumento esperado pelo Turso."""
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "integer", "value": str(int(value))}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    if isinstance(value, (bytes, bytearray)):
        return {"type": "blob", "value": base64.b64encode(bytes(value)).decode("ascii")}
    return {"type": "text", "value": str(value)}


def _from_turso_cell(cell: dict[str, Any]) -> Any:
    """Converte uma célula retornada pelo Turso de volta para um valor Python."""
    cell_type = cell.get("type")
    raw_value = cell.get("value")
    if cell_type == "null" or raw_value is None:
        return None
    if cell_type == "integer":
        return int(raw_value)
    if cell_type == "float":
        return float(raw_value)
    if cell_type == "blob":
        return base64.b64decode(raw_value)
    return raw_value  # "text" e qualquer outro caso caem aqui como string


class TursoHttpClient:
    """Cliente HTTP para um banco Turso, usado como storage compartilhado do app."""

    def __init__(self, database_url: str, auth_token: str, timeout_seconds: float = 30.0) -> None:
        if not database_url or not auth_token:
            raise RepositoryError(
                "URL e token do Turso são obrigatórios. Configure "
                "st.secrets['turso']['database_url'] e ['auth_token']."
            )
        self._pipeline_url = self._build_pipeline_url(database_url)
        self._auth_token = auth_token
        self._timeout_seconds = timeout_seconds

    @staticmethod
    def _build_pipeline_url(database_url: str) -> str:
        url = database_url.strip()
        if url.startswith("libsql://"):
            url = "https://" + url[len("libsql://") :]
        return url.rstrip("/") + "/v2/pipeline"

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> TursoQueryResult:
        """Executa uma única instrução SQL (SELECT, INSERT, UPDATE, DELETE, DDL)."""
        return self.execute_batch([(sql, params)])[0]

    def execute_batch(
        self, statements: Sequence[tuple[str, Sequence[Any] | None]]
    ) -> list[TursoQueryResult]:
        """Executa várias instruções SQL em UMA única requisição HTTP (o
        pipeline do Turso aceita uma lista de instruções por request), na
        ordem em que foram passadas. Os resultados voltam na mesma ordem.

        Não há rollback automático entre as instruções do batch — se uma
        falhar no meio, as anteriores já foram aplicadas (mesma semântica
        que chamar ``execute`` várias vezes em sequência; a diferença é só
        que tudo trafega num request HTTP só, em vez de um por instrução).
        """
        if not statements:
            return []

        requests_payload: list[dict[str, Any]] = [
            {
                "type": "execute",
                "stmt": {
                    "sql": sql,
                    "args": [_to_turso_arg(p) for p in (params or [])],
                },
            }
            for sql, params in statements
        ]
        requests_payload.append({"type": "close"})

        try:
            response = requests.post(
                self._pipeline_url,
                json={"requests": requests_payload},
                headers={
                    "Authorization": f"Bearer {self._auth_token}",
                    "Content-Type": "application/json",
                },
                timeout=self._timeout_seconds,
            )
        except requests.RequestException as exc:
            raise RepositoryError(f"Falha de rede ao acessar o Turso: {exc}") from exc

        if response.status_code >= 400:
            raise RepositoryError(
                f"Turso retornou HTTP {response.status_code} para um pipeline de "
                f"{len(statements)} instrução(ões) SQL: {response.text[:500]}"
            )

        body = response.json()
        results = body.get("results", [])
        if len(results) < len(statements):
            raise RepositoryError(
                f"Resposta do Turso incompleta: esperava {len(statements)} "
                f"resultado(s), vieram {len(results)}."
            )

        return [self._parse_result(result) for result in results[: len(statements)]]

    @staticmethod
    def _parse_result(result: dict[str, Any]) -> TursoQueryResult:
        if result.get("type") == "error":
            error = result.get("error", {})
            raise RepositoryError(
                f"Erro do Turso ao executar SQL: {error.get('message', error)}"
            )

        execute_result = result.get("response", {}).get("result", {})
        columns = [c.get("name", "") for c in execute_result.get("cols", [])]
        rows = [
            {columns[i]: _from_turso_cell(cell) for i, cell in enumerate(row)}
            for row in execute_result.get("rows", [])
        ]

        return TursoQueryResult(
            columns=columns,
            rows=rows,
            affected_row_count=execute_result.get("affected_row_count", 0) or 0,
            last_insert_rowid=execute_result.get("last_insert_rowid"),
        )

    def execute_script(self, statements: Sequence[tuple[str, Sequence[Any] | None]]) -> None:
        """Executa várias instruções (ex: criação do schema inicial) num único
        pipeline HTTP — alias de conveniência para ``execute_batch`` que
        descarta os resultados."""
        self.execute_batch(statements)

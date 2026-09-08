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
import binascii
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

import requests

from study_assistant.domain.exceptions import RepositoryError

logger = logging.getLogger(__name__)

# Quantas vezes tentar de novo o pipeline INTEIRO se um blob vier com um
# comprimento que nem _pad_base64 consegue corrigir (módulo 4 igual a 1 —
# ver _pad_base64). ATUALIZAÇÃO depois de investigar a fundo com
# scripts/diagnosticar_leitura_pdf.py contra o banco de produção: a causa
# do "blob truncado" NUNCA foi rede/proxy/antivírus cortando a resposta —
# era o Turso devolvendo o base64 sem o padding final (redundante por
# natureza, dá pra calcular quantos "=" faltam só pelo tamanho da string),
# e base64.b64decode do Python sendo estrito quanto a isso. Confirmado com
# 7 de 7 valores reais observados (tamanhos bem diferentes) tendo
# comprimento módulo 4 igual a 2 ou 3 — exatamente os dois únicos restos
# possíveis quando falta padding, nunca o resto 1 que uma corrupção de
# verdade (aleatória) produziria com chance razoável. Isso já é corrigido
# direto no decode (_pad_base64), sem precisar de nova tentativa nenhuma —
# esta constante e a nova tentativa abaixo ficam só como rede de segurança
# pro caso raro (zero instâncias confirmadas até agora) de uma corrupção
# de verdade, não relacionada a padding.
_MAX_BLOB_RETRIES = 2


class _BlobDecodeError(Exception):
    """Sinal interno (de propósito NÃO é RepositoryError): um valor blob
    veio com comprimento módulo 4 igual a 1 depois de tentar completar o
    padding — o único caso em que _pad_base64 não sabe o que fazer, porque
    não existe base64 válido (com ou sem padding) nesse formato. Na
    prática, quase todo "blob truncado" real era só falta de padding
    (corrigida antes de chegar aqui, ver _pad_base64) — isto agora cobre
    só a sobra: uma corrupção de verdade. ``execute_batch`` tenta o
    pipeline de novo antes de desistir, como rede de segurança pra esse
    caso raro. Nunca escapa deste módulo: ou uma tentativa seguinte
    decodifica direito, ou vira RepositoryError no final."""


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
        # Único tipo em que o Turso NÃO usa a chave "value" — é "base64"
        # mesmo (documentado em https://docs.turso.tech/sdk/http/reference).
        # Mandar como "value" (erro anterior) faz o Turso recusar a
        # requisição inteira com HTTP 400 "missing field `base64`" — foi
        # exatamente o que aconteceu ao salvar o primeiro PDF no histórico,
        # porque nenhum teste existente mandava bytes de verdade por aqui
        # (só instruções com params de texto/None — ver test_turso_client.py).
        return {"type": "blob", "base64": base64.b64encode(bytes(value)).decode("ascii")}
    return {"type": "text", "value": str(value)}


def _pad_base64(encoded: str) -> str:
    """Repõe o padding final ('=' / '==') que o Turso, na prática, às vezes
    NÃO manda de volta — confirmado rodando scripts/diagnosticar_leitura_pdf.py
    contra o banco de verdade: um blob de 100 bytes ALEATÓRIOS (nada de PDF,
    nada de rede corporativa envolvida na explicação) voltou com exatamente
    134 caracteres, e 134 é EXATAMENTE o comprimento de 100 bytes em base64
    SEM os 2 caracteres de padding finais (136 - 2 = 134). Os outros casos
    reais que já tinham aparecido (28875, 24254, 33074, 1334 e 6667
    caracteres) também batem: todos com comprimento módulo 4 igual a 2 ou 3
    — exatamente os dois únicos restos possíveis quando falta padding
    (nunca resto 1, que seria impossível pra um base64 válido, com ou sem
    padding). Ou seja: os dados nunca estiveram truncados/cortados — só
    faltava o padding, que é puramente redundante (dá pra calcular quantos
    "=" faltam só pelo tamanho da string) e o base64.b64decode do Python é
    estrito quanto a isso.

    Resto 1 (mod 4) é o único caso em que NÃO dá pra saber quanto
    completar — não é um "falta padding", é uma string que não pode ser
    base64 válido de jeito nenhum (nem com nem sem padding). Nesse caso não
    mexe: deixa cair no decode original e virar o erro de sempre, em vez de
    arriscar completar errado e decodificar silenciosamente pra bytes
    incorretos.
    """
    remainder = len(encoded) % 4
    if remainder in (2, 3):
        return encoded + "=" * (4 - remainder)
    return encoded


def _from_turso_cell(cell: dict[str, Any]) -> Any:
    """Converte uma célula retornada pelo Turso de volta para um valor Python."""
    cell_type = cell.get("type")
    if cell_type == "blob":
        # Mesma particularidade do lado de envio: aceita "base64" (chave
        # documentada) OU "value" (caso o Turso devolva no outro formato em
        # alguma versão da API) — não vale a pena arriscar um None
        # silencioso aqui por causa de um nome de campo.
        encoded = cell.get("base64", cell.get("value"))
        if encoded is None:
            return None
        try:
            return base64.b64decode(_pad_base64(encoded))
        except (binascii.Error, ValueError) as exc:
            # NUNCA deixa um valor blob malformado derrubar a página inteira
            # (era exatamente isso que acontecia antes: binascii.Error sem
            # tratamento estourava até o Streamlit, tela branca). Vira
            # _BlobDecodeError — execute_batch tenta o pipeline de novo
            # algumas vezes antes de desistir (ver _MAX_BLOB_RETRIES); só se
            # todas as tentativas falharem é que vira RepositoryError de
            # verdade, o mesmo tipo que session_repository.get() já propaga
            # pra history_page.py, que já sabe mostrar isso como erro na
            # tela em vez de quebrar (ver _show_repository_error). A
            # mensagem carrega tamanho + prefixo do valor recebido de
            # propósito: se acontecer mesmo depois das tentativas, o
            # "Detalhes técnicos" já expostos na tela trazem o que precisamos.
            preview = encoded[:24] if isinstance(encoded, str) else repr(encoded)[:24]
            length = len(encoded) if isinstance(encoded, str) else "desconhecido"
            raise _BlobDecodeError(
                "Valor blob vindo do Turso não é base64 válido "
                f"({exc}). Tamanho recebido: {length} caractere(s). "
                f"Começa com: {preview!r}."
            ) from exc
    raw_value = cell.get("value")
    if cell_type == "null" or raw_value is None:
        return None
    if cell_type == "integer":
        return int(raw_value)
    if cell_type == "float":
        return float(raw_value)
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

        Se um valor blob vier com padding faltando, isso já é corrigido
        direto no decode (ver ``_pad_base64``) — nenhuma nova tentativa
        acontece pra esse caso, que é o comum. Só se sobrar um comprimento
        que nem isso resolve (``_BlobDecodeError``, ver esse comentário) o
        pipeline INTEIRO é tentado de novo (até ``_MAX_BLOB_RETRIES`` vezes
        extras) antes de desistir, como rede de segurança pra uma
        corrupção de verdade.
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

        last_blob_error: _BlobDecodeError | None = None
        for attempt in range(_MAX_BLOB_RETRIES + 1):
            if attempt > 0:
                logger.warning(
                    "Valor blob com comprimento inválido mesmo depois de completar "
                    "o padding (possível corrupção de verdade, não o caso comum de "
                    "padding faltando) — tentando de novo (tentativa %d de %d)...",
                    attempt + 1,
                    _MAX_BLOB_RETRIES + 1,
                )
                time.sleep(0.4)

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

            try:
                return [self._parse_result(result) for result in results[: len(statements)]]
            except _BlobDecodeError as exc:
                last_blob_error = exc
                continue

        assert last_blob_error is not None  # só sai do loop sem return por aqui
        raise RepositoryError(str(last_blob_error)) from last_blob_error

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

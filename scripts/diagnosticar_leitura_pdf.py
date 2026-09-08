#!/usr/bin/env python3
"""Isola, sem o Streamlit e sem a nova-tentativa automática do app, duas
perguntas concretas sobre o "blob truncado" ao ler pdf_bytes do Turso:

  (a) É TAMANHO ou é CONTEÚDO? Grava e lê de volta bytes ALEATÓRIOS (nada
      que "pareça" um PDF) em vários tamanhos, dos bem pequenos até bem
      maiores que os PDFs que já falharam. Se até bytes aleatórios grandes
      falharem, o problema é tamanho, ponto — não tem nada a ver com ser
      PDF. Se bytes aleatórios passarem em todos os tamanhos mas o PDF de
      verdade (parte 2) continuar falhando, é o CONTEÚDO (algo reconhece o
      formato de um PDF e mexe só nesse tráfego) — não o tamanho puro.

  (b) É determinístico ou intermitente? Faz 5 tentativas SEPARADAS (uma
      requisição HTTP por tentativa, sem a nova-tentativa automática que o
      turso_client.py já tem) lendo a sessão real mais recente com PDF
      salvo. Falhar 5 de 5 é bem diferente de falhar 1 ou 2 de 5.

Isso NÃO prova sozinho se a causa é deste computador/rede ou é do lado do
Turso/código — só rodar essa mesma leitura de FORA desta máquina (o app
publicado no Streamlit Community Cloud é o jeito mais simples) resolve
essa parte. Mas já reduz bastante o campo de hipóteses antes disso.

Uso:
    python scripts/diagnosticar_leitura_pdf.py [--secrets .streamlit/secrets.toml] [--manter]

Seguro de rodar: a parte (a) usa uma linha de teste com id fixo e
reservado ("__diagnostico_leitura_pdf__", título "Diagnóstico (pode
apagar)"), apagada no final — a menos que --manter seja passado. A parte
(b) só LÊ uma sessão real que já existia, nunca grava nada nela.
"""

from __future__ import annotations

import argparse
import os
import time

import requests

from _common import add_src_to_path, load_toml_secrets

add_src_to_path()

from study_assistant.config.settings import load_settings  # noqa: E402
from study_assistant.domain.exceptions import RepositoryError  # noqa: E402
from study_assistant.infrastructure.persistence.turso_client import (  # noqa: E402
    TursoHttpClient,
    _BlobDecodeError,
    _from_turso_cell,
    _to_turso_arg,
)

_DIAG_ID = "__diagnostico_leitura_pdf__"

# Os 3 casos reais que já falharam tinham, em bytes crus (antes do
# base64), aproximadamente 21.700, 18.200 e 24.800 bytes — a escada abaixo
# é mais fina bem nessa faixa (15k-30k) e mais grossa longe dela, pra tentar
# localizar onde exatamente (se for tamanho) a coisa quebra.
_TAMANHOS_TESTE = [
    100,
    1_000,
    5_000,
    10_000,
    15_000,
    20_000,
    25_000,
    30_000,
    50_000,
    100_000,
    300_000,
]


def _raw_select_pdf_bytes(pipeline_url: str, auth_token: str, session_id: str):
    """UMA requisição HTTP crua (sem repetir sozinha em caso de falha) —
    pra ver o resultado de cada tentativa individual, em vez da
    nova-tentativa automática do TursoHttpClient esconder quantas
    tentativas internas falharam antes de uma dar certo."""
    payload = {
        "requests": [
            {
                "type": "execute",
                "stmt": {
                    "sql": "SELECT pdf_bytes FROM sa_study_sessions WHERE id = ?",
                    "args": [_to_turso_arg(session_id)],
                },
            },
            {"type": "close"},
        ]
    }
    response = requests.post(
        pipeline_url,
        json=payload,
        headers={"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"},
        timeout=30.0,
    )
    response.raise_for_status()
    result = response.json()["results"][0]
    if result.get("type") == "error":
        raise RepositoryError(str(result.get("error")))
    rows = result.get("response", {}).get("result", {}).get("rows", [])
    if not rows or not rows[0]:
        return None
    return _from_turso_cell(rows[0][0])  # levanta _BlobDecodeError se vier truncado


def _testar_tamanho(client: TursoHttpClient, tamanho: int) -> tuple[bool, str]:
    dados = os.urandom(tamanho)
    try:
        client.execute(
            """
            INSERT INTO sa_study_sessions (id, title, created_at, pdf_bytes)
            VALUES (?, 'Diagnóstico (pode apagar)', '2000-01-01T00:00:00', ?)
            ON CONFLICT(id) DO UPDATE SET pdf_bytes = excluded.pdf_bytes
            """,
            [_DIAG_ID, dados],
        )
        resultado = client.execute(
            "SELECT pdf_bytes FROM sa_study_sessions WHERE id = ?", [_DIAG_ID]
        )
    except RepositoryError as exc:
        return False, f"{tamanho:>7} bytes: FALHOU — {exc}"

    linha = resultado.first()
    lido = linha.get("pdf_bytes") if linha else None
    if lido == dados:
        return True, f"{tamanho:>7} bytes: OK (foi e voltou idêntico)"
    if not lido:
        return False, f"{tamanho:>7} bytes: FALHOU (voltou vazio/nulo)"
    return False, f"{tamanho:>7} bytes: FALHOU (voltou {len(lido)} de {tamanho} bytes, não bateu)"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--secrets", default=".streamlit/secrets.toml")
    parser.add_argument("--manter", action="store_true", help="não apaga a linha de teste no final")
    args = parser.parse_args()

    secrets = load_toml_secrets(args.secrets)
    settings = load_settings(secrets)
    client = TursoHttpClient(settings.turso.database_url, settings.turso.auth_token)
    pipeline_url = TursoHttpClient._build_pipeline_url(settings.turso.database_url)

    print("=" * 72)
    print("PARTE 1 — bytes ALEATÓRIOS (sem nada de PDF) em vários tamanhos")
    print("=" * 72)
    print(
        "Testa se o problema é só tamanho, ou se é específico de conteúdo\n"
        "que 'parece' um PDF de verdade.\n"
    )
    algum_falhou = False
    primeiro_tamanho_que_falhou = None
    for tamanho in _TAMANHOS_TESTE:
        ok, linha = _testar_tamanho(client, tamanho)
        print(linha)
        if not ok:
            algum_falhou = True
            if primeiro_tamanho_que_falhou is None:
                primeiro_tamanho_que_falhou = tamanho

    if not args.manter:
        try:
            client.execute("DELETE FROM sa_study_sessions WHERE id = ?", [_DIAG_ID])
        except RepositoryError as exc:
            print(f"\n(Aviso: não consegui apagar a linha de teste sozinho: {exc})")
            print(f"Pode apagar manualmente depois: DELETE FROM sa_study_sessions WHERE id = '{_DIAG_ID}';")

    print()
    print("=" * 72)
    print("PARTE 2 — a sessão REAL mais recente com PDF, 5 tentativas SEPARADAS")
    print("(cada uma é 1 requisição HTTP só, sem repetir sozinha)")
    print("=" * 72)
    recente = client.execute(
        "SELECT id, title, length(pdf_bytes) as tamanho FROM sa_study_sessions "
        "WHERE pdf_bytes IS NOT NULL ORDER BY created_at DESC LIMIT 1"
    ).first()

    sucessos = 0
    if recente is None:
        print("Nenhuma sessão com PDF salvo encontrada — salve uma no app primeiro.")
    else:
        print(f"Sessão: {recente['title']!r} (id={recente['id']}, {recente['tamanho']} bytes no banco)\n")
        for tentativa in range(1, 6):
            try:
                valor = _raw_select_pdf_bytes(pipeline_url, settings.turso.auth_token, recente["id"])
                tamanho_lido = len(valor) if valor else 0
                print(f"  tentativa {tentativa}/5: OK ({tamanho_lido} bytes decodificados)")
                sucessos += 1
            except _BlobDecodeError as exc:
                print(f"  tentativa {tentativa}/5: FALHOU (blob truncado) — {exc}")
            except RepositoryError as exc:
                print(f"  tentativa {tentativa}/5: erro do Turso — {exc}")
            except requests.RequestException as exc:
                print(f"  tentativa {tentativa}/5: erro de rede — {exc}")
            time.sleep(0.5)
        print(f"\n  Resultado: {sucessos} de 5 tentativas OK.")

    print()
    print("=" * 72)
    print("COMO LER O RESULTADO")
    print("=" * 72)
    if algum_falhou:
        print(
            f"Bytes aleatórios já falharam a partir de {primeiro_tamanho_que_falhou} "
            "bytes, sem nada de PDF envolvido. Ou seja: NÃO é específico de PDF —\n"
            "é qualquer blob a partir desse tamanho. Aponta pra um limite genérico\n"
            "(do próprio Turso, ou de algo no caminho que corta qualquer resposta\n"
            "grande, não só as que 'parecem' um documento)."
        )
    else:
        print(
            f"Bytes aleatórios passaram em TODOS os tamanhos testados (até "
            f"{_TAMANHOS_TESTE[-1]} bytes).\n"
            "Se a Parte 2 (PDF real) falhou mesmo assim, isso aponta pra algo que\n"
            "trata esse tráfego de forma diferente especificamente quando reconhece\n"
            "um PDF ali dentro — inspeção de conteúdo (antivírus/DLP corporativo\n"
            "que decodifica e olha o que passa pela rede) é a explicação mais\n"
            "provável, mais do que 'qualquer coisa grande quebra'."
        )
    print(
        "\nDe qualquer forma, isso ainda não separa 'é este computador' de 'é o\n"
        "Turso ou o código' — só rodar essa mesma leitura de FORA desta máquina\n"
        "(publicar no Streamlit Community Cloud e testar 'Ver/baixar' por lá)\n"
        "resolve essa parte de vez."
    )


if __name__ == "__main__":
    main()

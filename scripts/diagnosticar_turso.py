#!/usr/bin/env python3
"""Mede, isoladamente (sem o Streamlit, sem interface nenhuma), quanto
tempo o Turso está levando pra responder NESTE computador/rede agora.

Por quê este script existe: se até uma única consulta simples (feita
direto, sem passar pelo resto do app) já demorar muito, o problema é de
rede até o Turso (ou do banco em si) — nenhum ajuste de "salvar tudo em
lote" no código do app resolve isso sozinho, porque o gargalo está antes
de chegar no código. Se essa consulta única for rápida mas o app continuar
lento, aí sim o problema é outra coisa (ex: os arquivos atualizados ainda
não foram salvos no lugar certo).

Uso:
    python scripts/diagnosticar_turso.py [--secrets .streamlit/secrets.toml]
"""

from __future__ import annotations

import argparse
import time

from _common import add_src_to_path, load_toml_secrets

add_src_to_path()

from study_assistant.config.settings import load_settings  # noqa: E402
from study_assistant.infrastructure.persistence.turso_client import TursoHttpClient  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--secrets", default=".streamlit/secrets.toml")
    args = parser.parse_args()

    secrets = load_toml_secrets(args.secrets)
    settings = load_settings(secrets)
    client = TursoHttpClient(settings.turso.database_url, settings.turso.auth_token)

    print("Turso configurado em:", settings.turso.database_url)
    print()

    print("1) Medindo 3 chamadas SEPARADAS (SELECT 1 cada) — imita o padrão")
    print("   antigo, uma requisição HTTP por instrução:")
    started_sequencial = time.perf_counter()
    for i in range(3):
        started_chamada = time.perf_counter()
        client.execute("SELECT 1")
        print(f"     chamada {i + 1}/3: {time.perf_counter() - started_chamada:.2f}s")
    total_sequencial = time.perf_counter() - started_sequencial
    print(f"   Total (3 chamadas separadas): {total_sequencial:.2f}s")
    print()

    print("2) Medindo a MESMA coisa em UM lote só (execute_batch) — é o que")
    print("   o app passa a usar depois da otimização:")
    started_lote = time.perf_counter()
    client.execute_batch([("SELECT 1", None), ("SELECT 1", None), ("SELECT 1", None)])
    total_lote = time.perf_counter() - started_lote
    print(f"   Total (1 chamada em lote): {total_lote:.2f}s")
    print()

    print("=" * 70)
    if total_lote < 2 and total_sequencial > 5:
        print(
            "Diagnóstico: o gargalo era mesmo o número de requisições HTTP —\n"
            "o lote resolve isso. Se o app ainda estiver lento depois de\n"
            "substituir os arquivos, confirme que salvou os 3 arquivos\n"
            "(turso_client.py, session_repository.py e os testes) nos\n"
            "caminhos certos e reiniciou o 'streamlit run'."
        )
    elif total_lote > 5:
        print(
            "Diagnóstico: até UMA chamada só (ou um lote de 3 numa requisição\n"
            "só) está lenta — isso não é o código do app, é a rede até o\n"
            "Turso (ou o banco em si). Vale checar, nesta ordem:\n"
            "  - conexão com a internet agora (outros sites/serviços também\n"
            "    estão lentos?);\n"
            "  - alguma VPN, proxy corporativo ou antivírus com inspeção de\n"
            "    tráfego HTTPS ativos;\n"
            "  - o status do banco no painel do Turso (https://turso.tech/app)\n"
            "    — bancos no plano gratuito podem 'dormir' e demorar mais na\n"
            "    primeira consulta depois de um tempo sem uso, mas não deveriam\n"
            "    continuar lentos depois disso."
        )
    else:
        print(
            "Os tempos parecem normais (poucos segundos ou menos). Se o app\n"
            "ainda estiver lento com os arquivos novos, pode ser outra causa —\n"
            "me manda o tempo exato que apareceu aqui pra eu investigar."
        )


if __name__ == "__main__":
    main()

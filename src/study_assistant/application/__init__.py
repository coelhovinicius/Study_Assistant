"""Camada de aplicação: casos de uso que orquestram o domínio.

Depende apenas de ``domain`` (entidades + ports). Nunca importa
diretamente ``streamlit``, ``requests``, SDKs de IA, ou qualquer outra
biblioteca de infraestrutura — tudo isso entra por injeção de dependência
(as implementações concretas vêm de ``infrastructure`` e são "encaixadas"
pelo composition root em ``presentation/di_container.py``).
"""

"""Utilitários pequenos e sem estado, compartilhados por mais de uma camada
(ex: infraestrutura de relatórios E páginas do Streamlit) sem criar uma
dependência de uma camada "de cima" para outra "de cima" — este pacote não
importa nada de ``domain``, ``application``, ``infrastructure`` nem
``presentation``, só o contrário.
"""

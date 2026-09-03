"""Study Assistant — automação pessoal de análise de materiais de estudo.

Pacote raiz da aplicação. A organização interna segue os princípios de
Clean Architecture / Ports & Adapters:

- ``domain``: entidades e contratos (interfaces) puros, sem dependências
  externas. É o núcleo estável do sistema.
- ``application``: casos de uso que orquestram o domínio. Depende apenas
  de ``domain`` (via interfaces/ports), nunca de frameworks concretos.
- ``infrastructure``: implementações concretas dos ports (banco de dados,
  provedores de IA, extração de arquivos, geração de relatórios).
- ``presentation``: interface com o usuário (Streamlit) e composição das
  dependências (injeção de dependência manual / composition root).

A regra de dependência é sempre "de fora para dentro": presentation e
infrastructure conhecem application e domain, mas domain nunca conhece
infrastructure nem presentation.
"""

__version__ = "1.0.0"

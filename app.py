"""Ponto de entrada do Streamlit. Rode com: streamlit run app.py

Este arquivo é deliberadamente fino: só ajusta o ``sys.path`` para
encontrar o pacote em ``src/`` e delega tudo para
``study_assistant.presentation.streamlit_app``. Toda a lógica real do app
vive dentro do pacote, em camadas (domain / application / infrastructure /
presentation) — ver o README para uma visão geral da arquitetura.
"""

import sys
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from study_assistant.presentation.streamlit_app import run  # noqa: E402

run()

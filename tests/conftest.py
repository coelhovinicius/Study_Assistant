"""Configuração compartilhada dos testes: garante que 'src/' esteja no
sys.path, já que o projeto não é instalado como pacote (sem setup.py/
pyproject.toml de propósito, para manter o projeto simples de rodar)."""

from __future__ import annotations

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

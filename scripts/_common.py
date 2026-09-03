"""Utilitários compartilhados pelos scripts de linha de comando (setup)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"


def add_src_to_path() -> None:
    if str(SRC_DIR) not in sys.path:
        sys.path.insert(0, str(SRC_DIR))


def load_toml_secrets(path: str) -> dict:
    try:
        import tomllib  # Python >= 3.11
    except ImportError:  # pragma: no cover
        import tomli as tomllib  # type: ignore[no-redef]

    secrets_path = Path(path)
    if not secrets_path.is_absolute():
        secrets_path = PROJECT_ROOT / secrets_path

    if not secrets_path.exists():
        raise SystemExit(
            f"Arquivo de segredos não encontrado: {secrets_path}\n"
            "Copie '.streamlit/secrets.toml.example' para '.streamlit/secrets.toml' "
            "e preencha com suas credenciais antes de rodar este script."
        )

    with open(secrets_path, "rb") as file:
        return tomllib.load(file)

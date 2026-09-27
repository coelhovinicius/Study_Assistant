"""Carregamento de configuração/segredos.

Nunca colocamos chaves de API, tokens ou senhas diretamente no código-fonte
ou no Git. Tudo vem de ``st.secrets`` (arquivo local ``.streamlit/secrets.toml``,
que fica no ``.gitignore``) ou de variáveis de ambiente equivalentes — o
mesmo padrão que o usuário já usa nos outros apps.

Este módulo não importa Streamlit diretamente: ``load_settings`` recebe
qualquer objeto do tipo mapeamento aninhado (``st.secrets`` se comporta
como um dict de dicts). Isso mantém a configuração testável sem precisar
rodar dentro do Streamlit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

# Caminho do fallback local de credenciais, no mesmo padrão usado nos
# outros apps do usuário (auth/auth_manager.py + auth/users.yaml).
# Calculado a partir deste arquivo: config/ -> study_assistant/ -> src/ -> raiz do projeto.
PROJECT_ROOT = Path(__file__).resolve().parents[3]
AUTH_YAML_PATH = PROJECT_ROOT / "auth" / "users.yaml"


@dataclass(frozen=True)
class TursoSettings:
    database_url: str
    auth_token: str


@dataclass(frozen=True)
class AuthSettings:
    """Credenciais do admin, resolvidas com a mesma prioridade usada nos
    outros apps do usuário: 1) st.secrets["auth"]; 2) auth/users.yaml local
    (fallback fora do Git). Nunca vem do Turso."""

    username: str
    password_hash: str

    @property
    def is_configured(self) -> bool:
        return bool(self.username and self.password_hash)


@dataclass(frozen=True)
class N8nSettings:
    """Configuração do webhook n8n — mesmo padrão dos outros apps do
    usuário ([n8n] webhook_url = "..."). Quando preenchido, o app usa esse
    webhook como ÚNICO elo da cascata (o n8n é quem decide, internamente,
    a ordem Gemini -> Groq -> Groq 2 -> Mistral -> OpenAI -> Groq 3 e o
    fallback entre eles) — as seções [ai.*] deixam de ser usadas nesse caso."""

    webhook_url: str
    auth_header_name: str = ""
    auth_header_value: str = ""
    # O workflow n8n tenta até 6 provedores em SEQUÊNCIA (Gemini -> Groq ->
    # Groq 2 -> Mistral -> OpenAI -> Groq 3) antes de responder — se vários
    # falharem/demorarem antes do que funciona, a soma pode passar de um
    # timeout curto. 300s (5min) dá folga; ajustável via secrets se ainda
    # não bastar.
    timeout_seconds: float = 300.0

    @property
    def is_configured(self) -> bool:
        return bool(self.webhook_url)


@dataclass(frozen=True)
class AIProviderSettings:
    """Configuração de um elo da cascata de IA."""

    kind: str  # "openai" | "gemini" | "groq" | "mistral"
    label: str
    api_key: str
    model: str

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.model)


@dataclass(frozen=True)
class AnalysisSettings:
    """Análise em lotes (ver ``application/analysis_service.py``)."""

    # Limite de texto analisado por rodada, somando todos os materiais
    # (~10 lotes). Acima disso, o resto de cada material não é analisado e
    # uma observação diz quanto ficou de fora.
    max_total_chars: int = 120_000
    # Tamanho de cada lote — o mesmo do qa_testgen, que já cabe na cota por
    # minuto das IAs gratuitas da cascata.
    batch_chars: int = 12_000
    # Por quantos dias as respostas da IA ficam salvas pra continuar uma
    # análise pausada sem pedir de novo o que já veio.
    saved_responses_days: int = 7


@dataclass(frozen=True)
class SecuritySettings:
    bcrypt_rounds: int = 12
    max_login_attempts: int = 5
    lock_minutes: int = 15


@dataclass(frozen=True)
class Settings:
    turso: TursoSettings
    auth: AuthSettings
    n8n: N8nSettings
    ai_cascade: list[AIProviderSettings] = field(default_factory=list)
    security: SecuritySettings = field(default_factory=SecuritySettings)
    analysis: AnalysisSettings = field(default_factory=AnalysisSettings)

    @property
    def configured_ai_cascade(self) -> list[AIProviderSettings]:
        """Só os provedores que de fato têm chave configurada, na ordem definida.
        Ignorado quando ``n8n.is_configured`` é True — nesse caso o n8n é
        quem decide a cascata, não o Python."""
        return [p for p in self.ai_cascade if p.is_configured]


def _get(secrets: Mapping[str, Any], *path: str, default: Any = "") -> Any:
    node: Any = secrets
    for key in path:
        if not isinstance(node, Mapping) or key not in node:
            return default
        node = node[key]
    return node


# Ordem padrão da cascata, espelhando o fluxo em n8n mostrado pelo usuário:
# OpenAI -> Gemini -> Groq (conta 1) -> Groq (conta 2) -> Mistral.
_DEFAULT_CASCADE_ORDER: tuple[tuple[str, str, str, str], ...] = (
    # (chave em [ai.*] no secrets.toml, kind, label, modelo padrão)
    ("openai", "openai", "OpenAI", "gpt-5.5"),
    ("gemini", "gemini", "Google Gemini", "gemini-2.5-flash"),
    ("groq_primary", "groq", "Groq (conta 1)", "openai/gpt-oss-120b"),
    ("groq_secondary", "groq", "Groq (conta 2)", "openai/gpt-oss-120b"),
    ("mistral", "mistral", "Mistral", "mistral-large-latest"),
)


def _load_auth_settings(secrets: Mapping[str, Any]) -> AuthSettings:
    """Resolve as credenciais do admin com a mesma precedência dos outros
    apps do usuário: st.secrets["auth"] primeiro; se não houver, cai para
    o arquivo local auth/users.yaml (gerado por scripts/create_admin_user.py).
    """
    secrets_username = _get(secrets, "auth", "username")
    secrets_hash = _get(secrets, "auth", "password_hash")
    if secrets_username and secrets_hash:
        return AuthSettings(username=secrets_username, password_hash=secrets_hash)

    if AUTH_YAML_PATH.exists():
        import yaml

        try:
            with open(AUTH_YAML_PATH, "r", encoding="utf-8") as file:
                data = yaml.safe_load(file) or {}
        except (yaml.YAMLError, OSError):
            # Arquivo presente mas ilegível (corrompido, vazio no meio de
            # uma escrita, permissão). Não trava o app inteiro por causa
            # disso — trata como "sem credencial ainda" (mesmo resultado de
            # não ter o arquivo), e a UI orienta a rodar o script de setup
            # de novo em vez de uma tela de erro sem explicação.
            data = {}
        yaml_username = data.get("username", "") if isinstance(data, dict) else ""
        yaml_hash = data.get("password_hash", "") if isinstance(data, dict) else ""
        if yaml_username and yaml_hash:
            return AuthSettings(username=yaml_username, password_hash=yaml_hash)

    # Nenhuma credencial configurada ainda (nem em secrets, nem em yaml).
    # Mantém um username padrão só para a UI conseguir orientar o usuário
    # a rodar o script de setup; sem password_hash, o login nunca passa.
    fallback_username = _get(secrets, "auth", "username", default="admin")
    return AuthSettings(username=fallback_username, password_hash="")


def load_settings(secrets: Mapping[str, Any]) -> Settings:
    turso = TursoSettings(
        database_url=_get(secrets, "turso", "database_url"),
        auth_token=_get(secrets, "turso", "auth_token"),
    )

    auth = _load_auth_settings(secrets)

    n8n = N8nSettings(
        webhook_url=_get(secrets, "n8n", "webhook_url"),
        auth_header_name=_get(secrets, "n8n", "auth_header_name"),
        auth_header_value=_get(secrets, "n8n", "auth_header_value"),
        timeout_seconds=float(_get(secrets, "n8n", "timeout_seconds", default=300.0)),
    )

    ai_cascade = [
        AIProviderSettings(
            kind=kind,
            label=label,
            api_key=_get(secrets, "ai", secrets_key, "api_key"),
            model=_get(secrets, "ai", secrets_key, "model", default=default_model),
        )
        for secrets_key, kind, label, default_model in _DEFAULT_CASCADE_ORDER
    ]

    security = SecuritySettings(
        bcrypt_rounds=int(_get(secrets, "security", "bcrypt_rounds", default=12)),
        max_login_attempts=int(_get(secrets, "security", "max_login_attempts", default=5)),
        lock_minutes=int(_get(secrets, "security", "lock_minutes", default=15)),
    )

    defaults = AnalysisSettings()
    analysis = AnalysisSettings(
        max_total_chars=int(_get(secrets, "analysis", "max_total_chars", default=defaults.max_total_chars)),
        batch_chars=int(_get(secrets, "analysis", "batch_chars", default=defaults.batch_chars)),
        saved_responses_days=int(
            _get(secrets, "analysis", "saved_responses_days", default=defaults.saved_responses_days)
        ),
    )

    return Settings(
        turso=turso,
        auth=auth,
        n8n=n8n,
        ai_cascade=ai_cascade,
        security=security,
        analysis=analysis,
    )


def load_settings_from_streamlit() -> Settings:
    """Ponto de entrada usado pelo app real (dentro do Streamlit)."""
    import streamlit as st

    return load_settings(st.secrets)

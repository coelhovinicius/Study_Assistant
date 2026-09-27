"""Provedor de IA que delega para um webhook n8n — mesmo padrão usado nos
outros apps do usuário ([n8n] webhook_url = "...").

Diferente dos outros provedores (`OpenAIProvider`, `GeminiProvider` etc.),
este não fala com nenhuma API de IA diretamente: ele manda o prompt já
pronto (construído em `config/prompts.py`) para o webhook, e é o próprio
n8n quem decide, internamente, qual provedor tentar e em que ordem — a
cascata Gemini → Groq → Groq 2 → Mistral → OpenAI → Groq 3, a mesma do
workflow Doc_QA_Generation_HA, só que rodando lá em vez de aqui. Por isso o app Python passa a ter só ESTE provedor na
cascata (`AIProviderCascade([N8nWebhookProvider(...)])`) quando o n8n está
configurado: o fallback entre modelos não é mais responsabilidade do
Python.

O workflow do n8n usado aqui é genérico de propósito — recebe
``{"prompt": "...", "formato": "json", "chaves_obrigatorias": [...]}`` e
devolve a resposta já validada (os nós "JSON ..." do workflow conferem o
formato e as chaves e, se faltar alguma, passam pra próxima IA), sem
nenhuma lógica de negócio (prompt de apostila, de desafio, etc.) embutida
nos nós do n8n.
Isso mantém as regras de negócio no Python (fácil de testar, versionar,
revisar) e o n8n só como "motor de execução com fallback entre
provedores" — ver ``n8n/study_assistant_ai_cascade.json`` no projeto para
o workflow pronto para importar.
"""

from __future__ import annotations

import json
from typing import Any

from study_assistant.domain.ports import ResponseFormat
from study_assistant.infrastructure.ai_providers.base import BaseAIProvider

# Nomes de campo candidatos para o texto de resposta dentro do objeto que o
# n8n devolve. O node "Respond to Webhook" do workflow deste app devolve o
# objeto inteiro (`={{ $json }}`), então o nome exato do campo com o texto
# da IA varia conforme o node do LangChain que respondeu por último na
# cascata (chainLlm sem parser normalmente usa "response"/"text"; com saída
# estruturada, "output"). Testamos os candidatos mais comuns, nessa ordem,
# antes de desistir e devolver o objeto inteiro como JSON.
_RESPONSE_FIELD_CANDIDATES: tuple[str, ...] = ("output", "response", "text", "answer")


def _extract_text(data: dict[str, Any]) -> str | None:
    """Procura o texto da resposta da IA num objeto retornado pelo n8n,
    testando os nomes de campo mais comuns (inclusive aninhados, já que o
    chainLlm às vezes devolve ``{"response": {"text": "..."}}``)."""
    for field in _RESPONSE_FIELD_CANDIDATES:
        if field not in data:
            continue
        value = data[field]
        if isinstance(value, str) and value.strip():
            return value
        if isinstance(value, dict):
            nested = _extract_text(value)
            if nested is not None:
                return nested
    return None


def _error_detail(response: Any) -> str:
    """Motivo real de um erro HTTP do n8n. Quando todas as IAs falham, o
    workflow responde 502 com ``{"error": ..., "detalhe": ...}`` — o
    "detalhe" (ex: "Request too large ... tokens per minute") é o que
    explica a falha, então vai inteiro na mensagem."""
    try:
        body = response.json()
    except ValueError:
        return response.text[:600]
    if isinstance(body, dict) and ("error" in body or "detalhe" in body):
        return f"{body.get('error', '')} {body.get('detalhe', '')}".strip()
    return response.text[:600]


class N8nWebhookProvider(BaseAIProvider):
    def __init__(
        self,
        *,
        webhook_url: str,
        auth_header_name: str = "",
        auth_header_value: str = "",
        timeout_seconds: float = 120.0,
    ) -> None:
        # "model" aqui é só um rótulo descritivo para os logs/relatório —
        # quem decidiu o modelo de verdade foi o workflow do n8n.
        super().__init__(
            model="cascata n8n (Gemini→Groq→Groq 2→Mistral→OpenAI→Groq 3)",
            timeout_seconds=timeout_seconds,
        )
        self._webhook_url = webhook_url
        self._auth_header_name = auth_header_name
        self._auth_header_value = auth_header_value

    @property
    def provider_name(self) -> str:
        return "n8n"

    def _send(self, prompt: str, *, response_format: ResponseFormat, required_keys: tuple[str, ...]) -> str:
        import requests

        headers = {"Content-Type": "application/json"}
        if self._auth_header_name and self._auth_header_value:
            headers[self._auth_header_name] = self._auth_header_value

        response = requests.post(
            self._webhook_url,
            json={
                "prompt": prompt,
                "formato": response_format,
                "chaves_obrigatorias": list(required_keys),
            },
            headers=headers,
            timeout=self._timeout_seconds,
        )

        if response.status_code >= 400:
            raise RuntimeError(
                f"webhook do n8n retornou HTTP {response.status_code}: {_error_detail(response)}"
            )

        try:
            data = response.json()
        except ValueError:
            # Corpo não é JSON — trata como texto puro direto (n8n pode ter
            # sido configurado para responder texto cru em vez de JSON).
            return response.text

        if isinstance(data, str):
            return data
        if isinstance(data, dict):
            if "error" in data and not any(key in data for key in required_keys):
                raise RuntimeError(f"{data['error']} {data.get('detalhe', '')}".strip())
            if response_format == "json" and required_keys and all(key in data for key in required_keys):
                # O workflow já devolve o objeto JSON validado, direto no
                # corpo — não é um "envelope" com o texto dentro.
                return json.dumps(data, ensure_ascii=False)
            text = _extract_text(data)
            if text is not None:
                return text
        # Fallback: não achamos nenhum campo de texto conhecido — devolve o
        # objeto inteiro como texto JSON, que o parser tolerante do app
        # (application/ai_json_utils.py) ainda consegue interpretar.
        return json.dumps(data, ensure_ascii=False)

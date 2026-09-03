"""Provedor de IA que delega para um webhook n8n — mesmo padrão usado nos
outros apps do usuário ([n8n] webhook_url = "...").

Diferente dos outros provedores (`OpenAIProvider`, `GeminiProvider` etc.),
este não fala com nenhuma API de IA diretamente: ele manda o prompt já
pronto (construído em `config/prompts.py`) para o webhook, e é o próprio
n8n quem decide, internamente, qual provedor tentar e em que ordem — a
mesma cascata OpenAI → Gemini → Groq → Groq → Mistral, só que rodando lá
em vez de aqui. Por isso o app Python passa a ter só ESTE provedor na
cascata (`AIProviderCascade([N8nWebhookProvider(...)])`) quando o n8n está
configurado: o fallback entre modelos não é mais responsabilidade do
Python.

O workflow do n8n usado aqui é genérico de propósito — recebe só
``{"prompt": "..."}`` e devolve o texto de resposta, sem nenhuma lógica de
negócio (prompt de apostila, de desafio, etc.) embutida nos nós do n8n.
Isso mantém as regras de negócio no Python (fácil de testar, versionar,
revisar) e o n8n só como "motor de execução com fallback entre
provedores" — ver ``n8n/study_assistant_ai_cascade.json`` no projeto para
o workflow pronto para importar.
"""

from __future__ import annotations

from typing import Any

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
        super().__init__(model="cascata n8n (OpenAI→Gemini→Groq→Groq→Mistral)", timeout_seconds=timeout_seconds)
        self._webhook_url = webhook_url
        self._auth_header_name = auth_header_name
        self._auth_header_value = auth_header_value

    @property
    def provider_name(self) -> str:
        return "n8n"

    def _call_api(self, prompt: str) -> str:
        import json

        import requests

        headers = {"Content-Type": "application/json"}
        if self._auth_header_name and self._auth_header_value:
            headers[self._auth_header_name] = self._auth_header_value

        response = requests.post(
            self._webhook_url,
            json={"prompt": prompt},
            headers=headers,
            timeout=self._timeout_seconds,
        )

        if response.status_code >= 400:
            raise RuntimeError(
                f"webhook do n8n retornou HTTP {response.status_code}: {response.text[:300]}"
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
            if "error" in data:
                raise RuntimeError(str(data["error"]))
            text = _extract_text(data)
            if text is not None:
                return text
        # Fallback: não achamos nenhum campo de texto conhecido — devolve o
        # objeto inteiro como texto JSON, que o parser tolerante do app
        # (application/ai_json_utils.py) ainda consegue interpretar.
        return json.dumps(data, ensure_ascii=False)

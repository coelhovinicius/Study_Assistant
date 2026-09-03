"""Ports (interfaces) que o domínio e a camada de aplicação dependem, mas
que só são implementados na camada de infraestrutura.

Este é o mecanismo central de Inversão de Dependência do projeto: a
aplicação programa contra estas abstrações, nunca contra uma biblioteca
concreta (bcrypt, requests, openai, reportlab, etc.). Isso permite trocar
qualquer peça de infraestrutura (ex: trocar Turso por Postgres, ou trocar
Groq por outro provedor) sem tocar em regra de negócio nenhuma, e permite
testar os casos de uso com implementações falsas (fakes/mocks).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

from study_assistant.domain.entities import AdminUser, StudySession

ResponseFormat = Literal["text", "json"]


class TextExtractor(ABC):
    """Extrai texto puro de um arquivo em um formato específico (PDF, TXT, DOCX)."""

    @abstractmethod
    def supports(self, filename: str) -> bool:
        """Retorna True se este extrator sabe lidar com o arquivo informado."""

    @abstractmethod
    def extract(self, file_bytes: bytes, filename: str) -> str:
        """Extrai e retorna o texto puro contido no arquivo.

        Deve levantar ``TextExtractionError`` em caso de falha e
        ``EmptyDocumentError`` se o resultado for vazio.
        """


class AIProvider(ABC):
    """Um provedor de IA generativa capaz de responder a um prompt de texto.

    Tanto um provedor concreto (OpenAI, Gemini, Groq, Mistral) quanto o
    orquestrador de cascata (``AIProviderCascade``) implementam esta mesma
    interface — a aplicação não precisa saber se está falando com um único
    provedor ou com uma cadeia de fallback (padrão Composite).
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Nome curto e estável do provedor, usado em logs e no relatório final."""

    @abstractmethod
    def generate(self, prompt: str, *, response_format: ResponseFormat = "text") -> str:
        """Envia o prompt e retorna o texto de resposta gerado.

        Quando ``response_format="json"``, a implementação deve instruir o
        modelo a responder apenas com JSON válido; a validação/parse do
        JSON é responsabilidade de quem chama, não do provedor.

        Deve levantar ``AIProviderError`` em qualquer falha (rede,
        autenticação, limite de uso, resposta vazia, etc.), nunca deixar
        vazar a exceção original da SDK do provedor.
        """


class PasswordHasher(ABC):
    """Responsável por gerar e verificar hashes seguros de senha."""

    @abstractmethod
    def hash(self, plain_password: str) -> str: ...

    @abstractmethod
    def verify(self, plain_password: str, password_hash: str) -> bool: ...


class UserRepository(ABC):
    """Persistência do (único) usuário administrador."""

    @abstractmethod
    def get_by_username(self, username: str) -> AdminUser | None: ...

    @abstractmethod
    def save(self, user: AdminUser) -> None: ...

    @abstractmethod
    def register_login_attempt(
        self, username: str, *, success: bool, lock_until_minutes: int, max_attempts: int
    ) -> None:
        """Atualiza o contador de tentativas falhas e, se necessário, bloqueia a conta."""


class SessionRepository(ABC):
    """Persistência do histórico de sessões de estudo (item 'salvar ou não').

    Desde que o histórico passou a guardar somente o PDF (não mais o texto
    bruto dos materiais nem a análise estruturada), quem CHAMA ``save`` já
    precisa ter gerado o PDF antes (``HistoryService`` faz isso via
    ``GenerateReportUseCase``) — o repositório só persiste o que recebe,
    sem saber nada sobre geração de relatório."""

    @abstractmethod
    def save(self, session: StudySession, *, pdf_bytes: bytes, pdf_filename: str) -> None: ...

    @abstractmethod
    def list_summaries(self, limit: int = 50) -> list[dict]:
        """Retorna metadados resumidos (id, título, data, matérias) do histórico."""

    @abstractmethod
    def get(self, session_id: str) -> StudySession | None:
        """Sessão salva DEPOIS da mudança pra só guardar PDF volta com
        ``stored_pdf_bytes``/``stored_pdf_filename`` preenchidos e sem
        materiais/análise. Sessão salva ANTES (legado) continua voltando
        reconstruída a partir de materiais + análise, como sempre foi."""

    @abstractmethod
    def delete(self, session_id: str) -> None: ...


class ReportGenerator(ABC):
    """Gera o documento final de análise em um formato específico de saída."""

    @property
    @abstractmethod
    def format_name(self) -> str:
        """Ex: 'docx', 'pdf', 'txt', 'csv'."""

    @property
    @abstractmethod
    def mime_type(self) -> str: ...

    @abstractmethod
    def generate(self, session: StudySession) -> bytes:
        """Renderiza a sessão de estudo (materiais + insights + análise) em bytes."""

# Study Assistant

Automação pessoal do fluxo de estudo descrito no chat: você sobe a
apostila (e, opcionalmente, livro, audiodescrição do podcast e outros
materiais), o app extrai automaticamente as referências bibliográficas, as
dicas/indicações de leitura e o desafio prático da apostila, manda tudo
para uma cascata de provedores de IA (OpenAI → Gemini → Groq → Groq →
Mistral, com fallback automático caso um falhe — via webhook do seu n8n,
mesmo padrão dos seus outros apps, ou direto em Python, você escolhe) e
devolve uma análise completa dividida por assunto, com a resolução do
desafio — pronta para baixar em `.docx`, `.pdf`, `.txt` ou `.csv`, com a
opção de salvar ou não o resultado no histórico.

A extração automática direto da plataforma Kroton **não** foi
implementada, por decisão explícita sua no chat (upload manual dos
arquivos já baixados continua sendo o fluxo).

## Arquitetura

O projeto segue Clean Architecture / Ports & Adapters, dividido em quatro
camadas dentro de `src/study_assistant/`:

```
domain/          entidades e interfaces (ports) — não depende de nada externo
application/     casos de uso, orquestram o domínio via ports
infrastructure/  implementações concretas (Turso, PDFs, provedores de IA, relatórios)
presentation/    app Streamlit + composition root (injeção de dependência)
```

Na raiz também tem `n8n/study_assistant_ai_cascade.json` — o workflow
pronto para importar na sua instância n8n, usado pelo modo de IA "n8n"
(ver "Modo de IA: n8n ou Python direto" no Setup).

Na raiz do projeto, `auth/users.yaml` (fora do Git) guarda o fallback
local de login — mesmo nome/formato de arquivo usado nos seus outros
apps, mesmo a lógica que o lê vivendo dentro do pacote
(`infrastructure/security/config_user_repository.py`) em vez de um
`auth/auth_manager.py` solto, para seguir a organização em camadas do
resto do projeto.

A regra é sempre "de fora para dentro": `presentation` e `infrastructure`
conhecem `application`/`domain`, mas o inverso nunca acontece. Isso é o
que permite, por exemplo, trocar o Turso por outro banco, ou adicionar um
quinto provedor de IA, sem tocar em nenhuma regra de negócio — só se
implementa a interface (`domain/ports.py`) correspondente e se registra a
nova peça em `presentation/di_container.py` (o único lugar que conhece as
implementações concretas).

Padrões usados de propósito:
- **Chain of Responsibility / Composite** — `AIProviderCascade`
  (`infrastructure/ai_providers/cascade.py`) tenta os provedores em ordem
  e, ao mesmo tempo, se comporta como "só mais um provedor" para quem a
  usa.
- **Strategy** — cada provedor de IA e cada gerador de relatório
  implementa a mesma interface, então adicionar um novo formato/provedor
  não exige mexer em código existente.
- **Template Method** — `BaseAIProvider` centraliza cronometragem e
  tratamento de erro comuns a todos os provedores de chat completion.
- **Repository** — acesso a dados fica isolado atrás de interfaces
  (`UserRepository`, `SessionRepository`), com implementações diferentes:
  o login do admin **não** usa Turso (segue o mesmo padrão dos seus
  outros apps: `st.secrets["auth"]`, com fallback em `auth/users.yaml`),
  enquanto o histórico de sessões salvas usa Turso — assim como nos
  outros apps o Turso guarda dados "de resultado" (ex: o
  `historico_backlog_sprint_qa` do Burndown), nunca a credencial de
  login. Trocar de novo essa peça no futuro (ex: mover o histórico para
  outro banco) continua sendo só implementar a interface e religar em
  `di_container.py`.

## Setup

### 1. Instalar dependências

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configurar segredos

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

Edite `.streamlit/secrets.toml` com:
- a URL e o token do seu banco Turso (o mesmo banco compartilhado dos
  seus outros apps — as tabelas deste app usam o prefixo `sa_` para não
  colidir com as suas tabelas existentes: `usuarios_app_qa`,
  `usuarios_autorizados_glpi_qa`, `logs_sistema_qa`,
  `historico_backlog_sprint_qa`);
- a IA — escolha um dos dois modos (ver "Modo de IA: n8n ou Python
  direto" logo abaixo) e preencha `[n8n]` **ou** `[ai.*]`;
- a seção `[auth]` (usuário e hash da senha) — mas essa você não escreve
  à mão, veja o passo 4.

Esse arquivo já está no `.gitignore` — nunca vai para o Git.

### 2.1. Modo de IA: n8n ou Python direto

O app aceita dois jeitos de rodar a cascata OpenAI → Gemini → Groq →
Groq → Mistral, e você escolhe qual usar só preenchendo (ou não) o
`[n8n]` em `secrets.toml` — nenhum código muda entre um modo e outro
(`_build_ai_providers()` em `presentation/di_container.py` decide isso
sozinho, olhando `settings.n8n.is_configured`).

**Modo n8n (recomendado — é o que você já usa nos outros apps):**

1. Abra sua instância n8n e importe `n8n/study_assistant_ai_cascade.json`
   (Workflows → Import from File).
2. O workflow já vem com as 5 credenciais linkadas pelos mesmos IDs que
   você usa no `Doc_QA_Generation_HA` (OpenAI account, Google
   Gemini(PaLM) Api account, Groq account, Groq account 2, Mistral Cloud
   account, Header Auth account 4) — se essas credenciais existirem na
   sua instância, elas conectam sozinhas; se o n8n reclamar de alguma,
   é só reapontar para a credencial certa manualmente.
3. Ative o workflow e copie a URL do webhook (nó "Webhook - Cascata
   IA").
4. Cole essa URL em `[n8n].webhook_url` no `secrets.toml`, e o mesmo
   header/valor de autenticação que a credencial "Header Auth account
   4" espera em `auth_header_name`/`auth_header_value`.

Diferente do `Doc_QA_Generation_HA` original (que serviu de referência),
este workflow é **genérico**: os nós "Chain" só repassam
`{{ $json.body.prompt }}` — nenhum prompt de negócio, schema ou Output
Parser vive dentro do n8n. Todo o texto do prompt (`config/prompts.py`)
e a interpretação da resposta (`application/ai_json_utils.py`) ficam no
Python, versionados e testados; o n8n vira só o "motor de execução com
fallback entre provedores". Duas correções em relação ao fluxo de
exemplo: o webhook agora liga na OpenAI Chain primeiro (no original ele
pulava direto para a Gemini Chain, por engano), e existe um nó
"Responder Erro" (HTTP 502) para quando até o Mistral falha — no
original, esse caso não tinha resposta nenhuma.

Com esse modo, a visão "o que deu certo, o que falhou, qual IA pegou a
tarefa, quando, com que erro" vem de graça pela aba **Executions** do
próprio n8n — o mesmo controle que você já usa nos seus outros fluxos,
sem precisar de nenhum log adicional dentro do Study Assistant.

**Modo Python direto (sem depender do n8n estar de pé):** deixe
`[n8n].webhook_url` vazio (ou a seção toda fora) e preencha as seções
`[ai.openai]`, `[ai.gemini]`, `[ai.groq_primary]`, `[ai.groq_secondary]`
e `[ai.mistral]` com suas chaves de API — não precisa configurar as
cinco, o app usa só as que tiverem `api_key` preenchida, na mesma ordem.
Nesse modo o fallback entre provedores acontece dentro do próprio
Python (`AIProviderCascade`), e as tentativas ficam disponíveis na
sessão (expander "Como cada IA respondeu" na tela de resultado), mas
não em nenhum painel de execuções.

### 3. Criar as tabelas no Turso

```bash
python scripts/init_database.py
```

Idempotente (`CREATE TABLE IF NOT EXISTS`) — pode rodar de novo sem medo.
Só cria as tabelas do histórico de sessões salvas — o login do admin não
mora no Turso (ver passo 4).

### 4. Criar seu usuário administrador

```bash
python scripts/create_admin_user.py
```

Vai pedir a senha de forma oculta (nunca digite a senha como argumento de
linha de comando) e gera o hash bcrypt. Mesmo padrão dos seus outros apps
(`auth/auth_manager.py`): o login do admin **não** fica no Turso.

O script grava o resultado em `auth/users.yaml` (fallback local, fora do
Git — é o que o app usa se você não configurar Secrets) e também imprime
um bloco `[auth]` pronto para colar em `.streamlit/secrets.toml` (ou nos
Secrets do Streamlit Cloud), caso prefira essa via — que tem prioridade
sobre o `auth/users.yaml` quando presente. Rode o mesmo comando de novo
quando quiser trocar a senha.

### 5. Rodar o app

```bash
streamlit run app.py
```

## Como o fluxo funciona por dentro

1. **Upload** (`presentation/pages_/upload_analysis_page.py`) — você sobe
   os arquivos, separados por tipo (Apostila / Livro / Podcast / Outros).
2. **Extração de texto** (`infrastructure/extractors/`) — PDF, TXT e DOCX
   viram texto puro.
3. **Extração das 3 seções da apostila**
   (`application/extraction_service.py`) — primeiro tenta achar por
   cabeçalhos comuns (rápido, sem custo de IA); se não achar, pede pra IA
   extrair só aquele trecho.
4. **Análise completa** (`application/analysis_service.py`) — um único
   prompt de negócio (`config/prompts.py`) é enviado à cascata de IA, que
   tenta cada provedor em ordem até um responder.
5. **Relatório** (`infrastructure/report_generators/`) — o mesmo
   resultado é renderizado em docx/pdf/txt/csv, todos a partir de um
   "esboço" comum (`report_content.py`) pra evitar duplicar a lógica de
   "o que entra no relatório" quatro vezes.
6. **Salvar ou não** — só grava no Turso (`sa_study_sessions`,
   `sa_materials`, `sa_provider_attempts`) se você clicar em "Salvar no
   histórico"; senão, nada é persistido. O login, por outro lado, nunca
   passa pelo Turso — vem de `st.secrets["auth"]` ou de `auth/users.yaml`
   (`infrastructure/security/config_user_repository.py`).

## Limitações conhecidas (v1)

- PDFs puramente escaneados (sem camada de texto) não são lidos — não há
  OCR embutido. Se isso for um problema recorrente, dá pra adicionar um
  extrator com OCR implementando o mesmo `TextExtractor` sem mexer em
  mais nada.
- A extração automática de materiais direto da plataforma Kroton não foi
  implementada (decisão explícita, por ser mais frágil/trabalhosa de
  manter que o upload manual).
- Sem suporte a múltiplos usuários — é um app pessoal, com um único
  administrador.
- O controle de tentativas de login malsucedidas (lockout) fica em
  memória, no processo do Streamlit — reinicia se o servidor reiniciar.
  Suficiente para um app pessoal de usuário único; não seria adequado com
  múltiplas réplicas do servidor.

## Testes

```bash
pip install pytest
pytest
```

Os testes usam fakes/mocks para os ports (`AIProvider`, `PasswordHasher`
etc.), então rodam sem precisar de chaves de API nem de conexão com o
Turso.

## Adicionando um novo provedor de IA

**Modo Python direto:**
1. Crie uma classe em `infrastructure/ai_providers/` que herde de
   `BaseAIProvider` e implemente `provider_name` e `_call_api`.
2. Registre-a em `_build_ai_provider()` e na ordem da cascata em
   `config/settings.py` (`_DEFAULT_CASCADE_ORDER`).
3. Adicione a seção correspondente em `.streamlit/secrets.toml.example`.

Nenhum outro arquivo precisa mudar.

**Modo n8n:** adicione o novo elo (Chat Model + Chain) direto no
workflow (`n8n/study_assistant_ai_cascade.json` ou na versão já
importada na sua instância), ligando a saída de erro do último elo
atual nele e a dele em "Responder Sucesso"/no próximo elo — nenhum
código Python precisa mudar, já que o app só enxerga o webhook como um
único provedor.

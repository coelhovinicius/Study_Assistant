# Study Assistant

Automação pessoal do fluxo de estudo descrito no chat: você sobe a
apostila (e, opcionalmente, livro, audiodescrição do podcast e outros
materiais), o app extrai automaticamente as referências bibliográficas, as
dicas/indicações de leitura e o desafio prático da apostila, manda tudo
— em lotes que cabem na cota por minuto das IAs gratuitas — para uma
cascata de provedores de IA (Gemini → Groq → Groq 2 → Mistral → OpenAI →
Groq 3, com fallback automático caso um falhe — via webhook do seu n8n,
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

O app aceita dois jeitos de rodar a cascata de IA, e você escolhe qual
usar só preenchendo (ou não) o `[n8n]` em `secrets.toml` — nenhum código
muda entre um modo e outro (`_build_ai_providers()` em
`presentation/di_container.py` decide isso sozinho, olhando
`settings.n8n.is_configured`).

**Modo n8n (recomendado — é o que você já usa nos outros apps):**

1. Abra sua instância n8n e importe `n8n/study_assistant_ai_cascade.json`
   (Workflows → Import from File).
2. O workflow já vem com as credenciais linkadas pelos mesmos IDs que
   você usa no `Doc_QA_Generation_HA` (Google Gemini(PaLM) Api account,
   Groq account, Groq account 2, Mistral Cloud account, OpenAI account,
   Groq account 3, Header Auth account 5) — se essas credenciais
   existirem na sua instância, elas conectam sozinhas; se o n8n reclamar
   de alguma, é só reapontar para a credencial certa manualmente.
3. Ative o workflow e copie a URL do webhook (nó "Webhook - Cascata
   IA").
4. Cole essa URL em `[n8n].webhook_url` no `secrets.toml`, e o mesmo
   header/valor de autenticação que a credencial "Header Auth account
   5" espera em `auth_header_name`/`auth_header_value`.

O workflow segue o mesmo padrão do `Doc_QA_Generation_HA`:

- cascata **Gemini → Groq → Groq 2 → Mistral → OpenAI → Groq 3**
  (gpt-oss-20b, na conta "Groq account 3"), com limite de tokens de
  resposta e sem retentativa interna de cada modelo;
- cada IA passa por um nó **"JSON ..."** que extrai e valida o JSON da
  resposta (tolera cerca de markdown, texto em volta e vírgula sobrando)
  e confere as chaves obrigatórias — resposta fora do formato vai pra
  próxima IA, em vez de voltar quebrada pro app;
- erro 5xx/sobrecarga de uma IA passa por **"Erro 5xx?"** → **"Aguardar
  5s"** e tenta a MESMA IA de novo (até 2 vezes) antes de ir pra próxima;
- "Responder Erro" (HTTP 502) só quando até o Groq 3 falha, com o motivo
  real em `detalhe`.

A diferença é que ele é **genérico**: nenhum prompt de negócio, schema ou
Output Parser vive dentro do n8n. O app manda
`{"prompt", "formato", "chaves_obrigatorias"}` e os nós "JSON ..." usam
essas chaves pra validar — todo o texto do prompt (`config/prompts.py`) e
a interpretação da resposta ficam no Python, versionados e testados. As
chains leem o prompt direto do Webhook (e não de `$json`), porque quando
uma chain é chamada pela saída de erro de um nó "JSON ...", o item que
chega é a resposta ruim da IA anterior, sem o pedido original.

Com esse modo, a visão "o que deu certo, o que falhou, qual IA pegou a
tarefa, quando, com que erro" vem de graça pela aba **Executions** do
próprio n8n — o mesmo controle que você já usa nos seus outros fluxos,
sem precisar de nenhum log adicional dentro do Study Assistant.

**Modo Python direto (sem depender do n8n estar de pé):** deixe
`[n8n].webhook_url` vazio (ou a seção toda fora) e preencha as seções
`[ai.openai]`, `[ai.gemini]`, `[ai.groq_primary]`, `[ai.groq_secondary]`
e `[ai.mistral]` com suas chaves de API — não precisa configurar as
cinco, o app usa só as que tiverem `api_key` preenchida, nessa ordem
(OpenAI → Gemini → Groq → Groq → Mistral). Nesse modo o fallback entre
provedores acontece dentro do próprio Python (`AIProviderCascade`), com a
mesma regra dos nós "JSON ..." do n8n (resposta sem as chaves pedidas vai
pro próximo provedor), e as tentativas ficam disponíveis na sessão
(expander "Detalhes técnicos da geração" na tela de resultado), mas não
em nenhum painel de execuções.

### 2.2. Análise em lotes

As IAs gratuitas da cascata têm teto de tokens **por minuto** (Groq:
8.000), e mandar o material inteiro numa chamada só estourava esse teto.
Por isso, igual ao qa_testgen, a análise é feita em lotes:

- cada material é dividido em lotes de até 12 mil caracteres, sempre
  cortando entre parágrafos (`application/text_batches.py`);
- entre uma chamada e outra o app espera o tempo proporcional ao tamanho
  do que foi enviado (de 5s a 30s); se uma chamada falha, espera 62s e
  tenta o mesmo lote de novo, até 3 vezes (`application/ai_caller.py`);
- o resultado continua sendo **uma** análise num PDF só: a seção de cada
  material traz as partes em ordem ("Parte 2 de 4 — título"), e as seções
  de referências, dicas, desafio e síntese são escritas a partir de um
  resumo curto de cada lote.

**Nada se perde e nada é pedido duas vezes:** cada resposta da IA é
gravada no Turso (`sa_ai_respostas`) assim que chega. Se um lote falhar as
3 vezes, a análise **pausa** (nunca sai com parte faltando) e o botão vira
**▶️ Continuar análise** — ao continuar, ou ao subir os mesmos arquivos de
novo (até dias depois, mesmo com o navegador fechado ou o servidor
reiniciado), o que já tinha resposta volta do banco sem chamar a IA. Essas
respostas são temporárias: somem sozinhas depois de 7 dias.

Os limites são ajustáveis em `[analysis]` no `secrets.toml` (ver
`.streamlit/secrets.toml.example`): `max_total_chars` (padrão 200 mil
caracteres por análise, somando os materiais — o que passar disso é
avisado no fim da seção do material), `batch_chars` e
`saved_responses_days`. O limite é repartido por prioridade: apostila,
podcast e outros materiais entram primeiro; os livros (opcionais e, de
longe, os maiores) ficam com o que sobrar.

### 3. Criar as tabelas no Turso

```bash
python scripts/init_database.py
```

Idempotente (`CREATE TABLE IF NOT EXISTS`) — pode rodar de novo sem medo.
Cria as tabelas do histórico de sessões salvas e a `sa_ai_respostas`
(respostas da IA guardadas por alguns dias pra análise em lotes poder
pausar e continuar — o app também cria essa sozinho no primeiro uso, se
faltar). O login do admin não mora no Turso (ver passo 4).

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
   cabeçalhos comuns (rápido, sem custo de IA); o que não achar, a IA
   procura na apostila lote a lote, com uma chamada por lote pedindo
   todas as seções que faltam de uma vez.
4. **Análise em lotes** (`application/analysis_service.py`) — uma chamada
   por lote de cada material e mais 4 pequenas para referências, dicas,
   desafio e síntese (ver "Análise em lotes" no Setup). A tela mostra em
   que etapa está, as esperas e o que já ficou pronto.
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
- A análise em lotes é mais lenta que uma chamada só. Medido com uma aula
  real (apostila + podcast + os dois livros da disciplina, ~165 mil
  caracteres): 21 chamadas, com ~7 minutos só de espera entre elas (pra
  não estourar a cota por minuto), fora o tempo de resposta das IAs. A
  espera é calculada pelo provedor mais apertado (Groq), mesmo quando quem
  responde é o Gemini. Os livros costumam ser os mesmos em todas as aulas
  da disciplina: dentro dos 7 dias em que as respostas ficam salvas, a
  análise deles é reaproveitada nas aulas seguintes, sem nova chamada.
- No PDF salvo no histórico, o título impresso dentro do arquivo é o da
  hora em que foi salvo — renomear a sessão muda o título da lista e o
  nome do arquivo baixado, não o conteúdo do PDF.

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

**Modo n8n:** adicione o novo elo direto no workflow
(`n8n/study_assistant_ai_cascade.json` ou na versão já importada na sua
instância), com as mesmas 5 peças dos outros: Chat Model, Chain (prompt
lido do Webhook), "JSON ..." (copie o código de um existente),
"Erro 5xx?" e "Aguardar 5s". Ligue nele as saídas de falha do último elo
atual (a de erro do "JSON ..." e a "falso" do "Erro 5xx?") e as dele em
"Responder Sucesso"/no próximo elo — nenhum código Python precisa mudar,
já que o app só enxerga o webhook como um único provedor.

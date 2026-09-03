-- Schema do Study Assistant no banco Turso compartilhado.
--
-- Todas as tabelas usam o prefixo "sa_" (Study Assistant) para não colidir
-- com as tabelas de outros apps que já vivem nesse mesmo banco. Rode este
-- script uma vez (veja scripts/init_database.py) antes do primeiro uso.
--
-- Não há tabela de usuário aqui de propósito: o login do admin segue o
-- mesmo padrão dos outros apps (st.secrets["auth"], com fallback em
-- auth/users.yaml) — nunca fica no Turso. O Turso guarda só o "resultado
-- salvo": as sessões de estudo que o usuário decide manter no histórico.

CREATE TABLE IF NOT EXISTS sa_study_sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    apostila_insights_json TEXT,
    analysis_sections_json TEXT,
    generated_by_provider TEXT,
    generated_by_model TEXT,
    -- pdf_bytes/pdf_filename: usadas a partir da mudança pra o histórico
    -- guardar SOMENTE o PDF (não mais o texto bruto dos materiais nem a
    -- análise estruturada). As colunas acima continuam existindo só para
    -- ler sessões salvas ANTES dessa mudança — nenhuma linha nova grava
    -- nelas. Bancos já criados antes dessa mudança precisam da migração em
    -- scripts/init_database.py (ALTER TABLE ... ADD COLUMN), já que
    -- "CREATE TABLE IF NOT EXISTS" não adiciona coluna em tabela existente.
    pdf_bytes BLOB,
    pdf_filename TEXT
);

-- sa_materials e sa_provider_attempts: mantidas só para conseguir continuar
-- lendo sessões salvas ANTES da mudança pra guardar somente o PDF — nenhuma
-- linha nova é inserida nelas a partir dessa mudança (session_repository.py
-- não escreve mais aqui). Não removidas pra não perder o que já existia.
CREATE TABLE IF NOT EXISTS sa_materials (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sa_study_sessions(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    material_type TEXT NOT NULL,
    source_format TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    uploaded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sa_provider_attempts (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sa_study_sessions(id) ON DELETE CASCADE,
    provider_name TEXT NOT NULL,
    model TEXT NOT NULL,
    success INTEGER NOT NULL,
    duration_ms REAL NOT NULL,
    error_message TEXT,
    attempted_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sa_materials_session_id ON sa_materials(session_id);
CREATE INDEX IF NOT EXISTS idx_sa_provider_attempts_session_id ON sa_provider_attempts(session_id);
CREATE INDEX IF NOT EXISTS idx_sa_study_sessions_created_at ON sa_study_sessions(created_at);

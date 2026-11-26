-- ============================================================================
-- CIVICPULSE MODENA - Schema Database Relazionale (SQLite3)
-- Corso di Intelligenza Artificiale e Tecnologie Web (AA 2026-2027) - UNIMORE
-- ============================================================================

PRAGMA foreign_keys = ON;

-- 1. Tabella Squadre Operative Comunali (Teams)
CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    department TEXT NOT NULL,
    specialization TEXT NOT NULL,
    contact_email TEXT NOT NULL,
    active_members INTEGER NOT NULL DEFAULT 4,
    is_available INTEGER NOT NULL DEFAULT 1 CHECK(is_available IN (0, 1)),
    unavailability_reason TEXT DEFAULT '',
    unavailable_until TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Tabella Utenti (Cittadini, Operatori Tecnici, Amministratori)
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('citizen', 'operator', 'admin')) DEFAULT 'citizen',
    team_id INTEGER,
    reputation_points INTEGER NOT NULL DEFAULT 10,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE SET NULL
);

-- 3. Tabella Principale: Segnalazioni Urbane (Reports - Entità CRUD Primaria)
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    category TEXT NOT NULL CHECK(category IN (
        'strade_viabilita',
        'illuminazione_energia',
        'ambiente_verde',
        'rifiuti_decoro',
        'idrico_allagamenti',
        'sicurezza_arredo'
    )),
    priority TEXT NOT NULL CHECK(priority IN ('bassa', 'media', 'alta', 'critica')) DEFAULT 'media',
    status TEXT NOT NULL CHECK(status IN ('aperta', 'in_lavorazione', 'sospesa_meteo', 'risolta', 'chiusa')) DEFAULT 'aperta',
    address TEXT NOT NULL,
    quartiere TEXT NOT NULL,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    image_url TEXT DEFAULT '',
    upvotes INTEGER NOT NULL DEFAULT 1,
    -- Campi derivati dal modulo AI/NLP di Auto-Triage ("Sporcarsi le Mani")
    ai_urgency_score INTEGER NOT NULL DEFAULT 50 CHECK(ai_urgency_score BETWEEN 0 AND 100),
    ai_suggested_category TEXT,
    ai_estimated_sla_hours INTEGER NOT NULL DEFAULT 48,
    ai_reasoning TEXT,
    weather_sensitive INTEGER NOT NULL DEFAULT 0 CHECK(weather_sensitive IN (0, 1)),
    -- Relazioni (Foreign Keys)
    author_id INTEGER NOT NULL,
    assigned_team_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP,
    FOREIGN KEY (author_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (assigned_team_id) REFERENCES teams(id) ON DELETE SET NULL
);

-- 4. Tabella Commenti e Aggiornamenti Operativi (Comments - Entità CRUD Secondaria)
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    is_official_update INTEGER NOT NULL DEFAULT 0 CHECK(is_official_update IN (0, 1)),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (report_id) REFERENCES reports(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- 5. Tabella Voti di Conferma Cittadina (Upvotes - Previene doppi voti dallo stesso utente)
CREATE TABLE IF NOT EXISTS report_upvotes (
    report_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (report_id, user_id),
    FOREIGN KEY (report_id) REFERENCES reports(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Indici per ottimizzare le query di ricerca, filtro e aggregazione su dashboard
CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status);
CREATE INDEX IF NOT EXISTS idx_reports_category ON reports(category);
CREATE INDEX IF NOT EXISTS idx_reports_priority ON reports(priority);
CREATE INDEX IF NOT EXISTS idx_reports_quartiere ON reports(quartiere);
CREATE INDEX IF NOT EXISTS idx_comments_report_id ON comments(report_id);

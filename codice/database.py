"""
database.py - Data Access Layer (DAL) e Inizializzazione Database SQLite3
=========================================================================
Gestisce la connessione al database relazionale SQLite3 (`database/civicpulse.db`),
l'esecuzione dello schema DDL (`database/schema.sql`), il popolamento iniziale (seeding)
con dati realistici geolocalizzati nel Comune di Modena / Campus UNIMORE e tutte le
operazioni CRUD parametrizzate (prevenzione SQL Injection tramite placeholder `?`).
"""

import os
import sqlite3
from datetime import datetime
from typing import Dict, Any, List, Optional
from werkzeug.security import generate_password_hash
from ai_engine import analyze_report_text

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(BASE_DIR, "database")
DB_PATH = os.path.join(DB_DIR, "civicpulse.db")
SCHEMA_PATH = os.path.join(DB_DIR, "schema.sql")


def get_db_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """
    Restituisce una connessione SQLite3 configurata con:
    - row_factory = sqlite3.Row (accesso alle colonne per nome come dizionario)
    - PRAGMA foreign_keys = ON (integrità referenziale attiva a livello DB)
    """
    target_path = db_path or DB_PATH
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    conn = sqlite3.connect(target_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def dict_from_row(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    """Converte un oggetto sqlite3.Row in un dizionario Python standard serializzabile in JSON."""
    if row is None:
        return None
    return dict(row)


def init_db(db_path: Optional[str] = None, force_reset: bool = False) -> None:
    """
    Inizializza il database creando le tabelle da schema.sql e inserendo i dati dimostrativi
    qualora il database sia vuoto (o se force_reset=True).
    """
    target_path = db_path or DB_PATH
    if force_reset and os.path.exists(target_path):
        os.remove(target_path)

    conn = get_db_connection(target_path)
    try:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())

        # Migrazione non distruttiva su database già esistenti per colonne disponibilità squadre
        existing_team_cols = {
            row["name"] for row in conn.execute("PRAGMA table_info(teams)").fetchall()
        }
        if "is_available" not in existing_team_cols:
            conn.execute(
                "ALTER TABLE teams ADD COLUMN is_available INTEGER NOT NULL DEFAULT 1"
            )
        if "unavailability_reason" not in existing_team_cols:
            conn.execute(
                "ALTER TABLE teams ADD COLUMN unavailability_reason TEXT DEFAULT ''"
            )
        if "unavailable_until" not in existing_team_cols:
            conn.execute(
                "ALTER TABLE teams ADD COLUMN unavailable_until TEXT DEFAULT ''"
            )
        conn.commit()

        # Verifica se il database contiene già utenti
        cur = conn.execute("SELECT COUNT(*) AS cnt FROM users")
        count = cur.fetchone()["cnt"]
        if count == 0:
            _seed_initial_data(conn)
            conn.commit()
    finally:
        conn.close()


def _seed_initial_data(conn: sqlite3.Connection) -> None:
    """Popola il database con squadre tecniche, utenti e segnalazioni georeferenziate a Modena."""
    # 1. Inserimento Squadre Operative Comunali
    teams_data = [
        (
            "Squadra Manutenzione Stradale & Segnaletica",
            "Settore Lavori Pubblici e Mobilità",
            "Ripristino manto stradale, piste ciclabili, marciapiedi e segnaletica verticale/orizzontale",
            "strade@comune.modena.demo.it",
            6,
        ),
        (
            "Squadra Impianti Elettrici & Smart Grid",
            "Servizi Tecnologici ed Energia",
            "Illuminazione pubblica LED, semafori intelligenti, colonnine EV e quadri elettrici",
            "energia@comune.modena.demo.it",
            5,
        ),
        (
            "Nucleo Cura del Verde & Arboricoltura",
            "Settore Ambiente e Verde Urbano",
            "Potature di sicurezza, manutenzione parchi storici, aree verdi e impianti d'irrigazione",
            "verde@comune.modena.demo.it",
            5,
        ),
        (
            "Unità Igiene Ambientale & Decoro Urbano",
            "Ambiente e Gestione Rifiuti",
            "Rimozione rifiuti abbandonati, pulizia straordinaria, bonifica micro-discariche e graffiti",
            "decoro@comune.modena.demo.it",
            7,
        ),
        (
            "Pronto Intervento Idrico & Protezione Civile",
            "Sicurezza Idraulica e Sottoservizi",
            "Disostruzione caditoie, perdite rete idrica, allagamenti sottopassi e messa in sicurezza",
            "idrico@comune.modena.demo.it",
            6,
        ),
        (
            "Squadra Edilizia Civica & Arredo Urbano",
            "Patrimonio e Sicurezza Urbana",
            "Manutenzione panchine, aree gioco, fontane, barriere architettoniche e arredo",
            "arredo@comune.modena.demo.it",
            4,
        ),
    ]

    conn.executemany(
        """
        INSERT INTO teams (name, department, specialization, contact_email, active_members)
        VALUES (?, ?, ?, ?, ?)
        """,
        teams_data,
    )

    # Mappa nome squadra -> id
    team_rows = conn.execute("SELECT id, name FROM teams").fetchall()
    team_map = {r["name"]: r["id"] for r in team_rows}

    # 2. Inserimento Utenti (Password hashate con PBKDF2-SHA256 di Werkzeug)
    # Credenziali demo:
    # - admin / admin123 (Amministratore Centrale)
    # - operatore / operatore123 (Operatore Tecnico Squadra Strade)
    # - cittadino / cittadino123 (Studente / Cittadino UNIMORE)
    users_data = [
        (
            "admin",
            "Ing. Marco Valli (Resp. Centrale Operativa)",
            "marco.valli@comune.modena.demo.it",
            generate_password_hash("admin123"),
            "admin",
            team_map["Pronto Intervento Idrico & Protezione Civile"],
            250,
        ),
        (
            "operatore",
            "Geom. Elena Ferri (Tecnico Sul Campo)",
            "elena.ferri@comune.modena.demo.it",
            generate_password_hash("operatore123"),
            "operator",
            team_map["Squadra Manutenzione Stradale & Segnaletica"],
            180,
        ),
        (
            "cittadino",
            "Davide Rossi (Studente DIEF UNIMORE)",
            "davide.rossi@studenti.unimore.demo.it",
            generate_password_hash("cittadino123"),
            "citizen",
            None,
            85,
        ),
        (
            "giulia_b",
            "Dott.ssa Giulia Bertoni (Comitato Quartiere)",
            "giulia.bertoni@cittadini.modena.demo.it",
            generate_password_hash("cittadino123"),
            "citizen",
            None,
            60,
        ),
    ]

    conn.executemany(
        """
        INSERT INTO users (username, full_name, email, password_hash, role, team_id, reputation_points)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        users_data,
    )

    user_rows = conn.execute("SELECT id, username FROM users").fetchall()
    user_map = {r["username"]: r["id"] for r in user_rows}

    # 3. Inserimento Segnalazioni Georeferenziate a Modena (con calcolo reale AI Triage)
    seed_reports = [
        {
            "code": "CPM-2026-001",
            "title": "Buca profonda e pericolosa su pista ciclabile ingresso Campus DIEF",
            "description": (
                "All'altezza dell'attraversamento ciclabile di Via Pietro Vivarelli 10 (ingresso Campus "
                "Ingegneria Enzo Ferrari UNIMORE) si è aperta una buca profonda circa 12 cm nell'asfalto. "
                "Rischio elevato di caduta per studenti in bicicletta e monopattino, specialmente nelle ore serali."
            ),
            "category": "strade_viabilita",
            "priority": "alta",
            "status": "in_lavorazione",
            "address": "Via Pietro Vivarelli 10, Modena (Campus DIEF UNIMORE)",
            "quartiere": "Crocetta - San Lazzaro - Modena Est",
            "latitude": 44.6294,
            "longitude": 10.9482,
            "image_url": "/static/uploads/demo_buca_dief.jpg",
            "upvotes": 24,
            "author_id": user_map["cittadino"],
            "created_at": "2026-11-02 09:15:00",
            "updated_at": "2026-11-05 14:30:00",
            "resolved_at": None,
        },
        {
            "code": "CPM-2026-002",
            "title": "Lampioni spenti e cavo scoperto nel vialetto del Parco Enzo Ferrari",
            "description": (
                "Tre lampioni consecutivi lungo il viale principale del Parco Enzo Ferrari sono completamente "
                "spenti da due notti. Alla base del secondo palo lo sportellino del quadro elettrico risulta "
                "aperto con cavo scoperto vicino al percorso pedonale. Intervento urgente richiesto per sicurezza."
            ),
            "category": "illuminazione_energia",
            "priority": "critica",
            "status": "aperta",
            "address": "Viale Autodromo 35, Modena (Parco Enzo Ferrari)",
            "quartiere": "San Faustino - Madonnina - Quattro Ville",
            "latitude": 44.6512,
            "longitude": 10.9065,
            "image_url": "/static/uploads/demo_lampione_parco.jpg",
            "upvotes": 31,
            "author_id": user_map["giulia_b"],
            "created_at": "2026-11-06 19:40:00",
            "updated_at": "2026-11-06 19:40:00",
            "resolved_at": None,
        },
        {
            "code": "CPM-2026-003",
            "title": "Tombini ostruiti e allagamento carreggiata nel sottopasso Stazione FS",
            "description": (
                "Le caditoie stradali in prossimità di Piazza Dante Alighieri / Stazione Centrale risultano "
                "completamente ostruite da fogliame e detriti. Durante le piogge si verifica un importante "
                "allagamento della corsia autobus e del passaggio pedonale."
            ),
            "category": "idrico_allagamenti",
            "priority": "critica",
            "status": "in_lavorazione",
            "address": "Piazza Dante Alighieri 1, Modena (Stazione FS)",
            "quartiere": "Centro Storico - Crocetta",
            "latitude": 44.6548,
            "longitude": 10.9301,
            "image_url": "/static/uploads/demo_allagamento_stazione.jpg",
            "upvotes": 19,
            "author_id": user_map["cittadino"],
            "created_at": "2026-11-04 08:20:00",
            "updated_at": "2026-11-06 11:10:00",
            "resolved_at": None,
        },
        {
            "code": "CPM-2026-004",
            "title": "Ramo spezzato pericolante sopra le panchine ai Giardini Ducali",
            "description": (
                "Un grosso ramo di un albero storico all'interno dei Giardini Ducali (lato Corso Canalgrande) "
                "si è parzialmente spezzato a seguito del vento forte e pende sopra l'area panchine vicino "
                "all'area gioco bambini. Necessaria potatura in quota e transennamento."
            ),
            "category": "ambiente_verde",
            "priority": "alta",
            "status": "sospesa_meteo",
            "address": "Corso Canalgrande 88, Modena (Giardini Ducali)",
            "quartiere": "Centro Storico",
            "latitude": 44.6487,
            "longitude": 10.9296,
            "image_url": "/static/uploads/demo_ramo_giardini.jpg",
            "upvotes": 15,
            "author_id": user_map["giulia_b"],
            "created_at": "2026-11-03 16:05:00",
            "updated_at": "2026-11-05 09:00:00",
            "resolved_at": None,
        },
        {
            "code": "CPM-2026-005",
            "title": "Abbandono rifiuti ingombranti e vetri presso isola ecologica Via Vignolese",
            "description": (
                "Segnalo abbandono illecito di materassi, mobili smontati e sacchi di spazzatura fuori dai "
                "cassonetti intelligenti in Via Vignolese vicino alla rotonda universitaria. Presenti anche "
                "vetri rotti sul marciapiede."
            ),
            "category": "rifiuti_decoro",
            "priority": "media",
            "status": "risolta",
            "address": "Via Vignolese 610, Modena",
            "quartiere": "Buon Pastore - Sant'Agnese - San Damaso",
            "latitude": 44.6318,
            "longitude": 10.9395,
            "image_url": "/static/uploads/demo_rifiuti_vignolese.jpg",
            "upvotes": 11,
            "author_id": user_map["cittadino"],
            "created_at": "2026-10-29 10:30:00",
            "updated_at": "2026-10-31 15:45:00",
            "resolved_at": "2026-10-31 15:45:00",
        },
        {
            "code": "CPM-2026-006",
            "title": "Ripristino lastricato in porfido e rampa disabili in Piazza Grande",
            "description": (
                "Alcuni cubetti di porfido lungo la rampa di accesso per persone con disabilità sul lato "
                "di Piazza Grande / Corso Duomo risultano sollevati, rendendo difficoltoso il transito "
                "alle carrozzine."
            ),
            "category": "sicurezza_arredo",
            "priority": "alta",
            "status": "risolta",
            "address": "Piazza Grande, Modena (Sito UNESCO)",
            "quartiere": "Centro Storico",
            "latitude": 44.6463,
            "longitude": 10.9255,
            "image_url": "/static/uploads/demo_arredo_piazza.jpg",
            "upvotes": 28,
            "author_id": user_map["giulia_b"],
            "created_at": "2026-10-25 11:00:00",
            "updated_at": "2026-10-27 17:20:00",
            "resolved_at": "2026-10-27 17:20:00",
        },
        {
            "code": "CPM-2026-007",
            "title": "Semaforo pedonale a chiamata guasto davanti al Policlinico di Modena",
            "description": (
                "Il pulsante di prenotazione dell'attraversamento semaforico in Via del Pozzo (ingresso "
                "principale Policlinico) è bloccato e il segnale acustico per non vedenti non funziona. "
                "Transito continuo di pazienti, anziani e personale sanitario."
            ),
            "category": "illuminazione_energia",
            "priority": "critica",
            "status": "aperta",
            "address": "Via del Pozzo 71, Modena (Policlinico)",
            "quartiere": "Buon Pastore - Sant'Agnese - San Damaso",
            "latitude": 44.6352,
            "longitude": 10.9428,
            "image_url": "/static/uploads/demo_semaforo_policlinico.jpg",
            "upvotes": 37,
            "author_id": user_map["cittadino"],
            "created_at": "2026-11-07 08:10:00",
            "updated_at": "2026-11-07 08:10:00",
            "resolved_at": None,
        },
    ]

    for item in seed_reports:
        ai_res = analyze_report_text(item["title"], item["description"], item["category"])
        assigned_team_id = team_map.get(ai_res["recommended_team"])
        conn.execute(
            """
            INSERT INTO reports (
                code, title, description, category, priority, status,
                address, quartiere, latitude, longitude, image_url, upvotes,
                ai_urgency_score, ai_suggested_category, ai_estimated_sla_hours,
                ai_reasoning, weather_sensitive, author_id, assigned_team_id,
                created_at, updated_at, resolved_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["code"],
                item["title"],
                item["description"],
                item["category"],
                item["priority"],
                item["status"],
                item["address"],
                item["quartiere"],
                item["latitude"],
                item["longitude"],
                item["image_url"],
                item["upvotes"],
                ai_res["ai_urgency_score"],
                ai_res["ai_suggested_category"],
                ai_res["ai_estimated_sla_hours"],
                ai_res["ai_reasoning"],
                ai_res["weather_sensitive"],
                item["author_id"],
                assigned_team_id,
                item["created_at"],
                item["updated_at"],
                item["resolved_at"],
            ),
        )

    # 4. Inserimento Commenti / Note Tecniche Ufficiali
    comments_data = [
        (
            1,
            user_map["operatore"],
            "Sopralluogo effettuato con strumentazione laser. Area delimitata con birilli catarifrangenti; posa conglomerato bituminoso a caldo programmata per domani mattina.",
            1,
            "2026-11-03 11:20:00",
        ),
        (
            1,
            user_map["cittadino"],
            "Grazie mille per il rapido posizionamento della segnaletica provvisoria! Ora la buca è ben visibile anche di sera.",
            0,
            "2026-11-04 18:05:00",
        ),
        (
            3,
            user_map["admin"],
            "Inviata autospurgo del Pronto Intervento Idrico per aspirazione fogliame e lavaggio condotta principale prima della perturbazione prevista.",
            1,
            "2026-11-05 10:15:00",
        ),
        (
            4,
            user_map["operatore"],
            "Area sottostante messa in sicurezza con transenne metalliche. L'intervento con piattaforma aerea cestello è temporaneamente sospeso per raffiche di vento superiori ai limiti di sicurezza cantiere.",
            1,
            "2026-11-05 09:00:00",
        ),
        (
            5,
            user_map["admin"],
            "Bonifica completata dall'Unità Igiene Ambientale e spazzamento meccanizzato eseguito. Chiusura ticket con esito positivo.",
            1,
            "2026-10-31 15:45:00",
        ),
    ]

    conn.executemany(
        """
        INSERT INTO comments (report_id, user_id, content, is_official_update, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [(r_id, u_id, txt, off, dt, dt) for (r_id, u_id, txt, off, dt) in comments_data],
    )


# ============================================================================
# FUNZIONI DI QUERY E CRUD SULLE SEGNALAZIONI (REPORTS)
# ============================================================================

def query_reports(
    search: str = "",
    category: str = "",
    status: str = "",
    priority: str = "",
    quartiere: str = "",
    sort_by: str = "newest",
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Recupera l'elenco delle segnalazioni applicando filtri combinati lato SQL
    (con join su users e teams e conteggio commenti).
    """
    conn = get_db_connection(db_path)
    try:
        sql = """
            SELECT
                r.*,
                u.full_name AS author_name,
                u.username AS author_username,
                u.role AS author_role,
                t.name AS team_name,
                t.department AS team_department,
                (SELECT COUNT(*) FROM comments c WHERE c.report_id = r.id) AS comments_count
            FROM reports r
            JOIN users u ON r.author_id = u.id
            LEFT JOIN teams t ON r.assigned_team_id = t.id
            WHERE 1=1
        """
        params: List[Any] = []

        if search:
            sql += " AND (LOWER(r.title) LIKE ? OR LOWER(r.description) LIKE ? OR LOWER(r.address) LIKE ? OR LOWER(r.code) LIKE ?)"
            pattern = f"%{search.lower()}%"
            params.extend([pattern, pattern, pattern, pattern])

        if category:
            sql += " AND r.category = ?"
            params.append(category)

        if status:
            sql += " AND r.status = ?"
            params.append(status)

        if priority:
            sql += " AND r.priority = ?"
            params.append(priority)

        if quartiere:
            sql += " AND r.quartiere = ?"
            params.append(quartiere)

        # Ordinamento sicuro tramite whitelist
        order_map = {
            "newest": "r.created_at DESC, r.id DESC",
            "urgency": "r.ai_urgency_score DESC, r.upvotes DESC",
            "upvotes": "r.upvotes DESC, r.created_at DESC",
            "oldest": "r.created_at ASC",
        }
        sql += f" ORDER BY {order_map.get(sort_by, order_map['newest'])}"

        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_report_by_id(report_id: int, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Restituisce una singola segnalazione completa di metadati autore, squadra e commenti."""
    conn = get_db_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT
                r.*,
                u.full_name AS author_name,
                u.username AS author_username,
                u.role AS author_role,
                t.name AS team_name,
                t.department AS team_department,
                t.contact_email AS team_email
            FROM reports r
            JOIN users u ON r.author_id = u.id
            LEFT JOIN teams t ON r.assigned_team_id = t.id
            WHERE r.id = ?
            """,
            (report_id,),
        ).fetchone()

        if not row:
            return None

        report = dict(row)
        comments = conn.execute(
            """
            SELECT
                c.*,
                u.full_name AS author_name,
                u.username AS author_username,
                u.role AS author_role
            FROM comments c
            JOIN users u ON c.user_id = u.id
            WHERE c.report_id = ?
            ORDER BY c.created_at ASC, c.id ASC
            """,
            (report_id,),
        ).fetchall()
        report["comments"] = [dict(c) for c in comments]
        return report
    finally:
        conn.close()


def create_report(data: Dict[str, Any], db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    CREATE: Inserisce una nuova segnalazione calcolando il codice univoco progressivo
    e applicando l'analisi AI/NLP per urgenza, SLA e assegnazione automatica squadra.
    """
    conn = get_db_connection(db_path)
    try:
        ai_res = analyze_report_text(data["title"], data["description"], data["category"])

        # Assegnazione automatica squadra se non specificata manualmente
        assigned_team_id = data.get("assigned_team_id")
        if not assigned_team_id:
            team_row = conn.execute(
                "SELECT id FROM teams WHERE name = ?", (ai_res["recommended_team"],)
            ).fetchone()
            assigned_team_id = team_row["id"] if team_row else 1

        # Generazione codice progressivo CPM-2026-XXX
        max_id_row = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM reports").fetchone()
        next_num = max_id_row["next_id"]
        code = f"CPM-2026-{next_num:03d}"

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        priority = data.get("priority") or ai_res["suggested_priority"]

        cur = conn.execute(
            """
            INSERT INTO reports (
                code, title, description, category, priority, status,
                address, quartiere, latitude, longitude, image_url, upvotes,
                ai_urgency_score, ai_suggested_category, ai_estimated_sla_hours,
                ai_reasoning, weather_sensitive, author_id, assigned_team_id,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'aperta', ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                code,
                data["title"].strip(),
                data["description"].strip(),
                data["category"],
                priority,
                data["address"].strip(),
                data["quartiere"].strip(),
                float(data["latitude"]),
                float(data["longitude"]),
                data.get("image_url", ""),
                ai_res["ai_urgency_score"],
                ai_res["ai_suggested_category"],
                ai_res["ai_estimated_sla_hours"],
                ai_res["ai_reasoning"],
                ai_res["weather_sensitive"],
                int(data["author_id"]),
                int(assigned_team_id),
                now_str,
                now_str,
            ),
        )
        new_id = cur.lastrowid

        # Incrementa punti reputazione civica dell'autore
        conn.execute(
            "UPDATE users SET reputation_points = reputation_points + 15 WHERE id = ?",
            (int(data["author_id"]),),
        )
        conn.commit()
    finally:
        conn.close()

    return get_report_by_id(new_id, db_path)


def update_report(report_id: int, data: Dict[str, Any], db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    UPDATE: Aggiorna i campi di una segnalazione esistente, ricalcolando i metadati AI
    qualora titolo, descrizione o categoria siano stati modificati.
    """
    existing = get_report_by_id(report_id, db_path)
    if not existing:
        return None

    title = data.get("title", existing["title"]).strip()
    description = data.get("description", existing["description"]).strip()
    category = data.get("category", existing["category"])
    priority = data.get("priority", existing["priority"])
    status = data.get("status", existing["status"])
    address = data.get("address", existing["address"]).strip()
    quartiere = data.get("quartiere", existing["quartiere"]).strip()
    latitude = float(data.get("latitude", existing["latitude"]))
    longitude = float(data.get("longitude", existing["longitude"]))
    image_url = data.get("image_url", existing["image_url"])
    assigned_team_id = data.get("assigned_team_id", existing["assigned_team_id"])

    # Ricalcola l'analisi AI sul testo aggiornato
    ai_res = analyze_report_text(title, description, category)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    resolved_at = existing["resolved_at"]
    if status in ("risolta", "chiusa") and not resolved_at:
        resolved_at = now_str
    elif status not in ("risolta", "chiusa"):
        resolved_at = None

    conn = get_db_connection(db_path)
    try:
        conn.execute(
            """
            UPDATE reports
            SET title = ?,
                description = ?,
                category = ?,
                priority = ?,
                status = ?,
                address = ?,
                quartiere = ?,
                latitude = ?,
                longitude = ?,
                image_url = ?,
                assigned_team_id = ?,
                ai_urgency_score = ?,
                ai_suggested_category = ?,
                ai_estimated_sla_hours = ?,
                ai_reasoning = ?,
                weather_sensitive = ?,
                updated_at = ?,
                resolved_at = ?
            WHERE id = ?
            """,
            (
                title,
                description,
                category,
                priority,
                status,
                address,
                quartiere,
                latitude,
                longitude,
                image_url,
                assigned_team_id,
                ai_res["ai_urgency_score"],
                ai_res["ai_suggested_category"],
                ai_res["ai_estimated_sla_hours"],
                ai_res["ai_reasoning"],
                ai_res["weather_sensitive"],
                now_str,
                resolved_at,
                report_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return get_report_by_id(report_id, db_path)


def delete_report(report_id: int, db_path: Optional[str] = None) -> bool:
    """DELETE: Elimina una segnalazione e a cascata (ON DELETE CASCADE) i relativi commenti e voti."""
    conn = get_db_connection(db_path)
    try:
        cur = conn.execute("DELETE FROM reports WHERE id = ?", (report_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def toggle_upvote(report_id: int, user_id: Optional[int] = None, db_path: Optional[str] = None) -> Optional[int]:
    """Incrementa il contatore di conferme civiche (upvotes) di una segnalazione."""
    conn = get_db_connection(db_path)
    try:
        row = conn.execute("SELECT upvotes FROM reports WHERE id = ?", (report_id,)).fetchone()
        if not row:
            return None
        conn.execute("UPDATE reports SET upvotes = upvotes + 1 WHERE id = ?", (report_id,))
        conn.commit()
        updated = conn.execute("SELECT upvotes FROM reports WHERE id = ?", (report_id,)).fetchone()
        return updated["upvotes"]
    finally:
        conn.close()


# ============================================================================
# FUNZIONI CRUD SUI COMMENTI / LOG OPERATIVI
# ============================================================================

def add_comment(
    report_id: int,
    user_id: int,
    content: str,
    is_official_update: int = 0,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """CREATE Comment: Aggiunge un commento o nota tecnica ufficiale a una segnalazione."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_connection(db_path)
    try:
        cur = conn.execute(
            """
            INSERT INTO comments (report_id, user_id, content, is_official_update, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (report_id, user_id, content.strip(), int(bool(is_official_update)), now_str, now_str),
        )
        comment_id = cur.lastrowid
        conn.execute("UPDATE reports SET updated_at = ? WHERE id = ?", (now_str, report_id))
        conn.commit()

        row = conn.execute(
            """
            SELECT c.*, u.full_name AS author_name, u.username AS author_username, u.role AS author_role
            FROM comments c
            JOIN users u ON c.user_id = u.id
            WHERE c.id = ?
            """,
            (comment_id,),
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def update_comment(comment_id: int, content: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """UPDATE Comment: Modifica il testo di un commento esistente."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_connection(db_path)
    try:
        cur = conn.execute(
            "UPDATE comments SET content = ?, updated_at = ? WHERE id = ?",
            (content.strip(), now_str, comment_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            return None
        row = conn.execute(
            """
            SELECT c.*, u.full_name AS author_name, u.username AS author_username, u.role AS author_role
            FROM comments c
            JOIN users u ON c.user_id = u.id
            WHERE c.id = ?
            """,
            (comment_id,),
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def delete_comment(comment_id: int, db_path: Optional[str] = None) -> bool:
    """DELETE Comment: Rimuove un commento dal database."""
    conn = get_db_connection(db_path)
    try:
        cur = conn.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_comment_by_id(comment_id: int, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Recupera un singolo commento per controlli di autorizzazione."""
    conn = get_db_connection(db_path)
    try:
        row = conn.execute("SELECT * FROM comments WHERE id = ?", (comment_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ============================================================================
# FUNZIONI UTENTI, SQUADRE E STATISTICHE ANALITICHE DASHBOARD
# ============================================================================

def _hydrate_team(conn: sqlite3.Connection, row: sqlite3.Row) -> Dict[str, Any]:
    """Calcola la disponibilità effettiva di una squadra (manuale + assenza di incarichi in corso)."""
    item = dict(row)
    manual_avail = bool(item.get("is_available", 1))
    busy_row = conn.execute(
        """
        SELECT id, code, title, status
        FROM reports
        WHERE assigned_team_id = ? AND status IN ('in_lavorazione', 'sospesa_meteo')
        ORDER BY updated_at DESC, id DESC
        LIMIT 1
        """,
        (item["id"],),
    ).fetchone()

    is_busy = busy_row is not None
    item["manual_available"] = manual_avail
    item["is_busy"] = is_busy
    item["busy_report"] = dict(busy_row) if busy_row else None
    item["active_assigned"] = item.get("active_assigned") or 0
    item["in_progress_count"] = item.get("in_progress_count") or 0
    # Una squadra con un incarico in corso risulta automaticamente INDISPONIBILE fino al completamento
    item["is_available"] = bool(manual_avail and not is_busy)

    if is_busy:
        item["effective_reason"] = f"Incarico attivo: {busy_row['code']} — {busy_row['title']}"
        item["effective_until"] = "Fino a completamento lavoro"
    else:
        item["effective_reason"] = item.get("unavailability_reason") or ""
        item["effective_until"] = item.get("unavailable_until") or ""
    return item


def get_all_teams(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Restituisce tutte le squadre operative con stato disponibilità e numero di segnalazioni assegnate."""
    conn = get_db_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT
                t.*,
                COUNT(r.id) AS total_assigned,
                SUM(CASE WHEN r.status IN ('aperta', 'in_lavorazione', 'sospesa_meteo') THEN 1 ELSE 0 END) AS active_assigned,
                SUM(CASE WHEN r.status IN ('in_lavorazione', 'sospesa_meteo') THEN 1 ELSE 0 END) AS in_progress_count,
                (
                    SELECT COUNT(*)
                    FROM users u
                    WHERE u.team_id = t.id AND u.role = 'operator'
                ) AS operators_count
            FROM teams t
            LEFT JOIN reports r ON r.assigned_team_id = t.id
            GROUP BY t.id
            ORDER BY t.id ASC
            """
        ).fetchall()
        return [_hydrate_team(conn, r) for r in rows]
    finally:
        conn.close()


def get_team_by_id(team_id: int, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Restituisce una singola squadra operativa con stato disponibilità, incarico attivo e operatori."""
    conn = get_db_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT
                t.*,
                COUNT(r.id) AS total_assigned,
                SUM(CASE WHEN r.status IN ('aperta', 'in_lavorazione', 'sospesa_meteo') THEN 1 ELSE 0 END) AS active_assigned,
                SUM(CASE WHEN r.status IN ('in_lavorazione', 'sospesa_meteo') THEN 1 ELSE 0 END) AS in_progress_count
            FROM teams t
            LEFT JOIN reports r ON r.assigned_team_id = t.id
            WHERE t.id = ?
            GROUP BY t.id
            """,
            (team_id,),
        ).fetchone()
        if not row:
            return None
        return _hydrate_team(conn, row)
    finally:
        conn.close()


def create_team(
    name: str,
    department: str,
    specialization: str,
    contact_email: str,
    active_members: int = 4,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Registra una nuova squadra operativa comunale (disponibile di default)."""
    conn = get_db_connection(db_path)
    try:
        cur = conn.execute(
            """
            INSERT INTO teams (name, department, specialization, contact_email, active_members, is_available, unavailability_reason, unavailable_until)
            VALUES (?, ?, ?, ?, ?, 1, '', '')
            """,
            (
                name.strip(),
                department.strip(),
                specialization.strip(),
                contact_email.strip(),
                max(1, int(active_members)),
            ),
        )
        new_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    return get_team_by_id(new_id, db_path)


def update_team_availability(
    team_id: int,
    is_available: bool,
    reason: str = "",
    until_time: str = "",
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Aggiorna la disponibilità di una squadra operativa (e l'eventuale motivo/fascia oraria)."""
    existing = get_team_by_id(team_id, db_path)
    if not existing:
        return None

    avail_int = 1 if is_available else 0
    clean_reason = "" if is_available else (reason or "").strip()[:240]
    clean_until = "" if is_available else (until_time or "").strip()[:80]

    conn = get_db_connection(db_path)
    try:
        conn.execute(
            """
            UPDATE teams
            SET is_available = ?, unavailability_reason = ?, unavailable_until = ?
            WHERE id = ?
            """,
            (avail_int, clean_reason, clean_until, team_id),
        )
        conn.commit()
    finally:
        conn.close()
    return get_team_by_id(team_id, db_path)


def assign_report_to_team(
    report_id: int,
    team_id: int,
    new_status: str = "in_lavorazione",
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Assegna un compito a una squadra disponibile e aggiorna lo stato (es. in_lavorazione)."""
    return update_report(
        report_id,
        {"assigned_team_id": team_id, "status": new_status},
        db_path=db_path,
    )


def get_reports_by_team(team_id: int, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Restituisce tutte le segnalazioni assegnate a una specifica squadra, ordinate per priorità/data."""
    conn = get_db_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT
                r.*,
                u.full_name AS author_name,
                t.name AS team_name
            FROM reports r
            LEFT JOIN users u ON r.author_id = u.id
            LEFT JOIN teams t ON r.assigned_team_id = t.id
            WHERE r.assigned_team_id = ?
            ORDER BY
                CASE r.status WHEN 'aperta' THEN 1 WHEN 'in_lavorazione' THEN 2 WHEN 'sospesa_meteo' THEN 3 ELSE 4 END ASC,
                r.ai_urgency_score DESC,
                r.created_at DESC
            """,
            (team_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_user_by_username(username: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    conn = get_db_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT u.*, t.name AS team_name
            FROM users u
            LEFT JOIN teams t ON u.team_id = t.id
            WHERE u.username = ?
            """,
            (username.strip(),),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_id(user_id: int, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    conn = get_db_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT u.*, t.name AS team_name
            FROM users u
            LEFT JOIN teams t ON u.team_id = t.id
            WHERE u.id = ?
            """,
            (user_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def create_user(username: str, full_name: str, email: str, password: str, role: str = "citizen", db_path: Optional[str] = None) -> Dict[str, Any]:
    conn = get_db_connection(db_path)
    try:
        cur = conn.execute(
            """
            INSERT INTO users (username, full_name, email, password_hash, role, reputation_points)
            VALUES (?, ?, ?, ?, ?, 20)
            """,
            (username.strip(), full_name.strip(), email.strip(), generate_password_hash(password), role),
        )
        new_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    return get_user_by_id(new_id, db_path)


def get_dashboard_analytics(db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Calcola gli indicatori KPI e le distribuzioni aggregate per la Dashboard Analitica
    e per i grafici interattivi Chart.js.
    """
    conn = get_db_connection(db_path)
    try:
        kpi_row = conn.execute(
            """
            SELECT
                COUNT(*) AS total_reports,
                SUM(CASE WHEN status = 'aperta' THEN 1 ELSE 0 END) AS open_reports,
                SUM(CASE WHEN status = 'in_lavorazione' THEN 1 ELSE 0 END) AS in_progress_reports,
                SUM(CASE WHEN status = 'sospesa_meteo' THEN 1 ELSE 0 END) AS weather_hold_reports,
                SUM(CASE WHEN status IN ('risolta', 'chiusa') THEN 1 ELSE 0 END) AS resolved_reports,
                SUM(CASE WHEN priority = 'critica' AND status NOT IN ('risolta', 'chiusa') THEN 1 ELSE 0 END) AS active_critical,
                ROUND(AVG(ai_urgency_score), 1) AS avg_urgency_score,
                ROUND(AVG(ai_estimated_sla_hours), 1) AS avg_sla_hours,
                SUM(upvotes) AS total_upvotes
            FROM reports
            """
        ).fetchone()

        by_category = conn.execute(
            """
            SELECT category, COUNT(*) AS count
            FROM reports
            GROUP BY category
            ORDER BY count DESC
            """
        ).fetchall()

        by_status = conn.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM reports
            GROUP BY status
            """
        ).fetchall()

        by_priority = conn.execute(
            """
            SELECT priority, COUNT(*) AS count
            FROM reports
            GROUP BY priority
            """
        ).fetchall()

        by_quartiere = conn.execute(
            """
            SELECT quartiere, COUNT(*) AS count, ROUND(AVG(ai_urgency_score), 1) AS avg_urgency
            FROM reports
            GROUP BY quartiere
            ORDER BY count DESC
            """
        ).fetchall()

        total = kpi_row["total_reports"] or 0
        resolved = kpi_row["resolved_reports"] or 0
        resolution_rate = round((resolved / total) * 100, 1) if total > 0 else 0.0

        return {
            "kpi": {
                "total_reports": total,
                "open_reports": kpi_row["open_reports"] or 0,
                "in_progress_reports": kpi_row["in_progress_reports"] or 0,
                "weather_hold_reports": kpi_row["weather_hold_reports"] or 0,
                "resolved_reports": resolved,
                "active_critical": kpi_row["active_critical"] or 0,
                "avg_urgency_score": kpi_row["avg_urgency_score"] or 0.0,
                "avg_sla_hours": kpi_row["avg_sla_hours"] or 0.0,
                "total_upvotes": kpi_row["total_upvotes"] or 0,
                "resolution_rate": resolution_rate,
            },
            "by_category": [dict(r) for r in by_category],
            "by_status": [dict(r) for r in by_status],
            "by_priority": [dict(r) for r in by_priority],
            "by_quartiere": [dict(r) for r in by_quartiere],
            "teams": get_all_teams(db_path),
        }
    finally:
        conn.close()

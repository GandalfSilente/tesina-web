"""
app.py - Backend Principale Flask per CivicPulse Modena
=======================================================
Corso di Intelligenza Artificiale e Tecnologie Web (AA 2026-2027) - UNIMORE
Docente: Prof.ssa Laura Po

Architettura Ibrida Multi-Livello:
1. Presentazione SSR (Jinja2 Templates ereditati da base.html) + SPA React 19 (/kanban);
2. Servizi RESTful JSON (/api/...) per operazioni CRUD asincrone, filtri dinamici e grafici;
3. Moduli "Sporcarsi le Mani":
   - Motore AI/NLP di Auto-Triage (/api/ai/analyze) con Explainable AI e calcolo SLA;
   - Notifiche Real-Time push tramite protocollo Server-Sent Events (SSE - /api/stream);
   - Georeferenziazione interattiva OpenStreetMap/Leaflet + Correlazione Meteo (Open-Meteo API);
   - Progressive Web App (PWA) con Service Worker e caching offline-first.
"""

import csv
import io
import json
import os
import queue
import time
import urllib.request
from datetime import datetime
from typing import Dict, Any, List, Optional

from flask import (
    Flask,
    Response,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename

import database as db
from ai_engine import analyze_report_text, CATEGORY_METADATA

# ============================================================================
# CONFIGURAZIONE APPLICAZIONE FLASK
# ============================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "svg", "gif"}

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("CIVICPULSE_SECRET") or os.urandom(32)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # Max 8 MB per foto allegata
app.config["DATABASE_PATH"] = db.DB_PATH

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Dizionari costanti di dominio esposti a template e validatori
CATEGORIES: Dict[str, Dict[str, str]] = {
    "strade_viabilita": {
        "label": "Strade, Viabilità e Ciclabili",
        "icon": "fa-road",
        "color": "#ef4444",
        "badge_class": "cat-strade",
    },
    "illuminazione_energia": {
        "label": "Illuminazione & Rete Elettrica",
        "icon": "fa-bolt",
        "color": "#f59e0b",
        "badge_class": "cat-luce",
    },
    "ambiente_verde": {
        "label": "Verde Pubblico & Alberature",
        "icon": "fa-tree",
        "color": "#10b981",
        "badge_class": "cat-verde",
    },
    "rifiuti_decoro": {
        "label": "Rifiuti, Igiene e Decoro",
        "icon": "fa-recycle",
        "color": "#8b5cf6",
        "badge_class": "cat-rifiuti",
    },
    "idrico_allagamenti": {
        "label": "Rete Idrica & Allagamenti",
        "icon": "fa-water",
        "color": "#0284c7",
        "badge_class": "cat-idrico",
    },
    "sicurezza_arredo": {
        "label": "Arredo Urbano & Accessibilità",
        "icon": "fa-universal-access",
        "color": "#6366f1",
        "badge_class": "cat-arredo",
    },
}

PRIORITIES: Dict[str, Dict[str, str]] = {
    "bassa": {"label": "Bassa", "color": "#64748b", "badge": "prio-bassa"},
    "media": {"label": "Media", "color": "#0284c7", "badge": "prio-media"},
    "alta": {"label": "Alta", "color": "#f97316", "badge": "prio-alta"},
    "critica": {"label": "Critica", "color": "#dc2626", "badge": "prio-critica"},
}

STATUSES: Dict[str, Dict[str, str]] = {
    "aperta": {"label": "Aperta (In Attesa)", "icon": "fa-circle-exclamation", "badge": "status-aperta"},
    "in_lavorazione": {"label": "In Lavorazione", "icon": "fa-helmet-safety", "badge": "status-lavorazione"},
    "sospesa_meteo": {"label": "Sospesa per Meteo", "icon": "fa-cloud-showers-heavy", "badge": "status-meteo"},
    "risolta": {"label": "Risolta", "icon": "fa-circle-check", "badge": "status-risolta"},
    "chiusa": {"label": "Archiviata / Chiusa", "icon": "fa-box-archive", "badge": "status-chiusa"},
}

QUARTIERI_MODENA: List[str] = [
    "Centro Storico",
    "Centro Storico - Crocetta",
    "Crocetta - San Lazzaro - Modena Est",
    "Buon Pastore - Sant'Agnese - San Damaso",
    "San Faustino - Madonnina - Quattro Ville",
]

# ============================================================================
# BROKER EVENTI REAL-TIME (Server-Sent Events - SSE)
# ============================================================================

_sse_subscribers: List[queue.Queue] = []
_recent_events: List[Dict[str, Any]] = []


def broadcast_realtime_event(event_type: str, title: str, message: str, payload: Optional[Dict[str, Any]] = None) -> None:
    """
    Invia un evento in tempo reale a tutti i client browser connessi allo stream SSE (/api/stream)
    e conserva gli ultimi 15 eventi nel registro in-memory per la Control Room.
    """
    event_data = {
        "id": int(time.time() * 1000),
        "type": event_type,
        "title": title,
        "message": message,
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "payload": payload or {},
    }
    _recent_events.insert(0, event_data)
    if len(_recent_events) > 15:
        _recent_events.pop()

    stale_queues = []
    for q in _sse_subscribers:
        try:
            q.put_nowait(event_data)
        except queue.Full:
            stale_queues.append(q)

    for q in stale_queues:
        if q in _sse_subscribers:
            _sse_subscribers.remove(q)


# ============================================================================
# HELPER DI VALIDAZIONE, AUTENTICAZIONE E METEO
# ============================================================================

def get_db_path() -> str:
    return app.config.get("DATABASE_PATH", db.DB_PATH)


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def get_current_user() -> Optional[Dict[str, Any]]:
    """Recupera l'utente autenticato in sessione; se non loggato, restituisce None."""
    user_id = session.get("user_id")
    if not user_id:
        return None
    return db.get_user_by_id(user_id, get_db_path())


# Confini geografici rigorosi del solo territorio del Comune di Modena (esclude i comuni limitrofi)
MODENA_LAT_MIN = 44.5850
MODENA_LAT_MAX = 44.7150
MODENA_LON_MIN = 10.8350
MODENA_LON_MAX = 11.0150


def is_within_comune_di_modena(lat: float, lon: float) -> bool:
    """Verifica che le coordinate GPS ricadano esclusivamente entro il perimetro del Comune di Modena."""
    return (MODENA_LAT_MIN <= lat <= MODENA_LAT_MAX) and (MODENA_LON_MIN <= lon <= MODENA_LON_MAX)


def validate_report_payload(data: Dict[str, Any], is_update: bool = False) -> List[str]:
    """
    Validazione rigorosa Server-Side dei dati di una segnalazione (sia da Form HTML sia da API JSON).
    Restituisce una lista di messaggi di errore (vuota se tutti i campi sono validi).
    """
    errors: List[str] = []
    title = (data.get("title") or "").strip()
    description = (data.get("description") or "").strip()
    category = (data.get("category") or "").strip()
    address = (data.get("address") or "").strip()
    quartiere = (data.get("quartiere") or "").strip()
    priority = (data.get("priority") or "media").strip()
    status = (data.get("status") or "aperta").strip()

    if len(title) < 8 or len(title) > 140:
        errors.append("Il titolo deve contenere tra 8 e 140 caratteri.")
    if len(description) < 20 or len(description) > 2000:
        errors.append("La descrizione dettagliata deve contenere almeno 20 caratteri (max 2000).")
    if category not in CATEGORIES:
        errors.append("Seleziona una categoria valida dall'elenco.")
    if len(address) < 5 or len(address) > 160:
        errors.append("Inserisci un indirizzo valido situato nel Comune di Modena (min 5 caratteri).")
    if quartiere not in QUARTIERI_MODENA:
        errors.append("Seleziona una Circoscrizione / Quartiere valido del Comune di Modena.")
    if priority and priority not in PRIORITIES:
        errors.append("Livello di priorità non valido.")
    if is_update and status not in STATUSES:
        errors.append("Stato operativo non valido.")

    try:
        lat = float(data.get("latitude", 0))
        lon = float(data.get("longitude", 0))
        if not is_within_comune_di_modena(lat, lon):
            errors.append(
                f"Posizione fuori dal territorio del Comune di Modena! Sono consentite segnalazioni "
                f"solo all'interno dei confini comunali di Modena (Lat {MODENA_LAT_MIN}–{MODENA_LAT_MAX}, Lon {MODENA_LON_MIN}–{MODENA_LON_MAX})."
            )
    except (TypeError, ValueError):
        errors.append("Coordinate geografiche (latitudine/longitudine) non valide.")

    return errors


_weather_cache: Dict[str, Any] = {"timestamp": 0, "data": None}


def fetch_modena_weather() -> Dict[str, Any]:
    """
    Interroga l'API esterna pubblica Open-Meteo per le coordinate di Modena (44.6471, 10.9252)
    con caching di 10 minuti e fallback deterministico qualora la rete sia assente.
    Calcola inoltre l'Indice di Operatività Cantieri Esterni per le squadre tecniche.
    """
    now = time.time()
    if _weather_cache["data"] and (now - _weather_cache["timestamp"] < 600):
        return _weather_cache["data"]

    url = (
        "https://api.open-meteo.com/v1/forecast?"
        "latitude=44.6471&longitude=10.9252"
        "&current=temperature_2m,relative_humidity_2m,precipitation,weather_code,wind_speed_10m"
        "&timezone=Europe%2FRome"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CivicPulse-UNIMORE-TW/1.0"})
        with urllib.request.urlopen(req, timeout=1.2) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
            curr = raw.get("current", {})
            temp = float(curr.get("temperature_2m", 16.5))
            precip = float(curr.get("precipitation", 0.0))
            wind = float(curr.get("wind_speed_10m", 9.0))
            humidity = int(curr.get("relative_humidity_2m", 68))
            w_code = int(curr.get("weather_code", 1))
            source = "Open-Meteo API Live"
    except Exception:
        # Fallback deterministico per funzionamento garantito anche senza connessione Internet
        temp = 15.8
        precip = 0.0
        wind = 11.4
        humidity = 65
        w_code = 1
        source = "Sensore Locale Campus DIEF (Offline Fallback)"

    is_raining = precip > 0.5 or w_code in (51, 53, 55, 61, 63, 65, 80, 81, 82, 95, 96, 99)
    high_wind = wind > 35.0
    outdoor_work_safe = not (is_raining or high_wind)

    if is_raining:
        condition_label = "Pioggia in corso"
        icon = "fa-cloud-showers-heavy"
        advisory = "Attenzione: Posa asfalto a caldo e verniciatura segnaletica sconsigliate; priorità a caditoie e rischio idrico."
    elif high_wind:
        condition_label = "Vento forte"
        icon = "fa-wind"
        advisory = "Allerta vento: Sospendere gli interventi in quota con cestello aereo (potature e pali luce)."
    elif w_code in (0, 1):
        condition_label = "Sereno o poco nuvoloso"
        icon = "fa-sun"
        advisory = "Condizioni meteo ottimali per tutti i cantieri stradali, elettrici e di manutenzione del verde."
    else:
        condition_label = "Parzialmente nuvoloso"
        icon = "fa-cloud-sun"
        advisory = "Condizioni regolari: operatività squadre esterne garantita al 100%."

    weather_info = {
        "city": "Modena (MO)",
        "latitude": 44.6471,
        "longitude": 10.9252,
        "temperature_c": round(temp, 1),
        "precipitation_mm": round(precip, 1),
        "wind_kmh": round(wind, 1),
        "humidity_pct": humidity,
        "condition_label": condition_label,
        "icon": icon,
        "outdoor_work_safe": outdoor_work_safe,
        "advisory": advisory,
        "source": source,
        "updated_at": datetime.now().strftime("%H:%M"),
    }
    _weather_cache["timestamp"] = now
    _weather_cache["data"] = weather_info
    return weather_info


# ============================================================================
# CONTEXT PROCESSOR JINJA2 (Variabili Globali per tutti i Template)
# ============================================================================

@app.context_processor
def inject_globals() -> Dict[str, Any]:
    return {
        "current_year": datetime.now().year,
        "current_user": get_current_user(),
        "CATEGORIES": CATEGORIES,
        "PRIORITIES": PRIORITIES,
        "STATUSES": STATUSES,
        "QUARTIERI_MODENA": QUARTIERI_MODENA,
    }


# ============================================================================
# ROUTE FRONTEND (Server-Side Rendering con Jinja2 + Host SPA React)
# ============================================================================

@app.route("/")
def index():
    """
    VISTA 1: Home Page / Esplorazione Geografica & Catalogo Segnalazioni.
    Permette il filtraggio combinato (testo, categoria, stato, priorità, quartiere, ordinamento)
    e sincronizza la lista con la Mappa Interattiva Leaflet/OpenStreetMap e il Meteo Live.
    """
    search = request.args.get("search", "").strip()
    category = request.args.get("category", "").strip()
    status = request.args.get("status", "").strip()
    priority = request.args.get("priority", "").strip()
    quartiere = request.args.get("quartiere", "").strip()
    sort_by = request.args.get("sort_by", "newest").strip()

    reports = db.query_reports(
        search=search,
        category=category,
        status=status,
        priority=priority,
        quartiere=quartiere,
        sort_by=sort_by,
        db_path=get_db_path(),
    )
    analytics = db.get_dashboard_analytics(get_db_path())
    weather = fetch_modena_weather()

    return render_template(
        "index.html",
        reports=reports,
        kpi=analytics["kpi"],
        weather=weather,
        filters={
            "search": search,
            "category": category,
            "status": status,
            "priority": priority,
            "quartiere": quartiere,
            "sort_by": sort_by,
        },
    )


@app.route("/report/<int:report_id>")
def report_detail(report_id: int):
    """
    VISTA 2: Pagina di Dettaglio Segnalazione, Mappa Puntuale, Analisi AI,
    Gestione Stato Operatore e Timeline Commenti CRUD.
    """
    report = db.get_report_by_id(report_id, get_db_path())
    if not report:
        abort(404)

    teams = db.get_all_teams(get_db_path())
    weather = fetch_modena_weather()
    return render_template(
        "report_detail.html",
        report=report,
        teams=teams,
        weather=weather,
    )


@app.route("/report/new", methods=["GET", "POST"])
def report_create():
    """
    VISTA 3 (CREATE): Form di inserimento nuova segnalazione con AI Auto-Triage in tempo reale,
    selettore coordinate su mappa interattiva e upload foto opzionale.
    """
    teams = db.get_all_teams(get_db_path())
    if request.method == "GET":
        default_form = {
            "title": "",
            "description": "",
            "category": "strade_viabilita",
            "priority": "media",
            "address": "",
            "quartiere": "Crocetta - San Lazzaro - Modena Est",
            "latitude": "44.6294",
            "longitude": "10.9482",
        }
        return render_template(
            "report_form.html",
            is_edit=False,
            form_data=default_form,
            errors=[],
            teams=teams,
        )

    # Gestione invio POST (Pattern Post/Redirect/Get - PRG)
    form_data = {
        "title": request.form.get("title", "").strip(),
        "description": request.form.get("description", "").strip(),
        "category": request.form.get("category", "strade_viabilita").strip(),
        "priority": request.form.get("priority", "").strip(),
        "address": request.form.get("address", "").strip(),
        "quartiere": request.form.get("quartiere", "").strip(),
        "latitude": request.form.get("latitude", "44.6471").strip(),
        "longitude": request.form.get("longitude", "10.9252").strip(),
        "assigned_team_id": request.form.get("assigned_team_id", "").strip() or None,
    }

    errors = validate_report_payload(form_data, is_update=False)
    if errors:
        return (
            render_template(
                "report_form.html",
                is_edit=False,
                form_data=form_data,
                errors=errors,
                teams=teams,
            ),
            400,
        )

    # Gestione upload immagine allegata
    image_url = ""
    file = request.files.get("image_file")
    if file and file.filename:
        if not allowed_file(file.filename):
            return (
                render_template(
                    "report_form.html",
                    is_edit=False,
                    form_data=form_data,
                    errors=["Formato immagine non supportato. Usa PNG, JPG, WEBP o SVG."],
                    teams=teams,
                ),
                400,
            )
        safe_name = f"{int(time.time())}_{secure_filename(file.filename)}"
        file.save(os.path.join(app.config["UPLOAD_FOLDER"], safe_name))
        image_url = f"/static/uploads/{safe_name}"
    else:
        # Immagine illustrativa coerente con la categoria scelta
        cat_default_img = {
            "strade_viabilita": "/static/uploads/demo_buca_dief.jpg",
            "illuminazione_energia": "/static/uploads/demo_lampione_parco.jpg",
            "idrico_allagamenti": "/static/uploads/demo_allagamento_stazione.jpg",
            "ambiente_verde": "/static/uploads/demo_ramo_giardini.jpg",
            "rifiuti_decoro": "/static/uploads/demo_rifiuti_vignolese.jpg",
            "sicurezza_arredo": "/static/uploads/demo_arredo_piazza.jpg",
        }
        image_url = cat_default_img.get(form_data["category"], "/static/uploads/demo_buca_dief.svg")

    current_user = get_current_user()
    author_id = current_user["id"] if current_user else 3  # Default: Cittadino Demo

    form_data["image_url"] = image_url
    form_data["author_id"] = author_id

    created = db.create_report(form_data, get_db_path())
    broadcast_realtime_event(
        "report_created",
        f"Nuova Segnalazione {created['code']}",
        f"{created['title']} ({created['quartiere']}) — Urgenza AI: {created['ai_urgency_score']}/100",
        {"report_id": created["id"], "code": created["code"], "priority": created["priority"]},
    )
    flash(f"Segnalazione {created['code']} registrata con successo! Il modulo AI ha assegnato la pratica a: {created['team_name']}.", "success")
    return redirect(url_for("report_detail", report_id=created["id"]))


@app.route("/report/<int:report_id>/edit", methods=["GET", "POST"])
def report_edit(report_id: int):
    """
    VISTA 3 (UPDATE): Modifica completa di una segnalazione esistente.
    Riservata all'autore della segnalazione oppure a Operatori e Admin.
    """
    existing = db.get_report_by_id(report_id, get_db_path())
    if not existing:
        abort(404)

    user = get_current_user()
    if not user:
        flash("Devi effettuare l'accesso per modificare una segnalazione.", "warning")
        return redirect(url_for("login"))

    if user["role"] not in ("operator", "admin") and user["id"] != existing.get("author_id"):
        flash("Operazione non consentita: solo l'autore della segnalazione, un Operatore o un Admin possono modificarla.", "danger")
        return redirect(url_for("report_detail", report_id=report_id))

    teams = db.get_all_teams(get_db_path())
    if request.method == "GET":
        return render_template(
            "report_form.html",
            is_edit=True,
            report=existing,
            form_data=existing,
            errors=[],
            teams=teams,
        )

    is_staff = user["role"] in ("operator", "admin")
    raw_team_id = request.form.get("assigned_team_id")
    if user["role"] == "admin":
        if raw_team_id is not None and str(raw_team_id).strip() != "":
            try:
                target_team_id = int(raw_team_id)
            except (TypeError, ValueError):
                target_team_id = existing.get("assigned_team_id")
        else:
            target_team_id = existing.get("assigned_team_id")
    else:
        target_team_id = existing.get("assigned_team_id")

    form_data = {
        "title": request.form.get("title", existing["title"]).strip(),
        "description": request.form.get("description", existing["description"]).strip(),
        "category": request.form.get("category", existing["category"]).strip(),
        "priority": request.form.get("priority", existing["priority"]).strip(),
        "status": request.form.get("status", existing["status"]).strip() if is_staff else existing["status"],
        "address": request.form.get("address", existing["address"]).strip(),
        "quartiere": request.form.get("quartiere", existing["quartiere"]).strip(),
        "latitude": request.form.get("latitude", str(existing["latitude"])).strip(),
        "longitude": request.form.get("longitude", str(existing["longitude"])).strip(),
        "assigned_team_id": target_team_id,
        "image_url": existing["image_url"],
    }

    errors = validate_report_payload(form_data, is_update=True)
    if is_staff and target_team_id:
        target_team = db.get_team_by_id(target_team_id, get_db_path())
        if not target_team:
            errors.append("La squadra selezionata non esiste.")
        else:
            team_changed = target_team_id != existing.get("assigned_team_id")
            if team_changed and not target_team.get("is_available", True):
                busy = target_team.get("busy_report")
                errors.append(
                    f"La squadra '{target_team['name']}' ha già un incarico in corso ({busy['code']}) ed è indisponibile."
                    if busy
                    else f"La squadra '{target_team['name']}' è AL MOMENTO INDISPONIBILE."
                )
            if form_data["status"] in ("in_lavorazione", "sospesa_meteo"):
                busy = target_team.get("busy_report")
                if busy and int(busy["id"]) != int(report_id):
                    errors.append(
                        f"La squadra '{target_team['name']}' può gestire 1 solo incarico alla volta (sta già lavorando su {busy['code']})."
                    )
                if not target_team.get("manual_available", True) and existing.get("status") == "aperta":
                    errors.append(f"La squadra '{target_team['name']}' è contrassegnata come AL MOMENTO INDISPONIBILE.")
    if errors:
        return (
            render_template(
                "report_form.html",
                is_edit=True,
                report=existing,
                form_data=form_data,
                errors=errors,
                teams=teams,
            ),
            400,
        )

    file = request.files.get("image_file")
    if file and file.filename:
        if not allowed_file(file.filename):
            return (
                render_template(
                    "report_form.html",
                    is_edit=True,
                    report=existing,
                    form_data=form_data,
                    errors=["Formato immagine non valido. Usa PNG, JPG, WEBP o SVG."],
                    teams=teams,
                ),
                400,
            )
        safe_name = f"{int(time.time())}_{secure_filename(file.filename)}"
        file.save(os.path.join(app.config["UPLOAD_FOLDER"], safe_name))
        form_data["image_url"] = f"/static/uploads/{safe_name}"

    was_active = existing.get("status") in ("in_lavorazione", "sospesa_meteo")
    updated = db.update_report(report_id, form_data, get_db_path())
    broadcast_realtime_event(
        "report_updated",
        f"Aggiornata {updated['code']}",
        f"Stato: {STATUSES[updated['status']]['label']} • Priorità: {PRIORITIES[updated['priority']]['label']}",
        {"report_id": updated["id"], "status": updated["status"], "priority": updated["priority"]},
    )
    if was_active and updated["status"] in ("risolta", "chiusa") and updated.get("assigned_team_id"):
        refreshed_team = db.get_team_by_id(updated["assigned_team_id"], get_db_path())
        if refreshed_team and refreshed_team.get("is_available"):
            broadcast_realtime_event(
                "team_availability_changed",
                f"🟢 Squadra Libera: {refreshed_team['name']}",
                f"Lavoro su {updated['code']} completato! La squadra è tornata DISPONIBILE per nuovi incarichi.",
                {"team": refreshed_team},
            )
    flash(f"Segnalazione {updated['code']} aggiornata correttamente.", "success")
    return redirect(url_for("report_detail", report_id=report_id))


@app.route("/report/<int:report_id>/delete", methods=["POST"])
def report_delete(report_id: int):
    """
    DELETE: Eliminazione di una segnalazione tramite form POST con redirect.
    RISERVATA TASSATIVAMENTE ALL'AMMINISTRATORE (ADMIN).
    """
    existing = db.get_report_by_id(report_id, get_db_path())
    if not existing:
        abort(404)

    user = get_current_user()
    if not user:
        flash("Accesso negato: devi accedere come Amministratore (Admin) per eliminare una segnalazione.", "warning")
        return redirect(url_for("login"))

    if user["role"] != "admin":
        flash("Operazione non consentita: solo l'Amministratore (Admin) ha i permessi per eliminare una segnalazione.", "danger")
        return redirect(url_for("report_detail", report_id=report_id))

    code = existing["code"]
    db.delete_report(report_id, get_db_path())
    broadcast_realtime_event(
        "report_deleted",
        f"Rimossa Segnalazione {code}",
        f"La segnalazione {code} è stata eliminata dal registro operativo dall'Amministratore.",
        {"report_id": report_id, "code": code},
    )
    flash(f"Segnalazione {code} eliminata definitivamente dall'Amministratore.", "info")
    return redirect(url_for("index"))


@app.route("/dashboard")
def dashboard():
    """
    VISTA 4: Dashboard Analitica & Real-Time Operations Center.
    Mostra KPI cittadini, grafici Chart.js, stato squadre comunali, log SSE in tempo reale ed export dati.
    """
    analytics = db.get_dashboard_analytics(get_db_path())
    weather = fetch_modena_weather()
    recent_reports = db.query_reports(sort_by="urgency", db_path=get_db_path())[:6]
    return render_template(
        "dashboard.html",
        analytics=analytics,
        weather=weather,
        recent_reports=recent_reports,
        recent_events=_recent_events[:8],
    )


@app.route("/kanban")
def kanban_react():
    """
    VISTA 5: Applicazione SPA in React 19 (Live Triage & Kanban Board Operativa)
    integrata con le API RESTful di Flask (/api/reports, /api/reports/<id>/status).
    """
    return render_template("kanban_react.html")


@app.route("/admin/teams")
def admin_teams():
    """
    VISTA 7 (Solo Admin): Centrale Operativa di Smistamento Compiti APERTI con Drag & Drop
    sulle Squadre Disponibili e Registrazione Nuove Squadre Comunali.
    """
    user = get_current_user()
    if not user:
        flash("Devi effettuare l'accesso come Amministratore (Admin) per accedere allo smistamento squadre.", "warning")
        return redirect(url_for("login"))
    if user["role"] != "admin":
        flash("Area riservata esclusivamente all'Amministratore Centrale (Admin).", "danger")
        return redirect(url_for("index"))

    open_reports = db.query_reports(status="aperta", sort_by="urgency", db_path=get_db_path())
    teams = db.get_all_teams(get_db_path())
    return render_template(
        "admin_teams.html",
        open_reports=open_reports,
        teams=teams,
    )


@app.route("/operator/availability")
def operator_availability():
    """
    VISTA 8 (Solo Operatore): Console Operatore Tecnico per gestire la disponibilità
    della propria squadra assegnata e consultare i compiti assegnati dall'Admin.
    """
    user = get_current_user()
    if not user:
        flash("Devi effettuare l'accesso come Operatore Tecnico per gestire la disponibilità della squadra.", "warning")
        return redirect(url_for("login"))
    if user["role"] != "operator":
        flash("Area riservata esclusivamente agli Operatori Tecnici comunali.", "danger")
        return redirect(url_for("index"))

    team_id = user.get("team_id")
    if not team_id:
        flash("Il tuo account Operatore non è associato a nessuna squadra operativa.", "warning")
        return redirect(url_for("index"))

    team = db.get_team_by_id(team_id, get_db_path())
    if not team:
        flash("Squadra associata non trovata.", "danger")
        return redirect(url_for("index"))

    assigned_reports = db.get_reports_by_team(team_id, get_db_path())
    return render_template(
        "operator_availability.html",
        team=team,
        assigned_reports=assigned_reports,
    )


# ============================================================================
# ROUTE AUTENTICAZIONE E PROFILO UTENTE
# ============================================================================

@app.route("/login", methods=["GET", "POST"])
def login():
    """
    VISTA 6: Pagina di Login / Registrazione e Switch Rapido Ruolo Demo.
    """
    if request.method == "GET":
        return render_template("login.html", error=None)

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    user = db.get_user_by_username(username, get_db_path())
    if not user or not check_password_hash(user["password_hash"], password):
        return render_template("login.html", error="Credenziali non valide. Riprova o usa i pulsanti di Accesso Demo Rapido."), 401

    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["role"] = user["role"]
    flash(f"Benvenuto/a, {user['full_name']}! Accesso effettuato con ruolo '{user['role'].upper()}'.", "success")
    return redirect(url_for("index"))


@app.route("/register", methods=["POST"])
def register():
    """Registrazione nuovo profilo cittadino."""
    username = request.form.get("username", "").strip()
    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")

    if len(username) < 3 or len(full_name) < 4 or "@" not in email or len(password) < 6:
        return render_template(
            "login.html",
            error="Compila tutti i campi di registrazione (username min 3 car., password min 6 car., email valida).",
        ), 400

    if db.get_user_by_username(username, get_db_path()):
        return render_template("login.html", error="Username già registrato nel sistema."), 400

    try:
        new_user = db.create_user(username, full_name, email, password, role="citizen", db_path=get_db_path())
    except Exception:
        return render_template("login.html", error="L'indirizzo email o lo username risultano già associati a un account."), 400

    session["user_id"] = new_user["id"]
    session["username"] = new_user["username"]
    session["role"] = new_user["role"]
    flash(f"Account creato con successo! Benvenuto/a in CivicPulse Modena, {new_user['full_name']}.", "success")
    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    session.clear()
    flash("Disconnessione completata.", "info")
    return redirect(url_for("index"))


# ============================================================================
# SERVIZI RESTful API (/api/...) - JSON & CRUD COMPLETO
# ============================================================================

@app.route("/api/reports", methods=["GET"])
def api_get_reports():
    """
    GET /api/reports
    Restituisce la collezione di segnalazioni filtrata in formato JSON (usata da Mappa Leaflet, filtri AJAX e SPA React).
    """
    reports = db.query_reports(
        search=request.args.get("search", "").strip(),
        category=request.args.get("category", "").strip(),
        status=request.args.get("status", "").strip(),
        priority=request.args.get("priority", "").strip(),
        quartiere=request.args.get("quartiere", "").strip(),
        sort_by=request.args.get("sort_by", "newest").strip(),
        db_path=get_db_path(),
    )
    return jsonify({
        "status": "ok",
        "count": len(reports),
        "reports": reports,
    })


@app.route("/api/reports/<int:report_id>", methods=["GET"])
def api_get_report_detail(report_id: int):
    """GET /api/reports/<id> - Restituisce il dettaglio JSON di una singola segnalazione e i suoi commenti."""
    report = db.get_report_by_id(report_id, get_db_path())
    if not report:
        return jsonify({"status": "error", "message": "Segnalazione non trovata"}), 404
    return jsonify({"status": "ok", "report": report})


@app.route("/api/reports", methods=["POST"])
def api_create_report():
    """POST /api/reports - Crea una nuova segnalazione via JSON API (CRUD Create)."""
    payload = request.get_json(silent=True) or {}
    errors = validate_report_payload(payload, is_update=False)
    if errors:
        return jsonify({"status": "error", "errors": errors}), 400

    current_user = get_current_user()
    payload["author_id"] = payload.get("author_id") or (current_user["id"] if current_user else 3)
    if not payload.get("image_url"):
        payload["image_url"] = "/static/uploads/demo_buca_dief.svg"

    created = db.create_report(payload, get_db_path())
    broadcast_realtime_event(
        "report_created",
        f"Nuova Segnalazione API {created['code']}",
        f"{created['title']} ({created['quartiere']})",
        {"report_id": created["id"], "code": created["code"]},
    )
    return jsonify({"status": "ok", "report": created}), 201


@app.route("/api/reports/<int:report_id>", methods=["PUT"])
def api_update_report(report_id: int):
    """PUT /api/reports/<id> - Aggiorna una segnalazione esistente via JSON API (CRUD Update) con controllo RBAC."""
    existing = db.get_report_by_id(report_id, get_db_path())
    if not existing:
        return jsonify({"status": "error", "message": "Segnalazione non trovata"}), 404

    user = get_current_user()
    if not user:
        return jsonify({"status": "unauthorized", "message": "Autenticazione richiesta per modificare una segnalazione."}), 401

    if user["role"] not in ("operator", "admin") and user["id"] != existing.get("author_id"):
        return jsonify({
            "status": "forbidden",
            "message": "Operazione non consentita: solo l'autore della segnalazione, un Operatore o un Admin possono modificarla.",
        }), 403

    payload = request.get_json(silent=True) or {}
    merged = {**existing, **payload}

    if user["role"] == "citizen":
        status_changed = "status" in payload and payload.get("status") != existing["status"]
        team_changed = False
        if "assigned_team_id" in payload:
            raw_team = payload.get("assigned_team_id")
            try:
                req_team_id = int(raw_team) if raw_team is not None and str(raw_team).strip() != "" else None
            except (TypeError, ValueError):
                req_team_id = raw_team
            team_changed = req_team_id != existing.get("assigned_team_id")
        if status_changed or team_changed:
            return jsonify({
                "status": "forbidden",
                "message": "La modifica dello stato operativo o della squadra è riservata a Operatori Tecnici e Amministratori.",
            }), 403
        merged["status"] = existing["status"]
        merged["assigned_team_id"] = existing.get("assigned_team_id")
    else:
        if user["role"] != "admin" and "assigned_team_id" in payload:
            raw_req_team = payload.get("assigned_team_id")
            try:
                req_team_id = int(raw_req_team) if raw_req_team is not None and str(raw_req_team).strip() != "" else None
            except (TypeError, ValueError):
                req_team_id = raw_req_team
            if req_team_id != existing.get("assigned_team_id"):
                return jsonify({
                    "status": "forbidden",
                    "message": "La riassegnazione della squadra è riservata all'Amministratore (Admin).",
                }), 403

        raw_team = existing.get("assigned_team_id") if user["role"] != "admin" else merged.get("assigned_team_id")
        if raw_team is None or str(raw_team).strip() == "":
            target_team_id = None
        else:
            try:
                target_team_id = int(raw_team)
            except (TypeError, ValueError):
                return jsonify({"status": "error", "message": "Parametro assigned_team_id non valido."}), 400

        if target_team_id:
            target_team = db.get_team_by_id(target_team_id, get_db_path())
            if not target_team:
                return jsonify({"status": "error", "message": "Squadra non trovata"}), 404

            team_changed = target_team_id != existing.get("assigned_team_id")
            if team_changed and not target_team.get("is_available", True):
                busy = target_team.get("busy_report")
                msg = (
                    f"La squadra '{target_team['name']}' ha già un incarico in corso ({busy['code']}) ed è indisponibile fino al completamento."
                    if busy
                    else f"La squadra '{target_team['name']}' è AL MOMENTO INDISPONIBILE e non può ricevere nuovi incarichi."
                )
                return jsonify({"status": "error", "message": msg}), 400

            if merged.get("status") in ("in_lavorazione", "sospesa_meteo"):
                busy = target_team.get("busy_report")
                if busy and int(busy["id"]) != int(report_id):
                    return jsonify({
                        "status": "error",
                        "message": f"La squadra '{target_team['name']}' può gestire 1 solo incarico alla volta (sta già lavorando su {busy['code']}). Completa prima quello!",
                    }), 400
                if not target_team.get("manual_available", True) and existing.get("status") == "aperta":
                    return jsonify({
                        "status": "error",
                        "message": f"La squadra '{target_team['name']}' è contrassegnata come AL MOMENTO INDISPONIBILE.",
                    }), 400
        merged["assigned_team_id"] = target_team_id

    errors = validate_report_payload(merged, is_update=True)
    if errors:
        return jsonify({"status": "error", "errors": errors}), 400

    was_active = existing.get("status") in ("in_lavorazione", "sospesa_meteo")
    updated = db.update_report(report_id, merged, get_db_path())
    broadcast_realtime_event(
        "report_updated",
        f"Aggiornata {updated['code']}",
        f"Nuovo stato: {STATUSES[updated['status']]['label']}",
        {"report_id": updated["id"], "status": updated["status"]},
    )
    if was_active and updated["status"] in ("risolta", "chiusa") and updated.get("assigned_team_id"):
        refreshed_team = db.get_team_by_id(updated["assigned_team_id"], get_db_path())
        if refreshed_team and refreshed_team.get("is_available"):
            broadcast_realtime_event(
                "team_availability_changed",
                f"🟢 Squadra Libera: {refreshed_team['name']}",
                f"Lavoro su {updated['code']} completato! La squadra è tornata DISPONIBILE per nuovi incarichi.",
                {"team": refreshed_team},
            )
    return jsonify({"status": "ok", "report": updated})


@app.route("/api/reports/<int:report_id>/status", methods=["POST", "PATCH"])
def api_update_report_status(report_id: int):
    """
    POST /api/reports/<id>/status
    Endpoint rapido per aggiornare stato, priorità o squadra assegnata (usato dalla Kanban Board in React e dal pannello Operatore).
    RISERVATO A OPERATORI TECNICI E AMMINISTRATORI.
    """
    existing = db.get_report_by_id(report_id, get_db_path())
    if not existing:
        return jsonify({"status": "error", "message": "Segnalazione non trovata"}), 404

    user = get_current_user()
    if not user:
        if request.accept_mimetypes.best == "application/json" or request.is_json:
            return jsonify({"status": "unauthorized", "message": "Autenticazione richiesta. Effettua il login come Operatore o Admin."}), 401
        flash("Devi accedere come Operatore o Admin per modificare lo stato della pratica.", "warning")
        return redirect(url_for("login"))

    if user["role"] not in ("operator", "admin"):
        if request.accept_mimetypes.best == "application/json" or request.is_json:
            return jsonify({"status": "forbidden", "message": "Operazione non consentita: riservata a Operatori Tecnici e Amministratori."}), 403
        flash("Operazione riservata a Operatori Tecnici e Amministratori.", "danger")
        return redirect(url_for("report_detail", report_id=report_id))

    payload = request.get_json(silent=True) or request.form.to_dict()
    new_status = payload.get("status", existing["status"])
    new_priority = payload.get("priority", existing["priority"])
    new_team = payload.get("assigned_team_id", existing["assigned_team_id"])

    if new_status not in STATUSES:
        return jsonify({"status": "error", "message": "Stato non valido"}), 400
    if new_priority not in PRIORITIES:
        return jsonify({"status": "error", "message": "Priorità non valida"}), 400

    # Risolve e valida l'ID della squadra assegnata (cambio squadra riservato ad Admin)
    target_team_id = existing.get("assigned_team_id")
    if new_team is not None and str(new_team).strip() != "":
        try:
            parsed_team_id = int(new_team)
        except (TypeError, ValueError):
            parsed_team_id = existing.get("assigned_team_id")
        if user["role"] != "admin" and parsed_team_id != existing.get("assigned_team_id"):
            msg = "La riassegnazione della squadra è riservata all'Amministratore (Admin)."
            if request.accept_mimetypes.best == "application/json" or request.is_json:
                return jsonify({"status": "forbidden", "message": msg}), 403
            flash(msg, "danger")
            return redirect(url_for("report_detail", report_id=report_id))
        if user["role"] == "admin":
            target_team_id = parsed_team_id

    if target_team_id:
        target_team = db.get_team_by_id(target_team_id, get_db_path())
        if not target_team:
            return jsonify({"status": "error", "message": "Squadra non trovata"}), 404

        team_changed = target_team_id != existing.get("assigned_team_id")
        # Se si cambia squadra verso una indisponibile (manuale o impegnata) -> blocca
        if team_changed and not target_team.get("is_available", True):
            busy = target_team.get("busy_report")
            msg = (
                f"La squadra '{target_team['name']}' ha già un incarico in corso ({busy['code']}) "
                "ed è indisponibile fino al completamento."
                if busy
                else f"La squadra '{target_team['name']}' è AL MOMENTO INDISPONIBILE e non può ricevere nuovi incarichi."
            )
            if request.accept_mimetypes.best == "application/json" or request.is_json:
                return jsonify({"status": "error", "message": msg}), 400
            flash(msg, "danger")
            return redirect(url_for("report_detail", report_id=report_id))

        # Se la pratica viene avviata/sospesa su questa squadra, verifica che non abbia già un ALTRO lavoro attivo
        if new_status in ("in_lavorazione", "sospesa_meteo"):
            busy = target_team.get("busy_report")
            if busy and int(busy["id"]) != int(report_id):
                msg = (
                    f"La squadra '{target_team['name']}' può gestire 1 solo incarico alla volta "
                    f"(sta già lavorando su {busy['code']}). Completa prima quello!"
                )
                if request.accept_mimetypes.best == "application/json" or request.is_json:
                    return jsonify({"status": "error", "message": msg}), 400
                flash(msg, "danger")
                return redirect(url_for("report_detail", report_id=report_id))
            if not target_team.get("manual_available", True) and existing.get("status") == "aperta":
                msg = f"La squadra '{target_team['name']}' è contrassegnata come AL MOMENTO INDISPONIBILE."
                if request.accept_mimetypes.best == "application/json" or request.is_json:
                    return jsonify({"status": "error", "message": msg}), 400
                flash(msg, "danger")
                return redirect(url_for("report_detail", report_id=report_id))

    was_active = existing.get("status") in ("in_lavorazione", "sospesa_meteo")
    updated = db.update_report(
        report_id,
        {"status": new_status, "priority": new_priority, "assigned_team_id": target_team_id},
        get_db_path(),
    )
    broadcast_realtime_event(
        "status_changed",
        f"Cambio Stato {updated['code']}",
        f"La pratica {updated['code']} è passata a '{STATUSES[new_status]['label']}' (Priorità: {PRIORITIES[new_priority]['label']}).",
        {"report_id": report_id, "status": new_status, "priority": new_priority},
    )

    # Se un lavoro attivo viene completato/risolto, controlla se la squadra torna libera e notifica via SSE
    if was_active and new_status in ("risolta", "chiusa") and updated.get("assigned_team_id"):
        refreshed_team = db.get_team_by_id(updated["assigned_team_id"], get_db_path())
        if refreshed_team and refreshed_team.get("is_available"):
            broadcast_realtime_event(
                "team_availability_changed",
                f"🟢 Squadra Libera: {refreshed_team['name']}",
                f"Lavoro su {updated['code']} completato! La squadra è tornata DISPONIBILE per nuovi incarichi.",
                {"team": refreshed_team},
            )

    if request.accept_mimetypes.best == "application/json" or request.is_json:
        return jsonify({"status": "ok", "report": updated})

    flash(f"Stato operativo di {updated['code']} aggiornato a '{STATUSES[new_status]['label']}'.", "success")
    return redirect(url_for("report_detail", report_id=report_id))


@app.route("/api/reports/<int:report_id>", methods=["DELETE"])
def api_delete_report(report_id: int):
    """
    DELETE /api/reports/<id> - Elimina una segnalazione via REST API (CRUD Delete).
    RISERVATA TASSATIVAMENTE ALL'AMMINISTRATORE (ADMIN).
    """
    existing = db.get_report_by_id(report_id, get_db_path())
    if not existing:
        return jsonify({"status": "error", "message": "Segnalazione non trovata"}), 404

    user = get_current_user()
    if not user:
        return jsonify({
            "status": "unauthorized",
            "message": "Autenticazione richiesta. Effettua l'accesso come Amministratore (Admin) per eliminare pratiche."
        }), 401

    if user["role"] != "admin":
        return jsonify({
            "status": "forbidden",
            "message": "Operazione negata: solo gli utenti con ruolo ADMIN hanno i permessi di eliminazione."
        }), 403

    db.delete_report(report_id, get_db_path())
    broadcast_realtime_event(
        "report_deleted",
        f"Eliminata {existing['code']}",
        f"Segnalazione {existing['code']} rimossa via API dall'Amministratore.",
        {"report_id": report_id},
    )
    return jsonify({"status": "ok", "deleted_id": report_id})


@app.route("/api/reports/<int:report_id>/upvote", methods=["POST"])
def api_upvote_report(report_id: int):
    """POST /api/reports/<id>/upvote - Incrementa le conferme civiche (crowdsensing validation)."""
    user = get_current_user()
    new_count = db.toggle_upvote(report_id, user["id"] if user else None, get_db_path())
    if new_count is None:
        return jsonify({"status": "error", "message": "Segnalazione non trovata"}), 404

    return jsonify({"status": "ok", "report_id": report_id, "upvotes": new_count})


# ============================================================================
# API CRUD SUI COMMENTI E LOG OPERATIVI
# ============================================================================

@app.route("/api/reports/<int:report_id>/comments", methods=["POST"])
def api_add_comment(report_id: int):
    """CREATE Comment: Aggiunge un commento o aggiornamento tecnico (supporta sia Form HTML che Fetch JSON)."""
    report = db.get_report_by_id(report_id, get_db_path())
    if not report:
        return jsonify({"status": "error", "message": "Segnalazione non trovata"}), 404

    payload = request.get_json(silent=True) or request.form.to_dict()
    content = (payload.get("content") or "").strip()
    if len(content) < 3 or len(content) > 1000:
        if request.is_json:
            return jsonify({"status": "error", "message": "Il commento deve contenere tra 3 e 1000 caratteri."}), 400
        flash("Il commento deve contenere tra 3 e 1000 caratteri.", "danger")
        return redirect(url_for("report_detail", report_id=report_id))

    user = get_current_user()
    user_id = user["id"] if user else 3
    is_official = 1 if (user and user["role"] in ("operator", "admin") and payload.get("is_official_update")) else 0

    comment = db.add_comment(report_id, user_id, content, is_official, get_db_path())
    broadcast_realtime_event(
        "comment_added",
        f"Nuova Nota su {report['code']}",
        f"{comment['author_name']}: {content[:70]}...",
        {"report_id": report_id, "comment_id": comment["id"]},
    )

    if request.is_json:
        return jsonify({"status": "ok", "comment": comment}), 201

    flash("Nota aggiunta con successo alla timeline della segnalazione.", "success")
    return redirect(url_for("report_detail", report_id=report_id))


@app.route("/api/comments/<int:comment_id>", methods=["PUT", "POST"])
def api_edit_comment(comment_id: int):
    """UPDATE Comment: Modifica un commento esistente (riservata all'autore del commento o ad Admin)."""
    existing = db.get_comment_by_id(comment_id, get_db_path())
    if not existing:
        return jsonify({"status": "error", "message": "Commento non trovato"}), 404

    user = get_current_user()
    if not user:
        if request.is_json:
            return jsonify({"status": "unauthorized", "message": "Autenticazione richiesta."}), 401
        flash("Devi effettuare l'accesso per modificare questo commento.", "warning")
        return redirect(url_for("login"))

    comment_author_id = existing.get("user_id") or existing.get("author_id")
    if user["role"] != "admin" and user["id"] != comment_author_id:
        if request.is_json:
            return jsonify({"status": "forbidden", "message": "Non hai i permessi per modificare questo commento."}), 403
        flash("Puoi modificare esclusivamente i commenti inseriti dal tuo account.", "danger")
        return redirect(url_for("report_detail", report_id=existing["report_id"]))

    payload = request.get_json(silent=True) or request.form.to_dict()
    content = (payload.get("content") or "").strip()
    if len(content) < 3 or len(content) > 1000:
        if request.is_json:
            return jsonify({"status": "error", "message": "Il commento deve contenere tra 3 e 1000 caratteri."}), 400
        flash("Testo del commento non valido.", "danger")
        return redirect(url_for("report_detail", report_id=existing["report_id"]))

    updated = db.update_comment(comment_id, content, get_db_path())
    if request.is_json:
        return jsonify({"status": "ok", "comment": updated})

    flash("Commento aggiornato con successo.", "success")
    return redirect(url_for("report_detail", report_id=existing["report_id"]))


@app.route("/api/comments/<int:comment_id>/delete", methods=["POST", "DELETE"])
def api_remove_comment(comment_id: int):
    """DELETE Comment: Elimina un commento dalla timeline (riservata all'autore del commento o ad Admin)."""
    existing = db.get_comment_by_id(comment_id, get_db_path())
    if not existing:
        return jsonify({"status": "error", "message": "Commento non trovato"}), 404

    user = get_current_user()
    if not user:
        if request.is_json or request.method == "DELETE":
            return jsonify({"status": "unauthorized", "message": "Autenticazione richiesta."}), 401
        flash("Devi effettuare l'accesso per eliminare questo commento.", "warning")
        return redirect(url_for("login"))

    comment_author_id = existing.get("user_id") or existing.get("author_id")
    if user["role"] != "admin" and user["id"] != comment_author_id:
        if request.is_json or request.method == "DELETE":
            return jsonify({"status": "forbidden", "message": "Non hai i permessi per rimuovere questo commento."}), 403
        flash("Puoi eliminare solo i commenti pubblicati dal tuo account o devi essere Admin.", "danger")
        return redirect(url_for("report_detail", report_id=existing["report_id"]))

    report_id = existing["report_id"]
    db.delete_comment(comment_id, get_db_path())

    if request.is_json or request.method == "DELETE":
        return jsonify({"status": "ok", "deleted_id": comment_id})

    flash("Commento rimosso dalla segnalazione.", "info")
    return redirect(url_for("report_detail", report_id=report_id))


# ============================================================================
# ENDPOINT "SPORCARSI LE MANI": AI NLP TRIAGE, METEO, SSE REAL-TIME, EXPORT
# ============================================================================

@app.route("/api/ai/analyze", methods=["POST"])
def api_ai_analyze():
    """
    POST /api/ai/analyze
    Analizza in tempo reale titolo e descrizione digitati dall'utente nel form e restituisce
    categoria suggerita, punteggio di urgenza (0-100), priorità, SLA in ore, squadra e spiegazione AI.
    """
    payload = request.get_json(silent=True) or {}
    title = payload.get("title", "")
    description = payload.get("description", "")
    category = payload.get("category", "")
    result = analyze_report_text(title, description, category)
    return jsonify({"status": "ok", "analysis": result})


@app.route("/api/analytics", methods=["GET"])
def api_analytics():
    """GET /api/analytics - Restituisce i dati statistici per i grafici Chart.js e i KPI live."""
    return jsonify({
        "status": "ok",
        "analytics": db.get_dashboard_analytics(get_db_path()),
        "weather": fetch_modena_weather(),
        "recent_events": _recent_events[:10],
    })


@app.route("/api/weather", methods=["GET"])
def api_weather():
    """GET /api/weather - Condizioni meteo attuali a Modena e fattibilità cantieri esterni."""
    return jsonify({"status": "ok", "weather": fetch_modena_weather()})


# ============================================================================
# ENDPOINT GESTIONE SQUADRE (ADMIN), DISPONIBILITÀ (OPERATORE) & SMISTAMENTO
# ============================================================================

@app.route("/api/teams", methods=["GET"])
def api_get_teams():
    """GET /api/teams - Elenco squadre comunali con stato disponibilità e carico lavori."""
    return jsonify({
        "status": "ok",
        "teams": db.get_all_teams(get_db_path()),
    })


@app.route("/api/teams", methods=["POST"])
def api_create_team():
    """POST /api/teams - Registra una nuova squadra operativa comunale (Solo Admin)."""
    user = get_current_user()
    if not user:
        return jsonify({"status": "unauthorized", "message": "Autenticazione richiesta come Amministratore."}), 401
    if user["role"] != "admin":
        return jsonify({"status": "forbidden", "message": "Solo l'Amministratore può registrare nuove squadre."}), 403

    payload = request.get_json(silent=True) or request.form.to_dict()
    name = (payload.get("name") or "").strip()
    department = (payload.get("department") or "").strip()
    specialization = (payload.get("specialization") or "").strip()
    contact_email = (payload.get("contact_email") or "").strip()
    active_members_raw = payload.get("active_members", 4)

    if len(name) < 3:
        return jsonify({"status": "error", "message": "Il nome della squadra deve avere almeno 3 caratteri."}), 400
    if len(department) < 3:
        return jsonify({"status": "error", "message": "Specifica il settore/dipartimento della squadra."}), 400
    if len(specialization) < 5:
        return jsonify({"status": "error", "message": "Descrivi brevemente la specializzazione tecnica."}), 400
    if "@" not in contact_email or len(contact_email) < 5:
        return jsonify({"status": "error", "message": "Inserisci un indirizzo email di contatto valido."}), 400

    try:
        active_members = int(active_members_raw)
        if active_members < 1 or active_members > 100:
            raise ValueError()
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Il numero di tecnici deve essere compreso tra 1 e 100."}), 400

    try:
        new_team = db.create_team(
            name=name,
            department=department,
            specialization=specialization,
            contact_email=contact_email,
            active_members=active_members,
            db_path=get_db_path(),
        )
    except Exception:
        return jsonify({"status": "error", "message": "Esiste già una squadra registrata con questo nome."}), 400

    broadcast_realtime_event(
        "team_created",
        f"Nuova Squadra: {new_team['name']}",
        f"Registrata dal Responsabile Admin ({new_team['department']}, {new_team['active_members']} tecnici).",
        {"team": new_team},
    )
    return jsonify({"status": "ok", "team": new_team}), 201


@app.route("/api/teams/<int:team_id>/availability", methods=["POST"])
def api_update_team_availability(team_id: int):
    """
    POST /api/teams/<team_id>/availability
    Permette all'Operatore associato alla squadra di impostare Disponibile / Non Disponibile
    con eventuale motivazione e fascia oraria. Emette notifica SSE istantanea all'Admin.
    """
    user = get_current_user()
    if not user:
        return jsonify({"status": "unauthorized", "message": "Autenticazione richiesta come Operatore."}), 401
    if user["role"] != "operator" or user.get("team_id") != team_id:
        return jsonify({
            "status": "forbidden",
            "message": "Puoi modificare esclusivamente la disponibilità della tua squadra associata.",
        }), 403

    team = db.get_team_by_id(team_id, get_db_path())
    if not team:
        return jsonify({"status": "error", "message": "Squadra non trovata."}), 404

    payload = request.get_json(silent=True) or request.form.to_dict()
    raw_avail = payload.get("is_available")
    if isinstance(raw_avail, bool):
        is_avail = raw_avail
    elif isinstance(raw_avail, (int, float)):
        is_avail = bool(int(raw_avail))
    elif isinstance(raw_avail, str):
        is_avail = raw_avail.strip().lower() in ("1", "true", "yes", "si", "on")
    else:
        return jsonify({"status": "error", "message": "Parametro is_available non valido."}), 400

    reason = (payload.get("reason") or payload.get("unavailability_reason") or "").strip()
    until_time = (payload.get("until_time") or payload.get("unavailable_until") or "").strip()

    # Se la squadra ha ancora un incarico in corso, non può tornare disponibile finché non lo completa
    if is_avail and team.get("is_busy"):
        busy = team.get("busy_report") or {}
        return jsonify({
            "status": "team_busy",
            "message": (
                f"Impossibile impostare la disponibilità: hai ancora l'incarico {busy.get('code', '')} in corso. "
                "Segna prima il lavoro come completato!"
            ),
        }), 400

    updated_team = db.update_team_availability(
        team_id=team_id,
        is_available=is_avail,
        reason=reason,
        until_time=until_time,
        db_path=get_db_path(),
    )

    if is_avail:
        ev_title = f"🟢 Squadra Disponibile: {updated_team['name']}"
        ev_msg = f"L'operatore {user['full_name']} ha impostato la squadra come DISPONIBILE per nuovi interventi."
    else:
        details = f" Motivo: {updated_team['unavailability_reason']}." if updated_team["unavailability_reason"] else ""
        until_txt = f" Fino a: {updated_team['unavailable_until']}." if updated_team["unavailable_until"] else ""
        ev_title = f"🔴 Squadra Indisponibile: {updated_team['name']}"
        ev_msg = f"L'operatore {user['full_name']} ha segnato la squadra come AL MOMENTO INDISPONIBILE.{details}{until_txt}"

    broadcast_realtime_event(
        "team_availability_changed",
        ev_title,
        ev_msg,
        {"team": updated_team},
    )

    return jsonify({"status": "ok", "team": updated_team})


@app.route("/api/admin/assign-report", methods=["POST"])
def api_admin_assign_report():
    """
    POST /api/admin/assign-report
    Assegna un compito APERTO a una squadra DISPONIBILE tramite Drag & Drop dell'Admin
    e porta automaticamente la segnalazione nello stato 'in_lavorazione'.
    Finché questo incarico non è completato, la squadra risulta automaticamente indisponibile.
    """
    user = get_current_user()
    if not user:
        return jsonify({"status": "unauthorized", "message": "Autenticazione richiesta come Admin."}), 401
    if user["role"] != "admin":
        return jsonify({"status": "forbidden", "message": "Solo l'Amministratore può assegnare i compiti alle squadre."}), 403

    payload = request.get_json(silent=True) or request.form.to_dict()
    try:
        report_id = int(payload.get("report_id"))
        team_id = int(payload.get("team_id"))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Parametri report_id o team_id non validi."}), 400

    report = db.get_report_by_id(report_id, get_db_path())
    if not report:
        return jsonify({"status": "error", "message": "Segnalazione non trovata."}), 404

    team = db.get_team_by_id(team_id, get_db_path())
    if not team:
        return jsonify({"status": "error", "message": "Squadra non trovata."}), 404

    # Blocco rigoroso se la squadra è occupata su un incarico o è stata messa indisponibile
    if not team.get("is_available", True):
        if team.get("is_busy") and team.get("busy_report"):
            msg = (
                f"Assegnazione negata: '{team['name']}' sta già eseguendo {team['busy_report']['code']} "
                "ed è INDISPONIBILE fino a completamento lavoro."
            )
        else:
            msg = f"Assegnazione negata: '{team['name']}' è AL MOMENTO INDISPONIBILE."
        return jsonify({
            "status": "team_unavailable",
            "message": msg,
        }), 400

    updated_report = db.assign_report_to_team(
        report_id=report_id,
        team_id=team_id,
        new_status="in_lavorazione",
        db_path=get_db_path(),
    )

    broadcast_realtime_event(
        "report_assigned",
        f"📌 Assegnata {updated_report['code']} a {team['name']}",
        f"La pratica {updated_report['code']} è ora IN LAVORAZIONE. La squadra è occupata fino al completamento.",
        {"report": updated_report, "team_id": team_id},
    )

    return jsonify({
        "status": "ok",
        "report": updated_report,
        "teams": db.get_all_teams(get_db_path()),
    })


# Punti di riferimento geospaziali di Modena per Reverse Geocoding offline/fallback e mappatura quartieri
MODENA_LANDMARKS = [
    (44.6294, 10.9482, "Via Pietro Vivarelli 10 (Campus DIEF UNIMORE), Modena", "Crocetta - San Lazzaro - Modena Est"),
    (44.6318, 10.9395, "Via Vignolese 610 (Polo Universitario), Modena", "Buon Pastore - Sant'Agnese - San Damaso"),
    (44.6352, 10.9428, "Via del Pozzo 71 (Policlinico di Modena), Modena", "Buon Pastore - Sant'Agnese - San Damaso"),
    (44.6463, 10.9255, "Piazza Grande (Centro Storico UNESCO), Modena", "Centro Storico"),
    (44.6487, 10.9296, "Corso Canalgrande 88 (Giardini Ducali), Modena", "Centro Storico"),
    (44.6445, 10.9210, "Largo Porta Sant'Agostino, Modena", "Centro Storico"),
    (44.6475, 10.9218, "Via Emilia Centro, Modena", "Centro Storico"),
    (44.6548, 10.9301, "Piazza Dante Alighieri (Stazione FS Centrale), Modena", "Centro Storico - Crocetta"),
    (44.6585, 10.9350, "Via Nonantolana, Modena", "Centro Storico - Crocetta"),
    (44.6512, 10.9065, "Viale Autodromo 35 (Parco Enzo Ferrari), Modena", "San Faustino - Madonnina - Quattro Ville"),
    (44.6420, 10.9020, "Via Emilia Ovest (Zona Madonnina), Modena", "San Faustino - Madonnina - Quattro Ville"),
    (44.6360, 10.9110, "Via Giardini (Zona San Faustino), Modena", "San Faustino - Madonnina - Quattro Ville"),
    (44.6395, 10.9510, "Via Emilia Est, Modena", "Crocetta - San Lazzaro - Modena Est"),
    (44.6490, 10.9580, "Via Indipendenza (Modena Est), Modena", "Crocetta - San Lazzaro - Modena Est"),
    (44.6260, 10.9260, "Viale Amendola (Parco della Repubblica), Modena", "Buon Pastore - Sant'Agnese - San Damaso"),
]


def infer_modena_quartiere(lat: float, lon: float) -> str:
    """Determina la Circoscrizione/Quartiere di Modena più vicino alle coordinate (lat, lon)."""
    # Se siamo nel cuore del Centro Storico (entro i viali)
    if 44.6425 <= lat <= 44.6520 and 10.9180 <= lon <= 10.9330:
        return "Centro Storico"
    if lat > 44.6520 and 10.9200 <= lon <= 10.9420:
        return "Centro Storico - Crocetta"
    if lon < 10.9180:
        return "San Faustino - Madonnina - Quattro Ville"
    if lon >= 10.9430 or (lat >= 44.6380 and lon >= 10.9330):
        return "Crocetta - San Lazzaro - Modena Est"
    return "Buon Pastore - Sant'Agnese - San Damaso"


def reverse_geocode_modena(lat: float, lon: float) -> Dict[str, Any]:
    """
    Converte una coppia di coordinate GPS (lat, lon) nell'indirizzo stradale più vicino
    usando l'API OpenStreetMap Nominatim con fallback sul grafo locale di Modena.
    Blocca coordinate fuori dal territorio del Comune di Modena.
    """
    if not is_within_comune_di_modena(lat, lon):
        return {
            "outside_modena": True,
            "message": (
                f"Coordinate ({lat:.4f}, {lon:.4f}) fuori dal perimetro del Comune di Modena. "
                "È consentito inviare segnalazioni solo nel territorio comunale di Modena."
            ),
            "latitude": round(lat, 4),
            "longitude": round(lon, 4),
        }

    nearest = min(
        MODENA_LANDMARKS,
        key=lambda item: (item[0] - lat) ** 2 + (item[1] - lon) ** 2,
    )
    quartiere = infer_modena_quartiere(lat, lon)
    fallback_address = nearest[2]

    url = (
        f"https://nominatim.openstreetmap.org/reverse?format=jsonv2"
        f"&lat={lat:.6f}&lon={lon:.6f}&zoom=18&addressdetails=1&accept-language=it"
    )
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "CivicPulse-Modena-UNIMORE-TW/2.6 (Educational Project)"},
        )
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            addr = data.get("address", {})
            detected_comune = (
                addr.get("city")
                or addr.get("town")
                or addr.get("municipality")
                or addr.get("village")
                or "Modena"
            )
            # Se OpenStreetMap rileva che il punto cade in un comune limitrofo (es. Formigine, Nonantola, Campogalliano)
            if detected_comune.strip().lower() != "modena":
                return {
                    "outside_modena": True,
                    "detected_comune": detected_comune,
                    "message": (
                        f"Il punto selezionato ricade nel Comune di {detected_comune}. "
                        "Puoi inviare segnalazioni esclusivamente nel Comune di Modena!"
                    ),
                    "latitude": round(lat, 4),
                    "longitude": round(lon, 4),
                }

            road = (
                addr.get("road")
                or addr.get("pedestrian")
                or addr.get("cycleway")
                or addr.get("footway")
                or addr.get("square")
                or addr.get("Amenity")
                or addr.get("neighbourhood")
                or ""
            )
            house_num = addr.get("house_number", "")
            suburb = addr.get("suburb") or addr.get("quarter") or addr.get("city_district") or ""

            if road:
                street_part = f"{road} {house_num}".strip()
                zone_part = f" ({suburb})" if suburb and suburb.lower() not in road.lower() else ""
                resolved_address = f"{street_part}{zone_part}, Modena"
                return {
                    "outside_modena": False,
                    "address": resolved_address,
                    "quartiere": quartiere,
                    "latitude": round(lat, 4),
                    "longitude": round(lon, 4),
                    "source": "OpenStreetMap Nominatim",
                }
    except Exception:
        pass

    return {
        "outside_modena": False,
        "address": fallback_address,
        "quartiere": nearest[3] or quartiere,
        "latitude": round(lat, 4),
        "longitude": round(lon, 4),
        "source": "Geodatabase Locale Modena",
    }


@app.route("/api/geocode/reverse", methods=["GET"])
def api_reverse_geocode():
    """
    GET /api/geocode/reverse?lat=...&lon=...
    Restituisce l'indirizzo stradale più vicino e il quartiere di Modena corrispondente
    alle coordinate cliccate sulla mappa o rilevate dal GPS.
    Rifiuta con HTTP 400 i punti fuori dal Comune di Modena.
    """
    try:
        lat = float(request.args.get("lat", 44.6294))
        lon = float(request.args.get("lon", 10.9482))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Coordinate non valide"}), 400

    result = reverse_geocode_modena(lat, lon)
    if result.get("outside_modena"):
        return jsonify({
            "status": "outside_modena",
            "outside_modena": True,
            "message": result.get("message"),
            "location": result,
        }), 400

    return jsonify({"status": "ok", "outside_modena": False, "location": result})



@app.route("/api/stream")
def api_sse_stream():
    """
    GET /api/stream
    Implementazione del protocollo Server-Sent Events (SSE - Content-Type: text/event-stream)
    per inviare notifiche push in tempo reale dal backend Flask ai client browser connessi.
    """
    def event_generator():
        client_queue: queue.Queue = queue.Queue(maxsize=25)
        _sse_subscribers.append(client_queue)
        try:
            # Messaggio iniziale di handshake SSE
            hello = json.dumps({
                "type": "connected",
                "title": "Stream Real-Time Attivo",
                "message": "Connesso al canale Server-Sent Events di CivicPulse Modena",
                "timestamp": datetime.now().strftime("%H:%M:%S"),
            })
            yield f"data: {hello}\n\n"

            while True:
                try:
                    event_data = client_queue.get(timeout=20)
                    yield f"data: {json.dumps(event_data)}\n\n"
                except queue.Empty:
                    # Heartbeat keep-alive conforme alla specifica SSE
                    yield ": keep-alive\n\n"
        except GeneratorExit:
            pass
        finally:
            if client_queue in _sse_subscribers:
                _sse_subscribers.remove(client_queue)

    return Response(
        event_generator(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.route("/api/export/csv")
def api_export_csv():
    """Esporta l'intero registro delle segnalazioni in formato CSV (Open Data Comunale)."""
    reports = db.query_reports(db_path=get_db_path())
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow([
        "Codice", "Titolo", "Categoria", "Priorita", "Stato",
        "Urgenza_AI_0_100", "SLA_Stimato_Ore", "Quartiere", "Indirizzo",
        "Latitudine", "Longitudine", "Squadra_Assegnata", "Conferme_Cittadini", "Data_Creazione"
    ])
    for r in reports:
        writer.writerow([
            r["code"],
            r["title"],
            CATEGORIES.get(r["category"], {}).get("label", r["category"]),
            r["priority"],
            r["status"],
            r["ai_urgency_score"],
            r["ai_estimated_sla_hours"],
            r["quartiere"],
            r["address"],
            r["latitude"],
            r["longitude"],
            r.get("team_name") or "Non assegnata",
            r["upvotes"],
            r["created_at"],
        ])

    csv_bytes = output.getvalue().encode("utf-8-sig")
    return Response(
        csv_bytes,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=civicpulse_modena_open_data.csv"},
    )


@app.route("/api/export/json")
def api_export_json():
    """Esporta il dataset completo in formato JSON strutturato (Open Data API)."""
    reports = db.query_reports(db_path=get_db_path())
    payload = {
        "dataset": "CivicPulse Modena - Registro Segnalazioni Urbane",
        "exported_at": datetime.now().isoformat(),
        "total_records": len(reports),
        "records": reports,
    }
    return Response(
        json.dumps(payload, indent=2, ensure_ascii=False),
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=civicpulse_modena_open_data.json"},
    )


@app.route("/sw.js")
def service_worker():
    """Espone il Service Worker dalla root dell'applicazione per garantire lo scope PWA globale '/'."""
    return send_from_directory(os.path.join(BASE_DIR, "static"), "sw.js", mimetype="application/javascript")


# ============================================================================
# GESTIONE PERSONALIZZATA ERRORI HTTP (404 / 500)
# ============================================================================

@app.errorhandler(404)
def page_not_found(e):
    if request.path.startswith("/api/"):
        return jsonify({"status": "error", "message": "Risorsa API non trovata (404)"}), 404
    return render_template("base.html", error_404=True), 404


# Inizializza automaticamente il database all'avvio del modulo
db.init_db()

if __name__ == "__main__":
    import threading
    threading.Thread(target=fetch_modena_weather, daemon=True).start()
    # host="0.0.0.0" rende il server accessibile sia in locale (127.0.0.1:5000)
    # sia da altri dispositivi (smartphone/tablet/PC); use_reloader=False evita doppio processo e latenza file watching
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False, threaded=True)


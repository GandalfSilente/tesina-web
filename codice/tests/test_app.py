"""
test_app.py - Suite di Test Automatizzati per CivicPulse Modena
===============================================================
Verifica il funzionamento end-to-end di:
1. Viste Frontend SSR (Home, Dettaglio, Form, Dashboard, Kanban React, Login);
2. Operazioni CRUD complete sulle Segnalazioni (Create, Read, Update, Delete);
3. Operazioni CRUD complete sui Commenti/Log Operativi;
4. Modulo "Sporcarsi le Mani" AI/NLP Auto-Triage (/api/ai/analyze);
5. Servizi RESTful API (/api/reports, /api/analytics, /api/weather, /api/export/csv).
"""

import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app
import database as db


@pytest.fixture
def client():
    db_fd, temp_db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)

    app.config["TESTING"] = True
    app.config["DATABASE_PATH"] = temp_db_path
    db.init_db(db_path=temp_db_path, force_reset=True)

    with app.test_client() as test_client:
        yield test_client

    if os.path.exists(temp_db_path):
        os.remove(temp_db_path)


def test_frontend_views_load(client):
    """Verifica che tutte le 6 viste principali rispondano con HTTP 200 OK (con gestione RBAC)."""
    # 1. Rotte pubbliche accessibili a tutti
    for path in ["/", "/report/1", "/report/new", "/dashboard", "/kanban", "/login"]:
        res = client.get(path)
        assert res.status_code == 200, f"Fallito caricamento della route pubblica {path}"

    # 2. Rotta di modifica: senza login redirige a /login (302)
    res_unauth = client.get("/report/1/edit")
    assert res_unauth.status_code == 302

    # 3. Rotta di modifica: dopo login risponde 200 OK
    client.post("/login", data={"username": "admin", "password": "admin123"})
    res_auth = client.get("/report/1/edit")
    assert res_auth.status_code == 200


def test_api_reports_crud_lifecycle(client):
    """Verifica l'intero ciclo di vita CRUD (Create -> Read -> Update -> Delete) via API REST."""
    # 1. READ iniziale
    res_list = client.get("/api/reports")
    assert res_list.status_code == 200
    initial_count = res_list.get_json()["count"]
    assert initial_count >= 7

    # 2. CREATE nuova segnalazione
    new_payload = {
        "title": "Perdita importante acqua potabile in Via Emilia Est",
        "description": "Segnalo una perdita importante dalla tubatura principale con allagamento del marciapiede vicino alla fermata autobus.",
        "category": "idrico_allagamenti",
        "address": "Via Emilia Est 140, Modena",
        "quartiere": "Crocetta - San Lazzaro - Modena Est",
        "latitude": 44.6395,
        "longitude": 10.9510,
    }
    res_create = client.post("/api/reports", json=new_payload)
    assert res_create.status_code == 201
    created = res_create.get_json()["report"]
    report_id = created["id"]
    assert created["code"].startswith("CPM-2026-")
    assert created["ai_urgency_score"] >= 60  # Rileva "perdita importante" e "allagamento"

    # 3. UPDATE segnalazione con verifica RBAC
    # 3a. Utente non autenticato -> 401
    res_update_anon = client.put(f"/api/reports/{report_id}", json={"title": "Tentativo non autenticato"})
    assert res_update_anon.status_code == 401

    # 3b. Altro cittadino non autore -> 403
    client.post("/login", data={"username": "giulia_b", "password": "cittadino123"})
    res_update_other = client.put(f"/api/reports/{report_id}", json={"title": "Tentativo da altro cittadino"})
    assert res_update_other.status_code == 403

    # 3c. Autore cittadino (id=3): non può cambiare status (403), può modificare il titolo (200)
    client.post("/login", data={"username": "cittadino", "password": "cittadino123"})
    res_update_status_citizen = client.put(f"/api/reports/{report_id}", json={"status": "in_lavorazione"})
    assert res_update_status_citizen.status_code == 403

    res_update_citizen = client.put(
        f"/api/reports/{report_id}",
        json={"title": "Perdita acqua potabile Via Emilia Est (Segnalata da cittadino)"},
    )
    assert res_update_citizen.status_code == 200

    # 3c-bis. Operatore: non può riassegnare la squadra (riservato ad Admin -> 403)
    client.post("/login", data={"username": "operatore", "password": "operatore123"})
    assert client.put(f"/api/reports/{report_id}", json={"assigned_team_id": 6}).status_code == 403
    assert client.post(f"/api/reports/{report_id}/status", json={"assigned_team_id": 6}).status_code == 403

    # 3d. Admin può aggiornare stato, priorità e squadra assegnata (squadra 6 libera nel seed)
    client.post("/login", data={"username": "admin", "password": "admin123"})
    update_payload = {
        "title": "Perdita acqua potabile Via Emilia Est (Riparazione in corso)",
        "status": "in_lavorazione",
        "priority": "critica",
        "assigned_team_id": 6,
    }
    res_update = client.put(f"/api/reports/{report_id}", json=update_payload)
    assert res_update.status_code == 200
    updated = res_update.get_json()["report"]
    assert updated["status"] == "in_lavorazione"
    assert updated["priority"] == "critica"

    # 4. UPVOTE segnalazione
    res_up = client.post(f"/api/reports/{report_id}/upvote")
    assert res_up.status_code == 200
    assert res_up.get_json()["upvotes"] == 2

    # 5. SICUREZZA RBAC SU DELETE:
    # 5a. Tentativo di eliminazione da utente NON autenticato -> Bloccato con 401
    client.get("/logout")
    res_del_anon = client.delete(f"/api/reports/{report_id}")
    assert res_del_anon.status_code == 401

    # 5b. Tentativo di eliminazione da utente Cittadino (Davide Rossi) -> Bloccato con 403
    client.post("/login", data={"username": "cittadino", "password": "cittadino123"})
    res_del_citizen = client.delete(f"/api/reports/{report_id}")
    assert res_del_citizen.status_code == 403

    # 5c. Eliminazione consentita SOLO ad Amministratore (Admin) -> Successo 200
    client.post("/login", data={"username": "admin", "password": "admin123"})
    res_del_admin = client.delete(f"/api/reports/{report_id}")
    assert res_del_admin.status_code == 200
    res_404 = client.get(f"/api/reports/{report_id}")
    assert res_404.status_code == 404


def test_comments_crud_lifecycle(client):
    """Verifica Creazione, Modifica ed Eliminazione dei commenti su una segnalazione con RBAC."""
    # Effettua login come cittadino per creare il commento
    client.post("/login", data={"username": "cittadino", "password": "cittadino123"})

    # CREATE commento
    res_add = client.post(
        "/api/reports/1/comments",
        json={"content": "Posizionate transenne di sicurezza attorno alla buca ciclabile."},
    )
    assert res_add.status_code == 201
    comment = res_add.get_json()["comment"]
    c_id = comment["id"]

    # UPDATE commento dall'autore
    res_edit = client.put(
        f"/api/comments/{c_id}",
        json={"content": "Transenne posizionate e intervento di asfaltatura completato al 50%."},
    )
    assert res_edit.status_code == 200
    assert "50%" in res_edit.get_json()["comment"]["content"]

    # DELETE commento dall'autore o admin
    res_del = client.delete(f"/api/comments/{c_id}/delete")
    assert res_del.status_code == 200


def test_ai_triage_engine_endpoint(client):
    """Verifica il modulo 'Sporcarsi le Mani' di Auto-Triage AI/NLP (/api/ai/analyze)."""
    res = client.post(
        "/api/ai/analyze",
        json={
            "title": "Lampione spento con cavo scoperto e scintille vicino scuola",
            "description": "Palo della luce danneggiato con pericolo elettrico e scintille sul marciapiede davanti alla scuola.",
            "category": "illuminazione_energia",
        },
    )
    assert res.status_code == 200
    analysis = res.get_json()["analysis"]
    assert analysis["ai_suggested_category"] == "illuminazione_energia"
    assert analysis["ai_urgency_score"] >= 80
    assert analysis["suggested_priority"] == "critica"
    assert "Impianti Elettrici" in analysis["recommended_team"]


def test_analytics_weather_and_exports(client):
    """Verifica gli endpoint di Analytics, Meteo, Reverse Geocoding e Open Data Export (CSV/JSON)."""
    assert client.get("/api/analytics").status_code == 200
    assert client.get("/api/weather").status_code == 200

    geo_res = client.get("/api/geocode/reverse?lat=44.6294&lon=10.9482")
    assert geo_res.status_code == 200
    geo_data = geo_res.get_json()["location"]
    assert len(geo_data["address"]) >= 5
    assert geo_data["quartiere"] != ""

    # Verifica blocco Geofencing su comuni esterni (es. Carpi: Lat 44.7830, Lon 10.8850)
    geo_outside = client.get("/api/geocode/reverse?lat=44.7830&lon=10.8850")
    assert geo_outside.status_code == 400
    assert geo_outside.get_json()["outside_modena"] is True

    report_outside = client.post(
        "/api/reports",
        json={
            "title": "Segnalazione fuori dal Comune di Modena",
            "description": "Tentativo di invio di una segnalazione nel comune limitrofo di Carpi o Formigine.",
            "category": "strade_viabilita",
            "address": "Piazza dei Martiri, Carpi",
            "quartiere": "Centro Storico",
            "latitude": 44.7830,
            "longitude": 10.8850,
        },
    )
    assert report_outside.status_code == 400

    csv_res = client.get("/api/export/csv")
    assert csv_res.status_code == 200
    assert "text/csv" in csv_res.content_type

    json_res = client.get("/api/export/json")
    assert json_res.status_code == 200
    assert "application/json" in json_res.content_type


def test_admin_team_dispatch_and_operator_availability(client):
    """Verifica il flusso completo: Registrazione Squadre Admin, Disponibilità Operatore e Smistamento Drag & Drop."""
    # 1. Protezione RBAC su rotte e API (utente anonimo e cittadino bloccati)
    assert client.get("/admin/teams").status_code == 302
    assert client.get("/operator/availability").status_code == 302
    assert client.post("/api/teams", json={"name": "Test Team"}).status_code == 401

    client.post("/login", data={"username": "cittadino", "password": "cittadino123"})
    assert client.post("/api/teams", json={"name": "Test Team"}).status_code == 403
    assert client.post("/api/admin/assign-report", json={"report_id": 2, "team_id": 1}).status_code == 403

    # 2. Admin registra una nuova squadra e accede alla pagina di smistamento
    client.post("/login", data={"username": "admin", "password": "admin123"})
    assert client.get("/admin/teams").status_code == 200

    res_team = client.post(
        "/api/teams",
        json={
            "name": "Squadra Interventi Rapidi Ciclabili",
            "department": "Mobilità Sostenibile",
            "specialization": "Riparazione cordoli e tracciatura ciclabili",
            "contact_email": "ciclabili@comune.modena.demo.it",
            "active_members": 5,
        },
    )
    assert res_team.status_code == 201
    created_team = res_team.get_json()["team"]
    assert created_team["is_available"] is True

    # 3. Operatore (associato alla squadra 1, che nel seed ha CPM-2026-001 in lavorazione)
    client.post("/login", data={"username": "operatore", "password": "operatore123"})
    assert client.get("/operator/availability").status_code == 200
    assert client.get("/admin/teams").status_code == 302  # Non può aprire vista Admin

    # Operatore non può modificare una squadra altrui
    res_other = client.post(
        f"/api/teams/{created_team['id']}/availability",
        json={"is_available": False, "reason": "Test"},
    )
    assert res_other.status_code == 403

    # Finché CPM-2026-001 è in corso, la squadra 1 è occupata:
    # non può tornare disponibile manualmente né ricevere un secondo incarico dall'Admin
    res_busy_avail = client.post("/api/teams/1/availability", json={"is_available": True})
    assert res_busy_avail.status_code == 400
    assert res_busy_avail.get_json()["status"] == "team_busy"

    client.post("/login", data={"username": "admin", "password": "admin123"})
    res_blocked_busy = client.post("/api/admin/assign-report", json={"report_id": 2, "team_id": 1})
    assert res_blocked_busy.status_code == 400
    assert res_blocked_busy.get_json()["status"] == "team_unavailable"

    # L'Operatore completa il lavoro attivo (report_id=1 -> 'risolta'): la squadra 1 torna libera!
    client.post("/login", data={"username": "operatore", "password": "operatore123"})
    res_complete = client.post(
        "/api/reports/1/status",
        json={"status": "risolta"},
    )
    assert res_complete.status_code == 200

    # Ora da libera può impostarsi manualmente NON DISPONIBILE ("Mezzo in officina")
    res_unavail = client.post(
        "/api/teams/1/availability",
        json={
            "is_available": False,
            "reason": "Mezzo in officina",
            "until_time": "18:30",
        },
    )
    assert res_unavail.status_code == 200
    assert res_unavail.get_json()["team"]["is_available"] is False

    # 4. Admin NON può assegnare alla squadra 1 perché messa manualmente indisponibile
    client.post("/login", data={"username": "admin", "password": "admin123"})
    res_blocked = client.post("/api/admin/assign-report", json={"report_id": 2, "team_id": 1})
    assert res_blocked.status_code == 400
    assert res_blocked.get_json()["status"] == "team_unavailable"

    # 5. Operatore ripristina la disponibilità -> Admin assegna report 2 -> passa in lavorazione
    client.post("/login", data={"username": "operatore", "password": "operatore123"})
    res_avail = client.post("/api/teams/1/availability", json={"is_available": True})
    assert res_avail.status_code == 200
    assert res_avail.get_json()["team"]["is_available"] is True

    client.post("/login", data={"username": "admin", "password": "admin123"})
    res_assign = client.post("/api/admin/assign-report", json={"report_id": 2, "team_id": 1})
    assert res_assign.status_code == 200
    assigned_report = res_assign.get_json()["report"]
    assert assigned_report["assigned_team_id"] == 1
    assert assigned_report["status"] == "in_lavorazione"

    # 6. Verifica blocco automatico 1-incarico-alla-volta: la squadra 1 è ora di nuovo INDISPONIBILE per report 7!
    res_second_job = client.post("/api/admin/assign-report", json={"report_id": 7, "team_id": 1})
    assert res_second_job.status_code == 400
    assert res_second_job.get_json()["status"] == "team_unavailable"





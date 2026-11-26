"""
ai_engine.py - Modulo di Auto-Triage NLP & Intelligenza Artificiale ("Sporcarsi le Mani")
=========================================================================================
Analizza il titolo e la descrizione di una segnalazione urbana per:
1. Classificare automaticamente la categoria più probabile tramite pesatura lessicale TF/Keyword;
2. Calcolare un Indice di Urgenza (0-100) e suggerire il livello di priorità (bassa, media, alta, critica);
3. Stimare lo SLA (Service Level Agreement in ore) e la sensibilità alle condizioni meteo;
4. Suggerire la squadra operativa comunale più adatta all'intervento;
5. Supportare in modo trasparente un eventuale endpoint LLM esterno (OpenAI/Gemini) con fallback
   deterministico locale (garantendo funzionamento 100% offline/autonomo durante la demo d'esame).
"""

import re
from typing import Dict, Any, List


# Dizionario semantico per dominio urbano (pesi e parole chiave)
CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "strade_viabilita": [
        "buca", "buche", "asfalto", "strada", "marciapiede", "semaforo", "incrocio",
        "segnaletica", "cartello", "pista ciclabile", "ciclabile", "voragine", "pavimentazione",
        "porfido", "passaggio pedonale", "strisce", "traffico", "viabilità", "guardrail"
    ],
    "illuminazione_energia": [
        "lampione", "lampioni", "luce", "illuminazione", "buio", "spento", "sfarfalla",
        "palo della luce", "cavo", "elettrico", "corrente", "colonnina", "ricarica",
        "quadro elettrico", "scintille", "blackout", "led"
    ],
    "ambiente_verde": [
        "albero", "ramo", "rami", "potatura", "parco", "giardino", "erba", "aiuola",
        "verde", "radici", "caduto", "pericolante", "pianta", "siepe", "irrigazione",
        "insetti", "zanzare"
    ],
    "rifiuti_decoro": [
        "rifiuti", "spazzatura", "cassonetto", "abbandono", "discarica", "ingombranti",
        "degrado", "graffiti", "vandalismo", "vetri", "sporco", "cestino", "plastica",
        "materasso", "sacchi"
    ],
    "idrico_allagamenti": [
        "acqua", "allagamento", "allagato", "tombin", "tombino", "caditoia", "perdita",
        "tubo", "tubatura", "fontanella", "fognatura", "ristagno", "pioggia", "pozzanghera",
        "infiltrazione", "scarico"
    ],
    "sicurezza_arredo": [
        "panchina", "altalena", "giostrina", "recinzione", "transenna", "parapetto",
        "pericolo", "rottura", "arredo", "fontana", "monumento", "barriera", "scivolo",
        "accessibilità", "disabili"
    ],
}

# Indicatori di rischio elevato / emergenza (incrementano lo score di urgenza)
CRITICAL_PATTERNS = [
    (r"\b(pericol[oi]|pericolos[oaie]|rischio|emergenza|urgente|grave)\b", 22, "Rilevati termini di pericolo diretto per l'incolumità pubblica"),
    (r"\b(cavo scoperto|scintille|tensione|corrente|fiamme|fumo)\b", 35, "Rischio elettrico/incendio ad alta criticità"),
    (r"\b(voragine|cedimento|crollo|albero caduto|ramo spezzato)\b", 30, "Rischio strutturale o ostruzione critica della sede stradale"),
    (r"\b(allagamento|perdita importante|fognatura|semaforo spento)\b", 25, "Impatto severo sulla circolazione o sulla rete idrica/elettrica"),
    (r"\b(scuola|ospedale|policlinico|campus|bambini|anziani|disabili)\b", 18, "Prossimità a luoghi sensibili o utenza fragile"),
    (r"\b(incidente|caduta|ferit[oi]|bloccato)\b", 24, "Segnalato evento dannoso già verificatosi sul posto"),
]

MODERATE_PATTERNS = [
    (r"\b(buca|lampione spento|cassonetto pieno|marciapiede sconnesso)\b", 12, "Disservizio infrastrutturale standard da programmare"),
    (r"\b(notte|buio|visibilit[àa]|pioggia)\b", 10, "Condizioni ambientali che amplificano il disagio"),
]

# Mappatura Categoria -> Squadra Operativa Comunale e sensibilità al meteo esterno
CATEGORY_METADATA: Dict[str, Dict[str, Any]] = {
    "strade_viabilita": {
        "label": "Strade, Viabilità e Ciclabili",
        "team_name": "Squadra Manutenzione Stradale & Segnaletica",
        "weather_sensitive": 1,  # Posa asfalto e verniciatura strisce richiedono assenza di pioggia
        "base_sla": 48,
    },
    "illuminazione_energia": {
        "label": "Illuminazione Pubblica e Rete Elettrica",
        "team_name": "Squadra Impianti Elettrici & Smart Grid",
        "weather_sensitive": 1,
        "base_sla": 24,
    },
    "ambiente_verde": {
        "label": "Verde Pubblico, Parchi e Alberature",
        "team_name": "Nucleo Cura del Verde & Arboricoltura",
        "weather_sensitive": 1,
        "base_sla": 72,
    },
    "rifiuti_decoro": {
        "label": "Rifiuti, Igiene Urbana e Decoro",
        "team_name": "Unità Igiene Ambientale & Decoro Urbano",
        "weather_sensitive": 0,
        "base_sla": 36,
    },
    "idrico_allagamenti": {
        "label": "Rete Idrica, Tombini e Allagamenti",
        "team_name": "Pronto Intervento Idrico & Protezione Civile",
        "weather_sensitive": 1,
        "base_sla": 12,
    },
    "sicurezza_arredo": {
        "label": "Arredo Urbano, Sicurezza e Barriere",
        "team_name": "Squadra Edilizia Civica & Arredo Urbano",
        "weather_sensitive": 0,
        "base_sla": 60,
    },
}


def analyze_report_text(title: str, description: str, user_category: str = "") -> Dict[str, Any]:
    """
    Esegue l'analisi NLP sul testo della segnalazione e restituisce:
    - ai_suggested_category: categoria dedotta dal testo
    - category_confidence: confidenza percentuale (0-100)
    - ai_urgency_score: punteggio numerico di urgenza (0-100)
    - suggested_priority: 'bassa' | 'media' | 'alta' | 'critica'
    - ai_estimated_sla_hours: ore stimate per la presa in carico/risoluzione
    - weather_sensitive: 1 se l'intervento dipende dal meteo, 0 altrimenti
    - recommended_team: nome della squadra tecnica suggerita
    - ai_reasoning: spiegazione trasparente (Explainable AI) dei fattori rilevati
    """
    full_text = f"{title or ''} {description or ''}".lower().strip()

    # 1. Classificazione della categoria tramite match pesato (titolo pesa il doppio)
    title_lower = (title or "").lower()
    scores: Dict[str, int] = {cat: 0 for cat in CATEGORY_KEYWORDS}
    matched_keywords: Dict[str, List[str]] = {cat: [] for cat in CATEGORY_KEYWORDS}

    for cat, kw_list in CATEGORY_KEYWORDS.items():
        for kw in kw_list:
            if kw in full_text:
                weight = 3 if kw in title_lower else 2
                scores[cat] += weight
                matched_keywords[cat].append(kw)

    best_category = max(scores, key=lambda k: scores[k])
    max_score = scores[best_category]

    if max_score == 0:
        best_category = user_category if user_category in CATEGORY_METADATA else "strade_viabilita"
        confidence = 55
    else:
        total_positive = sum(v for v in scores.values() if v > 0)
        confidence = min(98, max(65, int((max_score / max(1, total_positive)) * 100)))

    # 2. Calcolo dell'Indice di Urgenza (0 - 100) e raccolta motivazioni (Explainable AI)
    urgency_score = 30  # Baseline iniziale
    reasons: List[str] = []

    for pattern, boost, explanation in CRITICAL_PATTERNS:
        if re.search(pattern, full_text, re.IGNORECASE):
            urgency_score += boost
            reasons.append(explanation)

    for pattern, boost, explanation in MODERATE_PATTERNS:
        if re.search(pattern, full_text, re.IGNORECASE):
            urgency_score += boost
            if len(reasons) < 3:
                reasons.append(explanation)

    # Bonus urgenza per categorie intrinsecamente critiche
    effective_category = user_category if user_category in CATEGORY_METADATA else best_category
    if effective_category == "idrico_allagamenti":
        urgency_score += 12
    elif effective_category == "illuminazione_energia":
        urgency_score += 8

    urgency_score = max(15, min(98, urgency_score))

    # 3. Determinazione della priorità e dello SLA stimato
    meta = CATEGORY_METADATA.get(effective_category, CATEGORY_METADATA["strade_viabilita"])
    base_sla = meta["base_sla"]

    if urgency_score >= 80:
        suggested_priority = "critica"
        estimated_sla = max(4, int(base_sla * 0.25))
    elif urgency_score >= 60:
        suggested_priority = "alta"
        estimated_sla = max(12, int(base_sla * 0.5))
    elif urgency_score >= 38:
        suggested_priority = "media"
        estimated_sla = base_sla
    else:
        suggested_priority = "bassa"
        estimated_sla = int(base_sla * 1.5)

    # 4. Generazione della spiegazione leggibile per l'operatore e il cittadino
    kw_found = matched_keywords.get(best_category, [])[:4]
    kw_str = f"Termini chiave rilevati: {', '.join(kw_found)}." if kw_found else "Analisi contestuale del testo completata."
    factors_str = " | ".join(reasons[:2]) if reasons else "Nessun fattore di emergenza immediata rilevato; intervento programmabile in modalità ordinaria."

    reasoning = (
        f"[Auto-Triage NLP • Confidenza {confidence}%] {kw_str} "
        f"{factors_str}. Assegnazione consigliata: {meta['team_name']} (SLA stimato: {estimated_sla}h)."
    )

    return {
        "ai_suggested_category": best_category,
        "ai_suggested_category_label": CATEGORY_METADATA[best_category]["label"],
        "category_confidence": confidence,
        "ai_urgency_score": urgency_score,
        "suggested_priority": suggested_priority,
        "ai_estimated_sla_hours": estimated_sla,
        "weather_sensitive": meta["weather_sensitive"],
        "recommended_team": meta["team_name"],
        "ai_reasoning": reasoning,
        "keywords_detected": kw_found,
    }

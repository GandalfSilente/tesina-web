/**
 * form_validation.js - Validazione Live DOM, Co-Pilota AI/NLP e Selettore GPS su Mappa
 * Corso di Intelligenza Artificiale e Tecnologie Web (AA 2026-2027) - UNIMORE
 */

document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("report-form");
    if (!form) return;

    const titleInput = document.getElementById("title");
    const descInput = document.getElementById("description");
    const categorySelect = document.getElementById("category");
    const prioritySelect = document.getElementById("priority");
    const addressInput = document.getElementById("address");
    const quartiereSelect = document.getElementById("quartiere");
    const latInput = document.getElementById("latitude");
    const lonInput = document.getElementById("longitude");

    const titleCounter = document.getElementById("title-counter");
    const descCounter = document.getElementById("desc-counter");
    const titleFeedback = document.getElementById("title-feedback");
    const descFeedback = document.getElementById("desc-feedback");
    const addressFeedback = document.getElementById("address-feedback");

    let lastAiResult = null;
    let debounceTimer = null;

    // 1. Contatori caratteri e validazione live su evento 'input'
    function updateCountersAndValidate() {
        const tLen = titleInput.value.trim().length;
        const dLen = descInput.value.trim().length;
        if (titleCounter) titleCounter.textContent = tLen;
        if (descCounter) descCounter.textContent = dLen;

        if (tLen > 0 && tLen < 8) {
            titleFeedback.textContent = "Inserisci almeno 8 caratteri per il titolo.";
            titleInput.classList.add("is-invalid");
        } else {
            titleFeedback.textContent = "";
            titleInput.classList.remove("is-invalid");
        }

        if (dLen > 0 && dLen < 20) {
            descFeedback.textContent = "Aggiungi qualche dettaglio in più (minimo 20 caratteri).";
            descInput.classList.add("is-invalid");
        } else {
            descFeedback.textContent = "";
            descInput.classList.remove("is-invalid");
        }

        // Avvia l'analisi AI/NLP con debounce di 350ms quando c'è testo sufficiente
        if (tLen >= 5 || dLen >= 10) {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(runAiAnalysis, 350);
        }
    }

    titleInput.addEventListener("input", updateCountersAndValidate);
    descInput.addEventListener("input", updateCountersAndValidate);
    categorySelect.addEventListener("change", runAiAnalysis);

    // 2. Chiamata asincrona all'endpoint REST /api/ai/analyze ("Sporcarsi le Mani")
    async function runAiAnalysis() {
        try {
            const response = await fetch("/api/ai/analyze", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    title: titleInput.value,
                    description: descInput.value,
                    category: categorySelect.value
                })
            });
            const data = await response.json();
            if (response.ok && data.status === "ok") {
                lastAiResult = data.analysis;
                renderAiPanel(lastAiResult);
            }
        } catch (err) {
            console.warn("Analisi AI live non disponibile:", err);
        }
    }

    function renderAiPanel(ai) {
        const scoreEl = document.getElementById("ai-live-score");
        const barEl = document.getElementById("ai-live-bar");
        const catEl = document.getElementById("ai-live-category");
        const slaEl = document.getElementById("ai-live-sla");
        const teamEl = document.getElementById("ai-live-team");
        const reasonEl = document.getElementById("ai-live-reasoning");

        if (scoreEl) scoreEl.textContent = `${ai.ai_urgency_score} / 100 (${ai.suggested_priority.toUpperCase()})`;
        if (barEl) {
            barEl.style.width = `${ai.ai_urgency_score}%`;
            barEl.style.backgroundColor =
                ai.ai_urgency_score >= 80 ? "#ef4444" :
                ai.ai_urgency_score >= 60 ? "#f97316" : "#38bdf8";
        }
        if (catEl) catEl.textContent = ai.ai_suggested_category_label;
        if (slaEl) slaEl.textContent = `${ai.ai_estimated_sla_hours} ore`;
        if (teamEl) teamEl.textContent = ai.recommended_team;
        if (reasonEl) reasonEl.textContent = ai.ai_reasoning;
    }

    const btnRunAi = document.getElementById("btn-run-ai");
    if (btnRunAi) {
        btnRunAi.addEventListener("click", runAiAnalysis);
    }

    const btnApplyAi = document.getElementById("btn-apply-ai");
    if (btnApplyAi) {
        btnApplyAi.addEventListener("click", () => {
            if (!lastAiResult) {
                runAiAnalysis();
                return;
            }
            categorySelect.value = lastAiResult.ai_suggested_category;
            prioritySelect.value = lastAiResult.suggested_priority;
            btnApplyAi.textContent = "✓ Parametri AI Applicati al Modulo!";
            setTimeout(() => {
                btnApplyAi.textContent = "Applica Categoria e Priorità Suggerite dall'AI";
            }, 2200);
        });
    }

    // Limiti geografici del Comune di Modena (esclude comuni limitrofi)
    const MODENA_LAT_MIN = 44.5850;
    const MODENA_LAT_MAX = 44.7150;
    const MODENA_LON_MIN = 10.8350;
    const MODENA_LON_MAX = 11.0150;
    const MODENA_BOUNDS = [
        [MODENA_LAT_MIN, MODENA_LON_MIN],
        [MODENA_LAT_MAX, MODENA_LON_MAX]
    ];

    function isInsideModenaBounds(lat, lon) {
        return (
            !isNaN(lat) && !isNaN(lon) &&
            lat >= MODENA_LAT_MIN && lat <= MODENA_LAT_MAX &&
            lon >= MODENA_LON_MIN && lon <= MODENA_LON_MAX
        );
    }

    // 3. Validazione completa sul Submit del Form (Previene invio se non valido o fuori Modena)
    form.addEventListener("submit", (event) => {
        let valid = true;

        if (titleInput.value.trim().length < 8) {
            titleFeedback.textContent = "Il titolo è obbligatorio e deve avere almeno 8 caratteri.";
            titleInput.classList.add("is-invalid");
            valid = false;
        }
        if (descInput.value.trim().length < 20) {
            descFeedback.textContent = "La descrizione è obbligatoria e deve avere almeno 20 caratteri.";
            descInput.classList.add("is-invalid");
            valid = false;
        }
        if (addressInput.value.trim().length < 5) {
            addressFeedback.textContent = "Inserisci un indirizzo valido (almeno 5 caratteri).";
            addressInput.classList.add("is-invalid");
            valid = false;
        } else {
            addressFeedback.textContent = "";
            addressInput.classList.remove("is-invalid");
        }

        const subLat = parseFloat(latInput.value);
        const subLon = parseFloat(lonInput.value);
        if (!isInsideModenaBounds(subLat, subLon)) {
            showGeoStatus(
                "⚠️ Coordinate fuori dal Comune di Modena! Puoi inviare segnalazioni solo nel territorio comunale di Modena.",
                true
            );
            latInput.classList.add("is-invalid");
            lonInput.classList.add("is-invalid");
            valid = false;
        } else {
            latInput.classList.remove("is-invalid");
            lonInput.classList.remove("is-invalid");
        }

        if (!valid) {
            event.preventDefault();
        }
    });

    // 4. Mappa Interattiva Leaflet bloccata sul Comune di Modena + Reverse Geocoding + HTML5 Geolocation
    const pickerEl = document.getElementById("picker-map");
    const geoStatusEl = document.getElementById("geo-auto-status");

    function showGeoStatus(text, isWarning = false) {
        if (!geoStatusEl) return;
        geoStatusEl.classList.remove("d-none", "text-success", "text-danger");
        geoStatusEl.classList.add(isWarning ? "text-danger" : "text-success");
        geoStatusEl.textContent = text;
    }

    if (pickerEl && window.L) {
        const rawInitLat = parseFloat(latInput.value) || 44.6294;
        const rawInitLon = parseFloat(lonInput.value) || 10.9482;
        const initLat = isInsideModenaBounds(rawInitLat, rawInitLon) ? rawInitLat : 44.6294;
        const initLon = isInsideModenaBounds(rawInitLat, rawInitLon) ? rawInitLon : 10.9482;

        let lastValidLatLng = [initLat, initLon];

        const map = L.map("picker-map", {
            maxBounds: MODENA_BOUNDS,
            maxBoundsViscosity: 1.0,
            minZoom: 12,
            maxZoom: 19
        }).setView([initLat, initLon], 13);

        L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
            minZoom: 12,
            maxZoom: 19,
            attribution: "&copy; OpenStreetMap"
        }).addTo(map);

        // Rettangolo tratteggiato che evidenzia i confini operativi del Comune di Modena
        L.rectangle(MODENA_BOUNDS, {
            color: "#2563eb",
            weight: 2,
            opacity: 0.55,
            fill: false,
            dashArray: "6, 6",
            interactive: false
        }).addTo(map);

        const marker = L.marker([initLat, initLon], { draggable: true }).addTo(map);

        function openSafeMarkerPopup(heading, detail) {
            const wrap = document.createElement("div");
            const strongEl = document.createElement("strong");
            strongEl.textContent = heading;
            wrap.appendChild(strongEl);
            wrap.appendChild(document.createElement("br"));
            wrap.appendChild(document.createTextNode(detail));
            marker.bindPopup(wrap).openPopup();
        }

        async function setCoordsAndResolveAddress(lat, lon, customAddress = null, customQuartiere = null, originLabel = "Mappa") {
            const numLat = Number(lat);
            const numLon = Number(lon);

            // Controllo immediato lato client: se fuori dal perimetro di Modena, riporta il marker all'ultimo punto valido
            if (!isInsideModenaBounds(numLat, numLon)) {
                marker.setLatLng(lastValidLatLng);
                map.panTo(lastValidLatLng);
                showGeoStatus(
                    "⚠️ Punto fuori dal Comune di Modena! Seleziona una zona all'interno del territorio comunale di Modena.",
                    true
                );
                return;
            }

            const fixedLat = numLat.toFixed(4);
            const fixedLon = numLon.toFixed(4);
            latInput.value = fixedLat;
            lonInput.value = fixedLon;
            latInput.classList.remove("is-invalid");
            lonInput.classList.remove("is-invalid");
            marker.setLatLng([fixedLat, fixedLon]);
            map.panTo([fixedLat, fixedLon]);

            // Se abbiamo già un indirizzo esplicito da un pulsante preset di Modena, lo impostiamo subito
            if (customAddress) {
                lastValidLatLng = [Number(fixedLat), Number(fixedLon)];
                addressInput.value = customAddress;
                addressInput.classList.remove("is-invalid");
                if (addressFeedback) addressFeedback.textContent = "";
                if (customQuartiere) quartiereSelect.value = customQuartiere;
                openSafeMarkerPopup("Indirizzo selezionato (Comune di Modena):", customAddress);
                showGeoStatus(`✓ Indirizzo impostato automaticamente (${originLabel}): ${customAddress}`);
                return;
            }

            // Altrimenti interroga il backend /api/geocode/reverse per verificare il Comune e ottenere la via più vicina
            showGeoStatus("⏳ Verifica territorio Comune di Modena e ricerca via più vicina...");
            try {
                const res = await fetch(`/api/geocode/reverse?lat=${fixedLat}&lon=${fixedLon}`);
                const data = await res.json();

                // Se il punto ricade in un altro Comune limitrofo (es. Formigine, Nonantola, Campogalliano)
                if (data.outside_modena || res.status === 400) {
                    const prevLat = lastValidLatLng[0].toFixed(4);
                    const prevLon = lastValidLatLng[1].toFixed(4);
                    latInput.value = prevLat;
                    lonInput.value = prevLon;
                    marker.setLatLng(lastValidLatLng);
                    map.panTo(lastValidLatLng);
                    openSafeMarkerPopup("⚠️ Fuori dal Comune di Modena", data.message || "Seleziona un punto nel Comune di Modena.");
                    showGeoStatus(`⚠️ ${data.message || "Il punto selezionato non appartiene al Comune di Modena."}`, true);
                    return;
                }

                if (res.ok && data.status === "ok" && data.location) {
                    const loc = data.location;
                    lastValidLatLng = [Number(fixedLat), Number(fixedLon)];
                    addressInput.value = loc.address;
                    addressInput.classList.remove("is-invalid");
                    if (addressFeedback) addressFeedback.textContent = "";

                    if (loc.quartiere) {
                        quartiereSelect.value = loc.quartiere;
                    }
                    openSafeMarkerPopup("📍 Via più vicina rilevata:", loc.address);
                    showGeoStatus(`✓ Indirizzo compilato automaticamente da ${originLabel}: ${loc.address}`);
                }
            } catch (err) {
                console.warn("Reverse geocoding non riuscito:", err);
                lastValidLatLng = [Number(fixedLat), Number(fixedLon)];
                const fallbackAddr = `Punto su mappa Modena (Lat ${fixedLat}, Lon ${fixedLon})`;
                if (!addressInput.value.trim()) {
                    addressInput.value = fallbackAddr;
                }
                showGeoStatus(`✓ Coordinate nel Comune di Modena aggiornate (${fixedLat}, ${fixedLon})`);
            }
        }

        // Click sulla mappa -> verifica che sia nel Comune di Modena e compila l'indirizzo più vicino
        map.on("click", (e) => {
            setCoordsAndResolveAddress(e.latlng.lat, e.latlng.lng, null, null, "punto selezionato sulla mappa");
        });

        // Trascinamento del marker -> verifica che sia nel Comune di Modena e compila l'indirizzo più vicino
        marker.on("dragend", () => {
            const pos = marker.getLatLng();
            setCoordsAndResolveAddress(pos.lat, pos.lng, null, null, "trascinamento marker");
        });

        // Pulsanti preset rapidi (Campus DIEF, Piazza Grande, Parco Ferrari)
        document.querySelectorAll(".preset-loc").forEach((btn) => {
            btn.addEventListener("click", () => {
                setCoordsAndResolveAddress(btn.dataset.lat, btn.dataset.lon, btn.dataset.addr, btn.dataset.q, "luogo rapido");
            });
        });

        // Funzione condivisa per entrambi i pulsanti "Usa Posizione Attuale" (nel form e sopra la mappa)
        function triggerCurrentPosition() {
            const allGpsBtns = [
                document.getElementById("btn-use-gps"),
                document.getElementById("btn-use-current-pos-form")
            ].filter(Boolean);

            allGpsBtns.forEach(b => { b.disabled = true; });
            showGeoStatus("📡 Rilevamento della tua posizione attuale (GPS / Rete) nel Comune di Modena...");

            const applyPosition = (lat, lon, label) => {
                // Verifica se le coordinate rilevate sono dentro il Comune di Modena, altrimenti usa Campus DIEF Modena
                const inComuneModena = isInsideModenaBounds(lat, lon);
                const finalLat = inComuneModena ? lat : 44.6294;
                const finalLon = inComuneModena ? lon : 10.9482;
                const finalLabel = inComuneModena ? label : "Posizione Attuale (ricentrata su Modena - Campus DIEF)";

                setCoordsAndResolveAddress(finalLat, finalLon, null, null, finalLabel);
                allGpsBtns.forEach(b => {
                    b.disabled = false;
                    b.innerHTML = '<i class="fa-solid fa-check me-1"></i>Posizione e Via Impostate!';
                });
            };

            if (!navigator.geolocation) {
                applyPosition(44.6294, 10.9482, "Posizione Attuale");
                return;
            }

            navigator.geolocation.getCurrentPosition(
                (pos) => {
                    applyPosition(pos.coords.latitude, pos.coords.longitude, "Posizione GPS Attuale");
                },
                () => {
                    applyPosition(44.6294, 10.9482, "Posizione Attuale Rilevata");
                },
                { enableHighAccuracy: true, timeout: 4000 }
            );
        }

        const gpsBtnMap = document.getElementById("btn-use-gps");
        const gpsBtnForm = document.getElementById("btn-use-current-pos-form");
        if (gpsBtnMap) gpsBtnMap.addEventListener("click", () => triggerCurrentPosition());
        if (gpsBtnForm) gpsBtnForm.addEventListener("click", () => triggerCurrentPosition());
    }

    // Inizializza contatori all'apertura (utile in modalità Modifica)
    updateCountersAndValidate();
});


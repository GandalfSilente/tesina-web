/**
 * explore.js - Mappa Interattiva OpenStreetMap/Leaflet e Sincronizzazione Catalogo
 * Corso di Intelligenza Artificiale e Tecnologie Web (AA 2026-2027) - UNIMORE
 */

document.addEventListener("DOMContentLoaded", () => {
    const mapContainer = document.getElementById("modena-map");
    const dataScript = document.getElementById("initial-reports-data");
    if (!mapContainer || !window.L) return;

    const MODENA_CENTER = [44.6463, 10.9255];
    const MODENA_BOUNDS = [
        [44.5850, 10.8350], // Sud-Ovest Comune di Modena
        [44.7150, 11.0150]  // Nord-Est Comune di Modena
    ];

    const map = L.map("modena-map", {
        maxBounds: MODENA_BOUNDS,
        maxBoundsViscosity: 1.0,
        minZoom: 12,
        maxZoom: 19
    }).setView(MODENA_CENTER, 13);

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        minZoom: 12,
        maxZoom: 19,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).addTo(map);

    // Perimetro visivo del territorio comunale di Modena
    L.rectangle(MODENA_BOUNDS, {
        color: "#2563eb",
        weight: 2,
        opacity: 0.45,
        fill: false,
        dashArray: "6, 6",
        interactive: false
    }).addTo(map);

    let reports = [];
    if (dataScript) {
        try {
            reports = JSON.parse(dataScript.textContent);
        } catch (err) {
            console.error("Errore parsing JSON segnalazioni:", err);
        }
    }

    const PRIORITY_COLOR_MAP = {
        critica: "#dc2626",
        alta: "#f97316",
        media: "#0284c7",
        bassa: "#64748b"
    };

    const markersById = {};
    const bounds = [];

    reports.forEach((r) => {
        if (!r.latitude || !r.longitude) return;
        const color = PRIORITY_COLOR_MAP[r.priority] || "#2563eb";

        const circleMarker = L.circleMarker([r.latitude, r.longitude], {
            radius: r.priority === "critica" ? 11 : 9,
            fillColor: color,
            color: "#ffffff",
            weight: 2.5,
            opacity: 1,
            fillOpacity: 0.9
        }).addTo(map);

        // Costruzione sicura del contenuto popup
        const popupWrap = document.createElement("div");
        popupWrap.style.minWidth = "210px";

        const codeBadge = document.createElement("div");
        codeBadge.className = "fw-bold text-primary small mb-1";
        codeBadge.textContent = `${r.code} • Urgenza AI ${r.ai_urgency_score}/100`;

        const titleEl = document.createElement("div");
        titleEl.className = "fw-bold mb-1";
        titleEl.textContent = r.title;

        const addrEl = document.createElement("div");
        addrEl.className = "small text-muted mb-2";
        addrEl.textContent = r.address;

        const linkEl = document.createElement("a");
        linkEl.href = `/report/${r.id}`;
        linkEl.className = "btn btn-sm btn-primary text-white w-100";
        linkEl.textContent = "Apri Scheda Intervento";

        popupWrap.appendChild(codeBadge);
        popupWrap.appendChild(titleEl);
        popupWrap.appendChild(addrEl);
        popupWrap.appendChild(linkEl);

        circleMarker.bindPopup(popupWrap);
        markersById[r.id] = circleMarker;
        bounds.push([r.latitude, r.longitude]);
    });

    if (bounds.length > 1) {
        map.fitBounds(bounds, { padding: [35, 35], maxZoom: 15 });
    }

    // Pulsante "Centra su Modena"
    const resetBtn = document.getElementById("btn-reset-map");
    if (resetBtn) {
        resetBtn.addEventListener("click", () => {
            if (bounds.length > 1) {
                map.fitBounds(bounds, { padding: [35, 35], maxZoom: 15 });
            } else {
                map.setView(MODENA_CENTER, 13);
            }
        });
    }

    // Pulsanti mirino sulle singole card per centrare il marker corrispondente
    document.querySelectorAll(".btn-focus-map").forEach((btn) => {
        btn.addEventListener("click", () => {
            const lat = parseFloat(btn.dataset.lat);
            const lon = parseFloat(btn.dataset.lon);
            const id = btn.dataset.id;
            if (!isNaN(lat) && !isNaN(lon)) {
                mapContainer.scrollIntoView({ behavior: "smooth", block: "center" });
                map.flyTo([lat, lon], 16, { duration: 0.8 });
                if (markersById[id]) {
                    setTimeout(() => markersById[id].openPopup(), 450);
                }
            }
        });
    });
});

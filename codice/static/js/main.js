/**
 * main.js - Modulo Globale Client-Side (SSE Real-Time, Upvote AJAX & PWA Service Worker)
 * Corso di Intelligenza Artificiale e Tecnologie Web (AA 2026-2027) - UNIMORE
 */

document.addEventListener("DOMContentLoaded", () => {
    initServerSentEvents();
    initUpvoteButtons();
    initUiActions();
    registerServiceWorker();
});

/**
 * Azioni UI globali disaccoppiate (Principio dei Tre Layer, zero handler inline HTML)
 */
function initUiActions() {
    document.addEventListener("submit", (e) => {
        const form = e.target.closest(".js-confirm-form");
        if (!form) return;
        const msg = form.dataset.confirm;
        if (msg && !window.confirm(msg)) {
            e.preventDefault();
        }
    });

    document.addEventListener("click", (e) => {
        const toggleBtn = e.target.closest(".js-toggle-comment-edit");
        if (toggleBtn && toggleBtn.dataset.target) {
            const box = document.getElementById(toggleBtn.dataset.target);
            if (box) box.classList.toggle("d-none");
        }
    });

    const printBtn = document.getElementById("btn-print-dashboard");
    if (printBtn) {
        printBtn.addEventListener("click", () => window.print());
    }
}

/**
 * 1. Connessione Real-Time tramite Server-Sent Events (EventSource /api/stream)
 */
function initServerSentEvents() {
    if (!("EventSource" in window)) return;

    const pill = document.getElementById("sse-status-pill");
    const source = new EventSource("/api/stream");

    // Chiudi subito la connessione SSE al cambio pagina per non saturare i 6 socket HTTP del browser
    const closeStream = () => {
        try { source.close(); } catch (_) {}
    };
    window.addEventListener("pagehide", closeStream);
    window.addEventListener("beforeunload", closeStream);

    source.onopen = () => {
        if (pill) {
            pill.style.opacity = "1";
            pill.title = "Connessione Real-Time Server-Sent Events attiva";
        }
    };

    source.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            if (data.type === "connected") return;

            // Notifica eventuali moduli nella pagina corrente senza aprire un secondo EventSource
            window.dispatchEvent(new CustomEvent("civicpulse:sse", { detail: data }));

            // Mostra notifica Toast Real-Time in basso a destra
            showRealtimeToast(data.title, data.message, data.timestamp);

            // Se siamo sulla Home Page (#modena-map) e arriva una segnalazione (es. da smartphone/altro PC), aggiorna automaticamente la pagina e la mappa
            if (
                document.getElementById("modena-map") &&
                ["report_created", "report_updated", "report_deleted", "status_changed"].includes(data.type)
            ) {
                setTimeout(() => {
                    window.location.reload();
                }, 1200);
            }

            // Se siamo sulla Control Room (dashboard), aggiorna in diretta il feed eventi
            const liveFeed = document.getElementById("live-sse-feed");
            if (liveFeed) {
                const placeholder = document.getElementById("sse-empty-placeholder");
                if (placeholder) placeholder.remove();

                const li = document.createElement("li");
                li.className = "list-group-item px-0 py-2 bg-info bg-opacity-10";

                const headerDiv = document.createElement("div");
                headerDiv.className = "d-flex justify-content-between";

                const strongEl = document.createElement("strong");
                strongEl.className = "text-primary";
                strongEl.textContent = data.title;

                const timeSpan = document.createElement("span");
                timeSpan.className = "text-muted";
                timeSpan.textContent = data.timestamp;

                headerDiv.appendChild(strongEl);
                headerDiv.appendChild(timeSpan);

                const msgDiv = document.createElement("div");
                msgDiv.className = "text-secondary";
                msgDiv.textContent = data.message;

                li.appendChild(headerDiv);
                li.appendChild(msgDiv);
                liveFeed.prepend(li);
            }
        } catch (err) {
            console.warn("Evento SSE non valido:", err);
        }
    };

    source.onerror = () => {
        if (pill) {
            pill.style.opacity = "0.65";
        }
    };
}

/**
 * Crea in modo sicuro (usando textContent contro XSS) un Toast Bootstrap per gli eventi SSE
 */
function showRealtimeToast(title, message, timestamp) {
    const container = document.getElementById("realtime-toast-container");
    if (!container) return;

    const toastEl = document.createElement("div");
    toastEl.className = "toast show border-0 shadow-lg";
    toastEl.setAttribute("role", "status");
    toastEl.setAttribute("aria-live", "polite");

    const header = document.createElement("div");
    header.className = "toast-header bg-dark text-white";

    const icon = document.createElement("i");
    icon.className = "fa-solid fa-tower-broadcast text-info me-2";

    const strong = document.createElement("strong");
    strong.className = "me-auto";
    strong.textContent = title;

    const small = document.createElement("small");
    small.className = "text-secondary ms-2";
    small.textContent = timestamp || "ora";

    const closeBtn = document.createElement("button");
    closeBtn.type = "button";
    closeBtn.className = "btn-close btn-close-white ms-2";
    closeBtn.setAttribute("aria-label", "Chiudi");
    closeBtn.addEventListener("click", () => toastEl.remove());

    header.appendChild(icon);
    header.appendChild(strong);
    header.appendChild(small);
    header.appendChild(closeBtn);

    const body = document.createElement("div");
    body.className = "toast-body small bg-white text-dark";
    body.textContent = message;

    toastEl.appendChild(header);
    toastEl.appendChild(body);
    container.appendChild(toastEl);

    setTimeout(() => {
        if (toastEl.parentNode) toastEl.remove();
    }, 6500);
}

/**
 * 2. Gestione asincrona dei pulsanti "Conferma Segnalazione" (POST /api/reports/<id>/upvote)
 */
function initUpvoteButtons() {
    document.addEventListener("click", async (e) => {
        const btn = e.target.closest(".btn-upvote");
        if (!btn) return;

        const reportId = btn.dataset.reportId;
        if (!reportId || btn.disabled) return;

        btn.disabled = true;
        try {
            const response = await fetch(`/api/reports/${reportId}/upvote`, {
                method: "POST",
                headers: { "Accept": "application/json" }
            });
            const data = await response.json();
            if (response.ok && data.status === "ok") {
                const countSpan = btn.querySelector(".upvote-count");
                if (countSpan) countSpan.textContent = data.upvotes;
                btn.classList.remove("btn-outline-primary");
                btn.classList.add("btn-success");
            } else {
                btn.disabled = false;
            }
        } catch (err) {
            console.error("Errore durante l'upvote:", err);
            btn.disabled = false;
        }
    });
}

/**
 * 3. Registrazione Service Worker per Progressive Web App (PWA)
 */
function registerServiceWorker() {
    if ("serviceWorker" in navigator) {
        navigator.serviceWorker.register("/sw.js").catch(() => {
            // Silenzioso in ambienti di test non HTTPS/localhost
        });
    }
}

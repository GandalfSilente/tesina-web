/**
 * dashboard.js - Rendering Grafici Analitici con Chart.js per la Control Room
 * Corso di Intelligenza Artificiale e Tecnologie Web (AA 2026-2027) - UNIMORE
 */

document.addEventListener("DOMContentLoaded", () => {
    const jsonScript = document.getElementById("dashboard-analytics-json");
    if (!jsonScript || !window.Chart) return;

    let analytics = null;
    try {
        analytics = JSON.parse(jsonScript.textContent);
    } catch (err) {
        console.error("Errore lettura dati analitici:", err);
        return;
    }

    const CATEGORY_LABELS = {
        strade_viabilita: "Strade & Ciclabili",
        illuminazione_energia: "Illuminazione & Rete",
        ambiente_verde: "Verde & Parchi",
        rifiuti_decoro: "Rifiuti & Decoro",
        idrico_allagamenti: "Rischio Idrico",
        sicurezza_arredo: "Arredo & Accessibilità"
    };

    const STATUS_LABELS = {
        aperta: "Aperta",
        in_lavorazione: "In Lavorazione",
        sospesa_meteo: "Sospesa Meteo",
        risolta: "Risolta",
        chiusa: "Chiusa"
    };

    // 1. Grafico a barre orizzontali: Segnalazioni per Categoria
    const catCtx = document.getElementById("chartCategories");
    if (catCtx && analytics.by_category) {
        new Chart(catCtx, {
            type: "bar",
            data: {
                labels: analytics.by_category.map(item => CATEGORY_LABELS[item.category] || item.category),
                datasets: [{
                    label: "Numero di Segnalazioni",
                    data: analytics.by_category.map(item => item.count),
                    backgroundColor: ["#2563eb", "#f59e0b", "#0284c7", "#10b981", "#8b5cf6", "#6366f1"],
                    borderRadius: 8
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    y: { beginAtZero: true, ticks: { precision: 0 } }
                }
            }
        });
    }

    // 2. Grafico Doughnut: Ripartizione Stato Operativo
    const statusCtx = document.getElementById("chartStatus");
    if (statusCtx && analytics.by_status) {
        new Chart(statusCtx, {
            type: "doughnut",
            data: {
                labels: analytics.by_status.map(item => STATUS_LABELS[item.status] || item.status),
                datasets: [{
                    data: analytics.by_status.map(item => item.count),
                    backgroundColor: ["#f59e0b", "#2563eb", "#6366f1", "#10b981", "#64748b"],
                    borderWidth: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: "bottom", labels: { boxWidth: 12 } }
                }
            }
        });
    }

    // 3. Grafico Pie/Polar: Ripartizione Priorità
    const prioCtx = document.getElementById("chartPriority");
    if (prioCtx && analytics.by_priority) {
        const prioColorMap = {
            critica: "#dc2626",
            alta: "#f97316",
            media: "#0284c7",
            bassa: "#64748b"
        };
        new Chart(prioCtx, {
            type: "pie",
            data: {
                labels: analytics.by_priority.map(item => item.priority.toUpperCase()),
                datasets: [{
                    data: analytics.by_priority.map(item => item.count),
                    backgroundColor: analytics.by_priority.map(item => prioColorMap[item.priority] || "#2563eb"),
                    borderWidth: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: "bottom", labels: { boxWidth: 12 } }
                }
            }
        });
    }
});

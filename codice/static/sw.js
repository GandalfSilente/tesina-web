/**
 * sw.js - Service Worker per Progressive Web App (PWA) & Caching Resiliente ("Sporcarsi le Mani")
 * Strategia ottimizzata per prestazioni:
 * - Static-First (Stale-While-Revalidate) per file locali /static/ (CSS, JS, SVG)
 * - Bypass diretto per rotte /api/, streaming SSE e risorse esterne
 */

const CACHE_NAME = "civicpulse-modena-v3.0";
const STATIC_ASSETS = [
    "/static/css/style.css",
    "/static/js/main.js",
    "/static/js/explore.js",
    "/static/js/form_validation.js",
    "/static/js/dashboard.js",
    "/static/manifest.json"
];

self.addEventListener("install", (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS)).catch(() => {})
    );
    self.skipWaiting();
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys().then((keys) =>
            Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
        )
    );
    self.clients.claim();
});

self.addEventListener("fetch", (event) => {
    const req = event.request;
    const url = new URL(req.url);

    // Non intercettare richieste non-GET, API dinamiche, stream SSE o origini esterne (CDN / mappe)
    if (
        req.method !== "GET" ||
        url.origin !== self.location.origin ||
        url.pathname.startsWith("/api/")
    ) {
        return;
    }

    // Per asset statici (/static/...), rispondi subito dalla cache e aggiorna in background
    if (url.pathname.startsWith("/static/")) {
        event.respondWith(
            caches.match(req).then((cached) => {
                const fetchPromise = fetch(req)
                    .then((networkRes) => {
                        if (networkRes && networkRes.ok) {
                            const clone = networkRes.clone();
                            caches.open(CACHE_NAME).then((cache) => cache.put(req, clone));
                        }
                        return networkRes;
                    })
                    .catch(() => cached);
                return cached || fetchPromise;
            })
        );
        return;
    }
});

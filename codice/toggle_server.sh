#!/usr/bin/env bash
# ============================================================================
# PULSANTE ON/OFF SERVER TESINA WEB (CivicPulse Modena)
# - Se il server è SPENTO (OFF) -> Lo ACCENDE (ON), crea il tunnel HTTPS
#   stabile Cloudflare (HTTP/2 su TCP 443, nessuna rotazione del link),
#   rigenera il PDF con i QR Code e apre il browser
# - Se il server è ACCESO (ON)  -> Lo SPEGNE (OFF) e chiude il tunnel
# ============================================================================

CODE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$CODE_DIR")"
PYTHON_BIN="$CODE_DIR/.venv/bin/python"
APP_FILE="$CODE_DIR/app.py"
QR_SCRIPT="$CODE_DIR/generate_qr_pdf.py"
CLOUDFLARED_BIN="$CODE_DIR/cloudflared"
URL="http://127.0.0.1:5000"
LAN_IP=$(hostname -I | awk '{print $1}')
LAN_URL="http://${LAN_IP:-127.0.0.1}:5000"
LOG_FILE="/tmp/civicpulse_tesina_web.log"
TUNNEL_LOG="/tmp/civicpulse_tunnel.log"
LINK_FILE="$ROOT_DIR/LINK_ALTRI_DISPOSITIVI.txt"
PDF_QR_FILE="$ROOT_DIR/LINK_E_QRCODE_DISPOSITIVI.pdf"

# Controlla se c'è già il server attivo sulla porta 5000
SERVER_PIDS=$(lsof -t -i:5000 2>/dev/null || pgrep -f "[T]esina WEB.*app\.py" 2>/dev/null)

if [ -n "$SERVER_PIDS" ]; then
    # --- IL SERVER È ATTIVO -> LO SPENGO (OFF) ---
    kill $SERVER_PIDS 2>/dev/null || true
    pkill -f "[c]loudflared tunnel" 2>/dev/null || true
    pkill -f "[n]okey@localhost.run" 2>/dev/null || true
    sleep 0.5
    REMAINING=$(lsof -t -i:5000 2>/dev/null)
    if [ -n "$REMAINING" ]; then
        kill -9 $REMAINING 2>/dev/null || true
    fi
    notify-send -i system-shutdown "🔴 Server Tesina WEB: SPENTO (OFF)" "Server e tunnel per altri dispositivi arrestati."
    echo "Server Tesina WEB spento (OFF)."
else
    # --- IL SERVER È SPENTO -> LO ACCENDO (ON) E APRO IL BROWSER ---
    pkill -f "[c]loudflared tunnel" 2>/dev/null || true
    pkill -f "[n]okey@localhost.run" 2>/dev/null || true

    cd "$CODE_DIR" || exit 1
    setsid -f "$PYTHON_BIN" "$APP_FILE" >"$LOG_FILE" 2>&1 < /dev/null

    # Attende che il server risponda sulla porta 5000
    for _ in {1..24}; do
        if ss -tulpn 2>/dev/null | grep -q ":5000 "; then
            break
        fi
        sleep 0.25
    done

    # Avvia il tunnel HTTPS stabile Cloudflare via HTTP/2 (non ruota l'URL né cade dopo 5 min)
    rm -f "$TUNNEL_LOG"
    if [ -x "$CLOUDFLARED_BIN" ]; then
        setsid -f "$CLOUDFLARED_BIN" tunnel --url "$URL" --protocol http2 --no-autoupdate >"$TUNNEL_LOG" 2>&1 < /dev/null
    else
        setsid -f ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=30 -R 80:127.0.0.1:5000 nokey@localhost.run >"$TUNNEL_LOG" 2>&1 < /dev/null
    fi

    xdg-open "$URL" >/dev/null 2>&1 &

    # Attende fino a 10 secondi affinché Cloudflare generi l'URL e registri la connessione
    PUBLIC_URL=""
    for _ in {1..40}; do
        PUBLIC_URL=$(grep -oE 'https://[a-zA-Z0-9.-]+\.(trycloudflare\.com|lhr\.life)' "$TUNNEL_LOG" 2>/dev/null | head -n 1)
        if [ -n "$PUBLIC_URL" ]; then
            if grep -q "Registered tunnel connection" "$TUNNEL_LOG" 2>/dev/null || grep -q "lhr.life" "$TUNNEL_LOG" 2>/dev/null; then
                break
            fi
        fi
        sleep 0.25
    done

    cat << EOF > "$LINK_FILE"
================================================================================
🌐 LINK PER APRIRE LA TESINA SU MAC, TELEFONO O TABLET (ANCHE SU RETI DIVERSE)
================================================================================

1) Link HTTPS Pubblico Stabile (funziona anche su EmiliaRomagnaWiFi, eduroam o 4G/5G):
👉 ${PUBLIC_URL:-In generazione...}

2) Link Rete Locale (solo su Wi-Fi domestico / Hotspot privato):
👉 $LAN_URL

3) Link su questo PC Linux:
👉 $URL

📄 Trovi tutti i link con i rispettivi QR Code pronti da inquadrare nel file:
   LINK_E_QRCODE_DISPOSITIVI.pdf
================================================================================
EOF

    # Rigenera automaticamente il PDF con i QR Code aggiornati
    "$PYTHON_BIN" "$QR_SCRIPT" "${PUBLIC_URL:-$LAN_URL}" "$LAN_URL" "$URL" "$PDF_QR_FILE" >/dev/null 2>&1 || true

    if [ -n "$PUBLIC_URL" ]; then
        notify-send -i system-shutdown "🟢 Server Tesina WEB: ACCESO (ON)" "Link stabile per Telefono/Mac: $PUBLIC_URL (QR Code aggiornati in PDF)"
    else
        notify-send -i system-shutdown "🟢 Server Tesina WEB: ACCESO (ON)" "PC: $URL | Wi-Fi: $LAN_URL"
    fi
fi

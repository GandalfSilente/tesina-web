#!/usr/bin/env bash
# Script di avvio rapido per CivicPulse Modena (Tesina Tecnologie Web UNIMORE)
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

if [ ! -d ".venv" ]; then
    echo "Configurazione ambiente virtuale Python (.venv)..."
    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt
fi

echo "=================================================================="
echo " Avvio di CivicPulse Modena su http://127.0.0.1:5000"
echo " Premi CTRL+C per arrestare il server."
echo "=================================================================="
exec .venv/bin/python app.py

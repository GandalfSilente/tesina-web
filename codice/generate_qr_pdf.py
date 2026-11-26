#!/usr/bin/env python3
"""
Genera il documento PDF 'LINK_E_QRCODE_DISPOSITIVI.pdf' nella cartella principale
della Tesina WEB.
Ogni pagina presenta uno dei casi di accesso (1: HTTPS Pubblico, 2: Rete Locale Wi-Fi/Hotspot,
3: Accesso Locale PC + Rotte Dirette) con il link cliccabile in evidenza e sotto il
rispettivo QR Code ad alta risoluzione pronto da inquadrare.
"""

import os
import sys
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.graphics.shapes import Drawing, Rect
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics import renderPDF


def draw_qr_code(c: canvas.Canvas, url: str, x: float, y: float, size: float) -> None:
    """Disegna un QR Code vettoriale centrato in un riquadro bianco con bordo."""
    # Riquadro esterno estetico
    c.setFillColor(colors.white)
    c.setStrokeColor(colors.HexColor("#cbd5e1"))
    c.setLineWidth(2)
    c.roundRect(x - 12, y - 12, size + 24, size + 24, radius=14, fill=1, stroke=1)

    qr_widget = QrCodeWidget(url)
    qr_widget.barLevel = "M"
    bounds = qr_widget.getBounds()
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]

    drawing = Drawing(size, size, transform=[size / width, 0, 0, size / height, 0, 0])
    drawing.add(Rect(0, 0, width, height, fillColor=colors.white, strokeColor=None))
    drawing.add(qr_widget)
    renderPDF.draw(drawing, c, x, y)


def draw_access_page(
    c: canvas.Canvas,
    page_num: int,
    total_pages: int,
    badge_text: str,
    badge_color: str,
    title: str,
    subtitle: str,
    when_to_use_lines: list[str],
    url: str,
    footer_note: str,
    extra_routes: list[tuple[str, str]] | None = None,
) -> None:
    """Disegna una singola pagina del PDF con Link cliccabile e QR Code sottostante."""
    width, height = A4
    center_x = width / 2.0

    # Sfondo Header Scuro Istituzionale
    c.setFillColor(colors.HexColor("#0f172a"))
    c.rect(0, height - 115, width, 115, fill=1, stroke=0)

    # Titolo Progetto nell'Header
    c.setFillColor(colors.HexColor("#38bdf8"))
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(
        center_x,
        height - 38,
        "CIVICPULSE MODENA • TESINA TECNOLOGIE WEB (UNIMORE)",
    )

    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 20)
    c.drawCentredString(center_x, height - 68, title)

    c.setFillColor(colors.HexColor("#cbd5e1"))
    c.setFont("Helvetica", 11)
    c.drawCentredString(center_x, height - 92, subtitle)

    # Badge Caso d'Uso
    badge_w = 340
    badge_h = 28
    c.setFillColor(colors.HexColor(badge_color))
    c.roundRect(center_x - badge_w / 2, height - 158, badge_w, badge_h, radius=14, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(center_x, height - 148, badge_text)

    # Box "Quando utilizzare questa modalità"
    box_top = height - 180
    box_h = 90
    box_w = width - 90
    box_x = 45
    c.setFillColor(colors.HexColor("#f8fafc"))
    c.setStrokeColor(colors.HexColor("#e2e8f0"))
    c.setLineWidth(1.2)
    c.roundRect(box_x, box_top - box_h, box_w, box_h, radius=10, fill=1, stroke=1)

    c.setFillColor(colors.HexColor("#1e293b"))
    c.setFont("Helvetica-Bold", 11)
    c.drawString(box_x + 16, box_top - 22, "Quando usare questo collegamento:")

    c.setFont("Helvetica", 10.5)
    c.setFillColor(colors.HexColor("#334155"))
    text_y = box_top - 42
    for line in when_to_use_lines:
        c.drawString(box_x + 20, text_y, f"•  {line}")
        text_y -= 18

    # Box Link Diretto Cliccabile
    link_box_top = box_top - box_h - 22
    link_box_h = 72
    c.setFillColor(colors.HexColor("#eff6ff"))
    c.setStrokeColor(colors.HexColor("#2563eb"))
    c.setLineWidth(1.8)
    c.roundRect(box_x, link_box_top - link_box_h, box_w, link_box_h, radius=10, fill=1, stroke=1)

    c.setFillColor(colors.HexColor("#1e40af"))
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(center_x, link_box_top - 22, "LINK DIRETTO CLICCABILE (Premi sul link o copialo nel browser):")

    c.setFillColor(colors.HexColor("#1d4ed8"))
    font_size = 15 if len(url) <= 36 else (12.5 if len(url) <= 50 else 10.5)
    c.setFont("Helvetica-Bold", font_size)
    c.drawCentredString(center_x, link_box_top - 49, url)

    # Rende l'intero box del link cliccabile nel PDF
    if url.startswith("http"):
        c.linkURL(
            url,
            (box_x, link_box_top - link_box_h, box_x + box_w, link_box_top),
            relative=0,
        )

    # Titolo sopra al QR Code
    qr_section_top = link_box_top - link_box_h - 32
    c.setFillColor(colors.HexColor("#0f172a"))
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(center_x, qr_section_top, "INQUADRA IL QR CODE CON FOTOCAMERA / TELEFONO / TABLET")

    # QR Code Grande Centrato
    qr_size = 220 if not extra_routes else 185
    qr_x = center_x - qr_size / 2
    qr_y = qr_section_top - qr_size - 28
    draw_qr_code(c, url, qr_x, qr_y, qr_size)

    # Se ci sono rotte extra (in Pagina 3), le mostra in una tabella rapida sotto il QR
    if extra_routes:
        extra_y = qr_y - 34
        c.setFillColor(colors.HexColor("#1e293b"))
        c.setFont("Helvetica-Bold", 10.5)
        c.drawCentredString(center_x, extra_y, "Scorciatoie dirette alle sezioni della Web App:")
        extra_y -= 18
        c.setFont("Helvetica", 9.5)
        for label, route_url in extra_routes:
            c.setFillColor(colors.HexColor("#334155"))
            c.drawString(box_x + 30, extra_y, f"•  {label}:")
            c.setFillColor(colors.HexColor("#2563eb"))
            c.drawString(box_x + 210, extra_y, route_url)
            if route_url.startswith("http"):
                c.linkURL(route_url, (box_x + 205, extra_y - 3, box_x + box_w - 20, extra_y + 10), relative=0)
            extra_y -= 15

    # Nota informativa in basso (ridotta leggermente se il testo è lungo)
    c.setFillColor(colors.HexColor("#64748b"))
    note_font_size = 9.5 if len(footer_note) <= 95 else 8.2
    c.setFont("Helvetica-Oblique", note_font_size)
    c.drawCentredString(center_x, 62, footer_note)

    # Footer linea + numerazione pagina
    c.setStrokeColor(colors.HexColor("#e2e8f0"))
    c.setLineWidth(1)
    c.line(45, 44, width - 45, 44)

    now_str = datetime.now().strftime("%d/%m/%Y ore %H:%M")
    c.setFillColor(colors.HexColor("#64748b"))
    c.setFont("Helvetica", 9)
    c.drawString(45, 28, f"Generato/Aggiornato automaticamente: {now_str}")
    c.drawRightString(width - 45, 28, f"Pagina {page_num} di {total_pages}")

    c.showPage()


def generate_pdf(public_url: str, lan_url: str, local_url: str, output_path: str) -> None:
    c = canvas.Canvas(output_path, pagesize=A4)
    c.setTitle("CivicPulse Modena - Link e QR Code di Accesso Multi-Dispositivo")
    c.setAuthor("CivicPulse Modena - Tesina Tecnologie Web UNIMORE")

    clean_public = public_url if public_url and public_url.startswith("http") else lan_url

    # PAGINA 1: HTTPS PUBBLICO (TUNNEL UNIVERSALE)
    draw_access_page(
        c=c,
        page_num=1,
        total_pages=3,
        badge_text="CASO 1 • ACCESSO UNIVERSALE HTTPS (CONSIGLIATO)",
        badge_color="#059669",
        title="1. Link HTTPS Pubblico (Qualsiasi Rete)",
        subtitle="Funziona su Mac, iPhone, Android e iPad anche su EmiliaRomagnaWiFi, eduroam o 4G/5G",
        when_to_use_lines=[
            "Quando sei connesso a reti Wi-Fi pubbliche o universitarie (EmiliaRomagnaWiFi, eduroam).",
            "Quando vuoi aprire la Web App da uno smartphone o tablet sotto rete dati mobile (4G / 5G).",
            "Abilita automaticamente anche il sensore GPS su dispositivi mobili grazie al protocollo sicuro HTTPS.",
        ],
        url=clean_public,
        footer_note="Nota: Questo link e il relativo QR Code si aggiornano da soli ogni volta che accendi 'ON-OFF Server'.",
    )

    # PAGINA 2: RETE LOCALE WI-FI DOMESTICA / HOTSPOT (LAN)
    draw_access_page(
        c=c,
        page_num=2,
        total_pages=3,
        badge_text="CASO 2 • RETE LOCALE WI-FI PRIVATA / HOTSPOT",
        badge_color="#2563eb",
        title="2. Link Rete Locale Wi-Fi (LAN)",
        subtitle="Accesso diretto ad alta velocità sulla stessa rete Wi-Fi di casa o Hotspot del telefono",
        when_to_use_lines=[
            "Quando il PC Linux e l'altro dispositivo (Mac, Telefono, Tablet) sono sul Wi-Fi di casa.",
            "Quando colleghi entrambi i dispositivi all'Hotspot personale del tuo smartphone.",
            "Connessione locale diretta senza passare da internet esterno (non usare su Wi-Fi pubblici isolati).",
        ],
        url=lan_url,
        footer_note="Assicurati che entrambi i dispositivi siano collegati alla stessa rete Wi-Fi privata o Hotspot.",
    )

    # PAGINA 3: ACCESSO LOCALE PC SERVER + SCORCIATOIE ESAME
    base_for_routes = clean_public if clean_public.startswith("https://") else local_url
    extra_routes = [
        ("Home Page & Mappa Modena", f"{local_url}/"),
        ("Nuova Segnalazione + AI + GPS", f"{local_url}/report/new"),
        ("Dashboard Analytics & Meteo", f"{local_url}/dashboard"),
        ("Kanban Board React 18 (SPA)", f"{local_url}/kanban"),
    ]
    draw_access_page(
        c=c,
        page_num=3,
        total_pages=3,
        badge_text="CASO 3 • QUESTO PC LINUX (LOCALHOST & ROTTE)",
        badge_color="#4f46e5",
        title="3. Link Locale su Questo PC (Localhost)",
        subtitle="Accesso diretto sul computer Linux che esegue il server Flask (porta 5000)",
        when_to_use_lines=[
            "Quando apri e dimostri la Web App direttamente su questo PC Linux.",
            "Funziona anche completamente offline (senza connessione internet attiva).",
            "Si apre già in automatico nel browser quando fai doppio click su 'ON-OFF Server'.",
        ],
        url=local_url,
        footer_note=f"Le stesse sottorotte (/report/new, /dashboard, /kanban) funzionano anche sul link HTTPS ({base_for_routes}).",
        extra_routes=extra_routes,
    )

    c.save()


if __name__ == "__main__":
    pub = sys.argv[1] if len(sys.argv) > 1 else "https://e66117752a7526.lhr.life"
    lan = sys.argv[2] if len(sys.argv) > 2 else "http://192.168.1.159:5000"
    loc = sys.argv[3] if len(sys.argv) > 3 else "http://127.0.0.1:5000"
    out = (
        sys.argv[4]
        if len(sys.argv) > 4
        else os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "LINK_E_QRCODE_DISPOSITIVI.pdf"))
    )
    generate_pdf(pub, lan, loc, out)
    print(f"PDF QR Code generato in: {out}")

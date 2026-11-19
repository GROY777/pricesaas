from datetime import datetime
from decimal import Decimal
from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

FONT_PATHS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "C:/Windows/Fonts/arial.ttf"]


def register_font():
    for path in FONT_PATHS:
        if Path(path).is_file():
            pdfmetrics.registerFont(TTFont("PriceSnap", path))
            return
    raise RuntimeError("Не найден шрифт с поддержкой кириллицы")


def wrap(text, width, size, max_lines):
    words = text.split()
    lines = []
    current = ""
    while words:
        word = words.pop(0)
        candidate = (current + " " + word).strip()
        if pdfmetrics.stringWidth(candidate, "PriceSnap", size) <= width:
            current = candidate
        elif current:
            lines.append(current)
            current = ""
            words.insert(0, word)
        else:
            cut = len(word)
            while cut > 1 and pdfmetrics.stringWidth(word[:cut], "PriceSnap", size) > width:
                cut -= 1
            lines.append(word[:cut])
            if word[cut:]:
                words.insert(0, word[cut:])
        if len(lines) == max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    return lines


def generate_pdf(path, items, template):
    register_font()
    thermal = template == "thermo_58x40"
    page_size = (58 * mm, 40 * mm) if thermal else A4
    pdf = canvas.Canvas(str(path), pagesize=page_size)
    cell_w = page_size[0] if thermal else page_size[0] / 3
    cell_h = page_size[1] if thermal else page_size[1] / 4
    count = 0
    for product, quantity in items:
        for _ in range(quantity):
            if count and (thermal or count % 12 == 0):
                pdf.showPage()
            slot = 0 if thermal else count % 12
            x = (slot % 3) * cell_w
            y = page_size[1] - (slot // 3 + 1) * cell_h
            pdf.saveState()
            pdf.translate(x, y)
            if not thermal:
                pdf.setDash(2, 2)
                pdf.rect(0, 0, cell_w, cell_h)
                pdf.setDash()
            pad = 4 * mm
            top = cell_h - pad
            if template == "a4_promo":
                pdf.setFillColor(colors.red)
                pdf.rect(pad, top - 7 * mm, cell_w - 2 * pad, 7 * mm, fill=1, stroke=0)
                pdf.setFillColor(colors.white)
                pdf.setFont("PriceSnap", 12)
                pdf.drawCentredString(cell_w / 2, top - 5 * mm, "АКЦИЯ")
                pdf.setFillColor(colors.black)
                top -= 9 * mm
            font_size = 8 if thermal else 10
            pdf.setFont("PriceSnap", font_size)
            for line in wrap(product.name, cell_w - 2 * pad, font_size, 2 if thermal else 3):
                top -= font_size + 2
                pdf.drawString(pad, top, line)
            if template == "a4_promo" and product.old_price is not None:
                old = f"{product.old_price:.2f} ₽"
                pdf.setFont("PriceSnap", 10)
                pdf.drawString(pad, 25 * mm, old)
                pdf.line(pad, 26 * mm, pad + pdfmetrics.stringWidth(old, "PriceSnap", 10), 26 * mm)
            price = f"{Decimal(product.price):.2f}"
            rubles, kopecks = price.split(".")
            price_size = 24 if thermal else 30
            while price_size > 12 and pdfmetrics.stringWidth(rubles, "PriceSnap", price_size) > cell_w - 28 * mm:
                price_size -= 1
            pdf.setFont("PriceSnap", price_size)
            baseline = 12 * mm if thermal else 13 * mm
            pdf.drawString(pad, baseline, rubles)
            pdf.setFont("PriceSnap", 11)
            pdf.drawString(pad + pdfmetrics.stringWidth(rubles, "PriceSnap", price_size) + 2, baseline + 5, kopecks + " ₽")
            pdf.setFont("PriceSnap", 7)
            pdf.drawRightString(cell_w - pad, baseline - 2, "/ " + product.unit)
            pdf.drawString(pad, 5 * mm, product.barcode)
            if not thermal:
                pdf.drawRightString(cell_w - pad, 5 * mm, datetime.now().strftime("%d.%m.%Y"))
            pdf.restoreState()
            count += 1
    pdf.save()

import json
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

FONTS = [
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
]


def register_font():
    for regular, bold in FONTS:
        if Path(regular).is_file() and Path(bold).is_file():
            pdfmetrics.registerFont(TTFont("PriceSnap", regular))
            pdfmetrics.registerFont(TTFont("PriceSnapBold", bold))
            return
    raise RuntimeError("Не найден шрифт с поддержкой кириллицы")


def fit_text(text, width, font, size):
    text = str(text).replace("\n", " ").strip()
    if pdfmetrics.stringWidth(text, font, size) <= width:
        return text
    while text and pdfmetrics.stringWidth(text + "…", font, size) > width:
        text = text[:-1]
    return text.rstrip() + "…"


def wrap(text, width, size, max_lines, font="PriceSnapBold"):
    words = str(text).split()
    lines = []
    while words and len(lines) < max_lines:
        line = ""
        while words:
            candidate = (line + " " + words[0]).strip()
            if pdfmetrics.stringWidth(candidate, font, size) <= width:
                line = candidate
                words.pop(0)
            elif not line:
                word = words.pop(0)
                cut = len(word)
                while cut > 1 and pdfmetrics.stringWidth(word[:cut], font, size) > width:
                    cut -= 1
                line = word[:cut]
                if word[cut:]:
                    words.insert(0, word[cut:])
                break
            else:
                break
        lines.append(line)
    if words and lines:
        lines[-1] = fit_text(lines[-1] + "…", width, font, size)
    return lines


def draw_thermal_label(pdf, product, company_name, width, height, print_date):
    pad = 2.5 * mm
    usable = width - 2 * pad
    pdf.setFillColor(colors.HexColor("#172033"))
    pdf.setFont("PriceSnapBold", 6.5)
    pdf.drawCentredString(width / 2, height - pad - 6.5, fit_text(company_name, usable, "PriceSnapBold", 6.5))
    line_y = height - pad - 10
    pdf.setStrokeColor(colors.HexColor("#94A3B8"))
    pdf.setLineWidth(.4)
    pdf.line(pad, line_y, width - pad, line_y)

    name_size = 8
    lines = wrap(product.name, usable, name_size, 3)
    while name_size > 6 and lines and lines[-1].endswith("…"):
        name_size -= .5
        lines = wrap(product.name, usable, name_size, 3)
    pdf.setFont("PriceSnapBold", name_size)
    y = line_y - 12
    for line in lines:
        pdf.drawCentredString(width / 2, y, line)
        y -= name_size + 1

    old = getattr(product, "old_price", None)
    if old is not None and Decimal(old) > Decimal(product.price):
        text = fit_text(f"{Decimal(old):.2f} ₽", usable * .55, "PriceSnap", 6)
        old_y = 20.5 * mm
        pdf.setFont("PriceSnap", 6)
        pdf.drawString(pad, old_y, text)
        old_width = pdfmetrics.stringWidth(text, "PriceSnap", 6)
        pdf.line(pad, old_y + 2, pad + old_width, old_y + 2)

    rubles, kopecks = f"{Decimal(product.price):.2f}".split(".")
    price_size = 25
    cents_size = 9
    cents_width = pdfmetrics.stringWidth(kopecks, "PriceSnapBold", cents_size)
    unit = fit_text("₽ / " + str(product.unit), usable * .25, "PriceSnap", 6.5)
    unit_width = pdfmetrics.stringWidth(unit, "PriceSnap", 6.5)
    while price_size > 8 and pdfmetrics.stringWidth(rubles, "PriceSnapBold", price_size) + cents_width + 3 > usable - 2 * unit_width:
        price_size -= 1
    rubles_width = pdfmetrics.stringWidth(rubles, "PriceSnapBold", price_size)
    price_x = (width - rubles_width - cents_width - 3) / 2
    baseline = 11.5 * mm
    pdf.setFillColor(colors.HexColor("#0F172A"))
    pdf.setFont("PriceSnapBold", price_size)
    pdf.drawString(price_x, baseline, rubles)
    pdf.setFont("PriceSnapBold", cents_size)
    pdf.drawString(price_x + rubles_width + 3, baseline + price_size * .4, kopecks)
    pdf.setFont("PriceSnap", 6.5)
    pdf.drawRightString(width - pad, baseline, unit)

    pdf.setStrokeColor(colors.HexColor("#94A3B8"))
    pdf.line(pad, 7.5 * mm, width - pad, 7.5 * mm)
    pdf.setFont("PriceSnap", 5.5)
    date = print_date.strftime("%d.%m.%Y")
    date_width = pdfmetrics.stringWidth(date, "PriceSnap", 5.5)
    barcode = fit_text("ШК: " + str(product.barcode), usable - date_width - 5, "PriceSnap", 5.5)
    pdf.drawString(pad, 4 * mm, barcode)
    pdf.drawRightString(width - pad, 4 * mm, date)


def draw_label(pdf, product, company_name, width, height, thermal, promo, print_date):
    if thermal:
        draw_thermal_label(pdf, product, company_name, width, height, print_date)
        return
    pad = (2.5 if thermal else 4) * mm
    usable = width - 2 * pad
    pdf.setFillColor(colors.HexColor("#172033"))
    header_size = 6 if thermal else 8
    pdf.setFont("PriceSnapBold", header_size)
    pdf.drawCentredString(width / 2, height - pad - header_size, fit_text(company_name, usable, "PriceSnapBold", header_size))
    line_y = height - pad - header_size - 3
    pdf.setStrokeColor(colors.HexColor("#94A3B8"))
    pdf.setLineWidth(.4)
    pdf.line(pad, line_y, width - pad, line_y)

    name_size = 8 if thermal else 10
    y = line_y - name_size - 4
    pdf.setFont("PriceSnapBold", name_size)
    for line in wrap(product.name, usable, name_size, 2 if thermal else 3):
        pdf.drawString(pad, y, line)
        y -= name_size + 2

    if promo:
        badge_y = 26 * mm
        pdf.setFillColor(colors.HexColor("#C81E1E"))
        pdf.roundRect(pad, badge_y, 20 * mm, 6 * mm, 2, fill=1, stroke=0)
        pdf.setFillColor(colors.white)
        pdf.setFont("PriceSnapBold", 8)
        pdf.drawCentredString(pad + 10 * mm, badge_y + 2 * mm, "АКЦИЯ")
        pdf.setFillColor(colors.HexColor("#172033"))

    old = getattr(product, "old_price", None)
    if old is not None and Decimal(old) > Decimal(product.price):
        old_text = f"{Decimal(old):.2f} ₽"
        old_size = 6 if thermal else 8
        old_y = (20 if thermal else 23) * mm
        pdf.setFont("PriceSnap", old_size)
        pdf.drawRightString(width - pad, old_y, old_text)
        old_width = pdfmetrics.stringWidth(old_text, "PriceSnap", old_size)
        pdf.line(width - pad - old_width, old_y + old_size * .35, width - pad, old_y + old_size * .35)

    rubles, kopecks = f"{Decimal(product.price):.2f}".split(".")
    size = 25 if thermal else 34
    while size > 10 and pdfmetrics.stringWidth(rubles, "PriceSnapBold", size) > usable * .65:
        size -= 1
    baseline = (11 if thermal else 12) * mm
    pdf.setFillColor(colors.HexColor("#0F172A"))
    pdf.setFont("PriceSnapBold", size)
    pdf.drawString(pad, baseline, rubles)
    end = pad + pdfmetrics.stringWidth(rubles, "PriceSnapBold", size) + 2
    pdf.setFont("PriceSnapBold", 9 if thermal else 11)
    pdf.drawString(end, baseline + size * .43, kopecks)
    unit = fit_text("₽ / " + str(product.unit), usable * .42, "PriceSnap", 6 if thermal else 7)
    pdf.setFont("PriceSnap", 6 if thermal else 7)
    pdf.drawRightString(width - pad, baseline, unit)

    footer_line = 7.5 * mm
    pdf.setStrokeColor(colors.HexColor("#94A3B8"))
    pdf.line(pad, footer_line, width - pad, footer_line)
    pdf.setFont("PriceSnap", 5.5 if thermal else 6.5)
    footer_size = 5.5 if thermal else 6.5
    date_text = print_date.strftime("%d.%m.%Y")
    date_width = pdfmetrics.stringWidth(date_text, "PriceSnap", footer_size)
    barcode = fit_text("ШК: " + str(product.barcode), usable - date_width - 4, "PriceSnap", footer_size)
    pdf.drawString(pad, 4 * mm, barcode)
    pdf.drawRightString(width - pad, 4 * mm, date_text)


def draw_configured_label(pdf, product, company_name, width, height, config, print_date):
    def colour(key, default):
        value = config.get(key, default)
        return colors.HexColor(value if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value) else default)

    layout = config.get("layout", "custom")
    pad = 3 * mm
    pdf.setFillColor(colour("background", "#ffffff"))
    pdf.rect(0, 0, width, height, fill=1, stroke=0)
    border = config.get("border", "solid")
    if border != "none":
        pdf.setStrokeColor(colour("accent", "#475569"))
        pdf.setLineWidth(1.5 if border == "double" else 0.7)
        if border == "dashed": pdf.setDash(2, 2)
        pdf.rect(2, 2, width - 4, height - 4, fill=0, stroke=1)
        pdf.setDash()
        if border == "double": pdf.rect(5, 5, width - 10, height - 10, fill=0, stroke=1)
    if config.get("show_company", True):
        pdf.setFillColor(colour("header", "#1e293b"))
        pdf.rect(0, height - 8 * mm, width, 8 * mm, fill=1, stroke=0)
        pdf.setFillColor(colors.white)
        pdf.setFont("PriceSnapBold", 8)
        header = "АКЦИЯ" if layout == "promo" else company_name
        pdf.drawCentredString(width / 2, height - 5.3 * mm, fit_text(header, width - 2 * pad, "PriceSnapBold", 8))
    if layout == "thermal-promo":
        pdf.setFillColor(colour("accent", "#b91c1c"))
        pdf.roundRect(width - 18 * mm, height - 15 * mm, 14 * mm, 5 * mm, 2, fill=1, stroke=0)
        pdf.setFillColor(colors.white); pdf.setFont("PriceSnapBold", 7)
        pdf.drawCentredString(width - 11 * mm, height - 13.5 * mm, "ХИТ")
    pdf.setFillColor(colour("accent", "#2563eb")); pdf.setFont("PriceSnapBold", 10 if layout == "boutique" else 9)
    y = height - 12 * mm
    for line in wrap(product.name, width - 2 * pad, 9, 2):
        if layout == "boutique": pdf.drawCentredString(width / 2, y, line)
        else: pdf.drawString(pad, y, line)
        y -= 11
    if config.get("show_old_price", True) and product.old_price is not None and product.old_price > product.price:
        pdf.setFont("PriceSnap", 7); old = str(product.old_price)
        x = pad if layout in ("promo", "thermal-promo") else width - pad - pdfmetrics.stringWidth(old, "PriceSnap", 7)
        pdf.drawString(x, 18 * mm, old); pdf.line(x, 18 * mm + 2, x + pdfmetrics.stringWidth(old, "PriceSnap", 7), 18 * mm + 2)
    pdf.setFillColor(colour("price", "#0f172a")); pdf.setFont("PriceSnapBold", 22 if layout == "promo" else 20)
    if layout == "thermal-promo":
        pdf.setStrokeColor(colour("accent", "#b91c1c")); pdf.rect(pad, 9 * mm, width - 2 * pad, 8 * mm, fill=0, stroke=1)
    pdf.drawCentredString(width / 2, 11 * mm, str(product.price))
    if config.get("show_unit", True): pdf.setFont("PriceSnap", 6); pdf.drawRightString(width - pad, 10 * mm, str(product.unit))
    pdf.setFont("PriceSnap", 6)
    if config.get("show_barcode", True): pdf.drawString(pad, 4 * mm, fit_text(str(product.barcode), width * .55, "PriceSnap", 6))
    if config.get("show_date", True): pdf.drawRightString(width - pad, 4 * mm, print_date.strftime("%d.%m.%Y"))


def generate_pdf(path, items, template, company_name="PriceSnap", config=None, format_type=None):
    register_font()
    thermal = format_type == "thermo" or template == "thermo_58x40" or str(template).startswith("premium-thermal") or str(template).startswith("promo-thermal")
    promo = template == "a4_promo" or str(template).startswith("promo-")
    parsed_config = json.loads(config) if isinstance(config, str) and config else config
    page_size = (58 * mm, 40 * mm) if thermal else A4
    pdf = canvas.Canvas(str(path), pagesize=page_size)
    cell_w = page_size[0] if thermal else page_size[0] / 3
    cell_h = page_size[1] if thermal else page_size[1] / 4
    count = 0
    print_date = datetime.now()
    for product, quantity in items:
        for _ in range(quantity):
            if count and (thermal or count % 12 == 0):
                pdf.showPage()
            slot = 0 if thermal else count % 12
            pdf.saveState()
            pdf.translate((slot % 3) * cell_w, page_size[1] - (slot // 3 + 1) * cell_h)
            if not thermal:
                pdf.setStrokeColor(colors.HexColor("#94A3B8"))
                pdf.setDash(2, 2)
                pdf.rect(0, 0, cell_w, cell_h)
                pdf.setDash()
            if parsed_config is not None:
                draw_configured_label(pdf, product, company_name, cell_w, cell_h, parsed_config, print_date)
            else:
                draw_label(pdf, product, company_name, cell_w, cell_h, thermal, promo, print_date)
            pdf.restoreState()
            count += 1
    pdf.save()

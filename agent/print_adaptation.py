"""Choose a print layout from the PDF and the selected Windows printer."""
from pathlib import Path

from pypdf import PdfReader, PdfWriter

POINTS_PER_MM = 72 / 25.4
DM_ORIENTATION = 0x1
DM_PAPERSIZE = 0x2
DM_PAPERLENGTH = 0x4
DM_PAPERWIDTH = 0x8
DMORIENT_LANDSCAPE = 2


def printer_geometry(printer_name):
    """Return the effective page width and height in mm, or None if unknown."""
    import win32con
    import win32print

    handle = win32print.OpenPrinter(printer_name)
    try:
        info = win32print.GetPrinter(handle, 2)
        dev = info.get('pDevMode')
        if dev is None:
            return None
        fields = dev.Fields
        width = dev.PaperWidth / 10 if fields & DM_PAPERWIDTH else 0
        height = dev.PaperLength / 10 if fields & DM_PAPERLENGTH else 0
        if (width <= 0 or height <= 0) and fields & DM_PAPERSIZE:
            try:
                sizes = win32print.DeviceCapabilities(printer_name, info['pPortName'], win32con.DC_PAPERSIZE)
                ids = win32print.DeviceCapabilities(printer_name, info['pPortName'], win32con.DC_PAPERS)
                if dev.PaperSize in ids:
                    size = sizes[list(ids).index(dev.PaperSize)]
                    width, height = size[0] / 10, size[1] / 10
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                return None
        if width <= 0 or height <= 0:
            return None
        if fields & DM_ORIENTATION and dev.Orientation == DMORIENT_LANDSCAPE:
            width, height = height, width
        return width, height
    finally:
        win32print.ClosePrinter(handle)


def page_dimensions_mm(page):
    width = float(page.mediabox.width) / POINTS_PER_MM
    height = float(page.mediabox.height) / POINTS_PER_MM
    return (height, width) if int(page.rotation or 0) % 180 else (width, height)


def prepare_pdf(path, output_path, geometry):
    """Rotate 58x40 label pages if a known narrow page has opposite orientation.

    A4 and unknown page sizes are left untouched. Unknown printer geometry
    uses the original PDF; caller can still print it without crashing.
    """
    reader = PdfReader(str(path))
    if not reader.pages:
        raise ValueError('PDF не содержит страниц')
    dimensions = [page_dimensions_mm(page) for page in reader.pages]
    thermal = all(abs(max(w, h) - 58) < 1 and abs(min(w, h) - 40) < 1 for w, h in dimensions)
    if not thermal or not geometry or min(geometry) >= 100:
        return Path(path), thermal
    printer_landscape = geometry[0] > geometry[1]
    if all((w > h) == printer_landscape for w, h in dimensions):
        return Path(path), True
    writer = PdfWriter()
    for page, (width, height) in zip(reader.pages, dimensions):
        if (width > height) != printer_landscape:
            page.rotate(90)
            page.transfer_rotation_to_content()
        writer.add_page(page)
    with open(output_path, 'wb') as output:
        writer.write(output)
    return Path(output_path), True

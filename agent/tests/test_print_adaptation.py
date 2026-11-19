import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pypdf import PdfReader, PdfWriter
from print_adaptation import prepare_pdf, printer_geometry


class AdaptationTests(unittest.TestCase):
    def make_pdf(self, directory, width, height, pages=1):
        path = Path(directory) / 'input.pdf'
        writer = PdfWriter()
        for _ in range(pages):
            writer.add_blank_page(width=width * 72 / 25.4, height=height * 72 / 25.4)
        with path.open('wb') as file:
            writer.write(file)
        return path

    def test_label_rotates_only_when_orientation_differs(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.make_pdf(directory, 58, 40, pages=2)
            result, thermal = prepare_pdf(source, Path(directory) / 'output.pdf', (40, 58))
            self.assertTrue(thermal)
            self.assertNotEqual(result, source)
            pages = PdfReader(result).pages
            self.assertEqual(len(pages), 2)
            for page in pages:
                self.assertAlmostEqual(float(page.mediabox.width) * 25.4 / 72, 40, places=2)
                self.assertAlmostEqual(float(page.mediabox.height) * 25.4 / 72, 58, places=2)
                self.assertEqual(page.rotation, 0)
            self.assertEqual(prepare_pdf(source, Path(directory) / 'same.pdf', (58, 40)), (source, True))
            self.assertEqual(prepare_pdf(source, Path(directory) / 'unknown.pdf', None), (source, True))

    def test_a4_is_never_rotated_for_label_printer(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.make_pdf(directory, 210, 297)
            self.assertEqual(prepare_pdf(source, Path(directory) / 'out.pdf', (58, 40)), (source, False))

    def test_printer_dimensions_and_missing_size(self):
        import win32print
        base = {'pPortName':'USB001', 'pDevMode':SimpleNamespace(Fields=0x0f, PaperWidth=580, PaperLength=400, PaperSize=256, Orientation=1)}
        with patch.object(win32print, 'OpenPrinter', return_value=1), patch.object(win32print, 'ClosePrinter'), patch.object(win32print, 'GetPrinter', return_value=base):
            self.assertEqual(printer_geometry('test'), (58, 40))
            base['pDevMode'].Orientation = 2
            self.assertEqual(printer_geometry('test'), (40, 58))
            base['pDevMode'].Fields = 1
            self.assertIsNone(printer_geometry('test'))


if __name__ == '__main__':
    unittest.main()

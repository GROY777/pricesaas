import hashlib
import hmac
import json
import os
import tempfile
import time
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-thirty-two-characters-long")
os.environ.setdefault("BOT_TOKEN", "123456:test-token")

from pypdf import PdfReader
from app.config import get_settings
from app.pdf_generator import generate_pdf
from app.security import verify_telegram_init_data


def signed_data(auth_date):
    data = {"auth_date": str(auth_date), "user": json.dumps({"id": 123, "first_name": "Тест"}, ensure_ascii=False, separators=(",", ":"))}
    check = "\n".join(f"{key}={value}" for key, value in sorted(data.items()))
    secret = hmac.new(b"WebAppData", get_settings().bot_token.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


class TelegramTests(unittest.TestCase):
    def test_valid_tampered_and_expired_data(self):
        valid = signed_data(int(time.time()))
        self.assertEqual(verify_telegram_init_data(valid)["id"], 123)
        with self.assertRaises(ValueError):
            verify_telegram_init_data(valid.replace("123", "124"))
        with self.assertRaises(ValueError):
            verify_telegram_init_data(signed_data(int(time.time()) - 90000))
        with self.assertRaises(ValueError):
            verify_telegram_init_data(valid + "&auth_date=1")


class PdfTests(unittest.TestCase):
    def test_quantities_page_sizes_and_cyrillic(self):
        product = SimpleNamespace(name="Молоко", price=Decimal("125.50"), old_price=Decimal("150.00"), barcode="123456789", unit="шт.")
        with tempfile.TemporaryDirectory() as directory:
            for template, quantity, expected_pages in [("a4_3x4", 13, 2), ("a4_promo", 1, 1), ("thermo_58x40", 3, 3)]:
                path = Path(directory) / (template + ".pdf")
                generate_pdf(path, [(product, quantity)], template)
                pages = PdfReader(path).pages
                self.assertEqual(len(pages), expected_pages)
                self.assertIn("Молоко", pages[0].extract_text())
                if template == "thermo_58x40":
                    self.assertAlmostEqual(float(pages[0].mediabox.width) * 25.4 / 72, 40, places=2)
                    self.assertAlmostEqual(float(pages[0].mediabox.height) * 25.4 / 72, 58, places=2)


if __name__ == "__main__":
    unittest.main()

import csv
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import winreg
from pathlib import Path

import pandas as pd
import pystray
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import win32api
import win32print
from PIL import Image, ImageDraw
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from print_adaptation import prepare_pdf, printer_geometry

CONFIG = Path(os.environ["APPDATA"]) / "PriceAgent" / "config.json"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

def device_hwid():
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
            return str(value)
    except (OSError, TypeError):
        try:
            output = subprocess.check_output(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_ComputerSystemProduct).UUID"], text=True, timeout=5)
            return output.strip()
        except Exception:
            return "unknown-" + os.environ.get("COMPUTERNAME", "device")



def read_products(path):
    path = Path(path)
    if path.suffix.lower() == ".csv":
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp1251")
        from io import StringIO
        try:
            delimiter = csv.Sniffer().sniff(text[:8192], delimiters=";,").delimiter
        except csv.Error:
            delimiter = ";"
        frame = pd.read_csv(StringIO(text), sep=delimiter, dtype=str, keep_default_na=False)
    else:
        frame = pd.read_excel(path, dtype=str, keep_default_na=False)
    columns = {str(c).strip().lower(): c for c in frame.columns}
    def find(names, required=True):
        for name in names:
            for key, original in columns.items():
                if name in key:
                    return original
        if required:
            raise ValueError("Не найден столбец: " + "/".join(names))
        return None
    barcode = find(["штрихкод", "штрих код", "barcode"])
    name = find(["наименование", "товар", "name"])
    price = find(["цена", "price"])
    unit = find(["единица", "ед.", "unit"], False)
    result = []
    for _, row in frame.iterrows():
        code = str(row[barcode]).strip()
        if not code or not str(row[name]).strip():
            continue
        value = re.sub(r"[^\d,.\-]", "", str(row[price])).replace(",", ".")
        if not value:
            raise ValueError(f"Не указана цена товара {code}")
        result.append({"barcode": code, "name": str(row[name]).strip(), "price": value, "unit": str(row[unit]).strip() or "шт." if unit else "шт."})
    return result


if __name__ == "__main__":
    import webview
    from web_api import AgentAPI
    api = AgentAPI(read_products, device_hwid())
    ui = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "ui.html"
    window = webview.create_window("PriceSnap Agent", ui.as_uri(), js_api=api, width=760, height=520, frameless=True, easy_drag=False, resizable=False, background_color="#0A0D14")
    api._window = window
    window.events.closed += api.shutdown
    webview.start(api.start, gui="edgechromium")

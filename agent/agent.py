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
    from price_import import parse_products
    return parse_products(path, Path(path).name)


if __name__ == "__main__":
    import webview
    from web_api import AgentAPI
    api = AgentAPI(read_products, device_hwid())
    ui = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "ui.html"
    window = webview.create_window("PriceSnap Agent", ui.as_uri(), js_api=api, width=760, height=520, frameless=True, easy_drag=False, resizable=False, background_color="#0A0D14")
    api._window = window
    window.events.closed += api.shutdown
    webview.start(api.start, gui="edgechromium")

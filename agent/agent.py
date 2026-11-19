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
from tkinter import filedialog, messagebox

import customtkinter as ctk
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


class Watcher(FileSystemEventHandler):
    def __init__(self, app):
        self.app = app

    def on_any_event(self, event):
        if not event.is_directory and event.event_type in ("modified", "created", "moved"):
            target = getattr(event, "dest_path", event.src_path)
            if os.path.normcase(os.path.abspath(target)) == os.path.normcase(os.path.abspath(self.app.path.get())):
                self.app.schedule_sync()


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("PriceAgent")
        self.geometry("650x570")
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.timer = None
        self.observer = None
        self.tray = None
        self.http = requests.Session()
        # A configured Windows/enterprise proxy can time out on the VPS endpoint.
        # PriceSnap uses its own HTTPS origin, so connect directly to it.
        self.http.trust_env = False
        retry = Retry(total=3, connect=3, read=0, backoff_factor=0.7, allowed_methods=frozenset({"GET", "POST"}))
        self.http.mount("https://", HTTPAdapter(max_retries=retry))
        self.http.mount("http://", HTTPAdapter(max_retries=retry))
        try:
            data = json.loads(CONFIG.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        self.url = ctk.StringVar(value=data.get("url", "https://cardifyrbx.shop"))
        self.key = ctk.StringVar(value=data.get("key", ""))
        self.path = ctk.StringVar(value=data.get("path", ""))
        self.printer = ctk.StringVar(value=data.get("printer", ""))
        self.autostart = ctk.BooleanVar(value=data.get("autostart", False))
        self.status = ctk.StringVar(value="Готово")
        for label, variable in [("Адрес сервера", self.url), ("API-ключ магазина", self.key), ("Файл выгрузки", self.path)]:
            ctk.CTkLabel(self, text=label).pack(anchor="w", padx=20)
            ctk.CTkEntry(self, textvariable=variable).pack(fill="x", padx=20, pady=3)
        ctk.CTkButton(self, text="Выбрать файл", command=self.choose).pack(pady=5)
        try:
            printers = [p[2] for p in win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)]
        except Exception:
            printers = []
            self.status.set("Не удалось получить список принтеров. Проверьте службу диспетчера печати Windows и перезапустите программу.")
        if not self.printer.get() and printers:
            self.printer.set(printers[0])
        ctk.CTkLabel(self, text="Принтер").pack(anchor="w", padx=20)
        ctk.CTkOptionMenu(self, variable=self.printer, values=printers or ["Нет принтеров"]).pack(fill="x", padx=20)
        ctk.CTkCheckBox(self, text="Запускать вместе с Windows", variable=self.autostart).pack(pady=10)
        ctk.CTkButton(self, text="Проверить и сохранить", command=self.save).pack(pady=4)
        ctk.CTkButton(self, text="Синхронизировать сейчас", command=lambda: threading.Thread(target=self.sync, daemon=True).start()).pack(pady=4)
        ctk.CTkLabel(self, textvariable=self.status, wraplength=600).pack(pady=8)
        self.protocol("WM_DELETE_WINDOW", self.hide)
        self.watch()
        threading.Thread(target=self.poll, daemon=True).start()

    def notify(self, text):
        self.after(0, lambda: self.status.set(text))

    def headers(self):
        return {"X-API-Key": self.key.get().strip()}

    def endpoint(self, path):
        return self.url.get().strip().rstrip("/") + path

    def choose(self):
        path = filedialog.askopenfilename(filetypes=[("Файлы товаров", "*.csv *.xlsx *.xls")])
        if path:
            self.path.set(path)
            self.watch()

    def save(self):
        try:
            response = self.http.post(self.endpoint("/api/sync"), headers=self.headers(), json=[], timeout=(8, 20))
            response.raise_for_status()
            CONFIG.parent.mkdir(parents=True, exist_ok=True)
            CONFIG.write_text(json.dumps({"url": self.url.get(), "key": self.key.get(), "path": self.path.get(), "printer": self.printer.get(), "autostart": self.autostart.get()}, ensure_ascii=False, indent=2), encoding="utf-8")
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                if self.autostart.get():
                    command = f'"{sys.executable}"' if getattr(sys, "frozen", False) else f'"{sys.executable}" "{Path(__file__).resolve()}"'
                    winreg.SetValueEx(key, "PriceAgent", 0, winreg.REG_SZ, command)
                else:
                    try:
                        winreg.DeleteValue(key, "PriceAgent")
                    except FileNotFoundError:
                        pass
            self.watch()
            self.status.set("Настройки сохранены")
        except (requests.RequestException, OSError) as exc:
            messagebox.showerror("Ошибка", str(exc))

    def watch(self):
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.observer = None
        path = Path(self.path.get())
        if path.is_file():
            self.observer = Observer()
            self.observer.schedule(Watcher(self), str(path.resolve().parent), recursive=False)
            self.observer.start()

    def schedule_sync(self):
        if self.timer:
            self.timer.cancel()
        self.timer = threading.Timer(2, self.sync)
        self.timer.daemon = True
        self.timer.start()

    def sync(self):
        if not self.lock.acquire(blocking=False):
            return
        try:
            self.notify("Синхронизация…")
            products = read_products(self.path.get())
            for start in range(0, len(products), 500):
                response = self.http.post(self.endpoint("/api/sync"), headers=self.headers(), json=products[start:start + 500], timeout=(8, 45))
                response.raise_for_status()
            self.notify(f"Синхронизировано товаров: {len(products)}")
        except Exception as exc:
            self.notify(f"Ошибка синхронизации: {exc}")
        finally:
            self.lock.release()

    def poll(self):
        while not self.stop.wait(3):
            if not self.key.get() or not self.printer.get():
                continue
            try:
                jobs = self.http.get(self.endpoint("/api/agent/jobs"), headers=self.headers(), timeout=(8, 25))
                jobs.raise_for_status()
                for job in jobs.json():
                    job_headers = {**self.headers(), "X-Job-Token": job["lock_token"]}
                    response = self.http.get(self.endpoint(job["file_url"]), headers=job_headers, timeout=(8, 60))
                    response.raise_for_status()
                    with tempfile.TemporaryDirectory() as directory:
                        path = Path(directory) / "label.pdf"
                        path.write_bytes(response.content)
                        try:
                            geometry = printer_geometry(self.printer.get())
                        except Exception:
                            geometry = None
                        print_path, is_thermal = prepare_pdf(path, Path(directory) / "adapted.pdf", geometry)
                        bundled = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "SumatraPDF.exe"
                        if bundled.is_file():
                            settings = "shrink" if is_thermal else "noscale"
                            subprocess.run([str(bundled), "-print-to", self.printer.get(), "-print-settings", settings, "-silent", str(print_path)], check=True, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
                        else:
                            win32api.ShellExecute(0, "printto", str(print_path), f'"{self.printer.get()}"', ".", 0)
                            time.sleep(5)
                    ack = self.http.post(self.endpoint(f'/api/agent/jobs/{job["id"]}/ack'), headers=job_headers, timeout=(8, 25))
                    ack.raise_for_status()
                    self.notify(f'Задание {job["id"]} отправлено на принтер')
            except requests.Timeout:
                self.notify("Сервер временно не отвечает. Повтор через 3 секунды…")
            except requests.RequestException as exc:
                self.notify(f"Сетевая ошибка: {exc}")
            except Exception as exc:
                self.notify(f"Ошибка печати: {exc}")

    def hide(self):
        self.withdraw()
        if self.tray:
            return
        image = Image.new("RGB", (64, 64), "#1d4ed8")
        draw = ImageDraw.Draw(image)
        draw.rectangle((14, 18, 50, 46), outline="white", width=4)
        self.tray = pystray.Icon("PriceAgent", image, "PriceAgent", menu=pystray.Menu(pystray.MenuItem("Открыть", lambda: self.after(0, self.show)), pystray.MenuItem("Выход", lambda: self.after(0, self.quit_app))))
        threading.Thread(target=self.tray.run, daemon=True).start()

    def show(self):
        self.deiconify()
        self.lift()

    def quit_app(self):
        self.stop.set()
        self.http.close()
        if self.timer:
            self.timer.cancel()
        if self.observer:
            self.observer.stop()
            self.observer.join()
        if self.tray:
            self.tray.stop()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()

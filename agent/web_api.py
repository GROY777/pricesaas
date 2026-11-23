import json
import base64
import os
import subprocess
import sys
import tempfile
import threading
import time
import winreg
from pathlib import Path

import requests
import webview
import win32api
import win32clipboard
import win32con
import win32print
import win32crypt
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from print_adaptation import prepare_pdf, printer_geometry
from version import AGENT_VERSION
from packaging.version import Version, InvalidVersion

CONFIG = Path(os.environ.get('PRICEAGENT_CONFIG', str(Path(os.environ['APPDATA']) / 'PriceAgent' / 'config.json')))
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
UPDATE_URL = 'https://cardifyrbx.shop/releases/PriceAgent_Setup.exe'

def write_config(config):
    stored = dict(config)
    key = stored.pop('key', '')
    stored['key_dpapi'] = base64.b64encode(win32crypt.CryptProtectData(key.encode('utf-8'), None, None, None, None, 1)).decode('ascii')
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    temp = CONFIG.with_suffix('.tmp')
    temp.write_text(json.dumps(stored, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, CONFIG)

def read_config():
    try:
        data = json.loads(CONFIG.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    if 'key_dpapi' in data:
        try:
            data['key'] = win32crypt.CryptUnprotectData(base64.b64decode(data.pop('key_dpapi')), None, None, None, 1)[1].decode('utf-8')
        except Exception as exc:
            raise RuntimeError('Не удалось расшифровать ключ магазина для текущего пользователя Windows') from exc
    elif data.get('key'):
        write_config(data)
    return data


class Watcher(FileSystemEventHandler):
    def __init__(self, api): self.api = api
    def on_any_event(self, event):
        target = getattr(event, 'dest_path', event.src_path)
        if not event.is_directory and event.event_type in ('modified', 'created', 'moved') and os.path.normcase(os.path.abspath(target)) == os.path.normcase(os.path.abspath(self.api.config.get('path', ''))):
            self.api.schedule_sync()


class AgentAPI:
    def __init__(self, read_products, hwid):
        self.read_products = read_products
        self.hwid = hwid
        self.config = read_config()
        for key, value in {'url':'https://cardifyrbx.shop','key':'','path':'','printer':'','autostart':False}.items(): self.config.setdefault(key, value)
        self.stop = threading.Event(); self.lock = threading.Lock(); self.timer = None; self.observer = None; self._window = None; self.printed = 0; self.update_info = None
        self.http = requests.Session(); self.http.trust_env = False
        retry = Retry(total=3, connect=3, read=0, backoff_factor=.7, allowed_methods=frozenset({'GET','POST'}))
        self.http.mount('https://', HTTPAdapter(max_retries=retry)); self.http.mount('http://', HTTPAdapter(max_retries=retry))

    def emit(self, kind, **data):
        if self._window:
            try: self._window.evaluate_js('window.agentEvent(' + json.dumps({'type':kind, **data}, ensure_ascii=False) + ')')
            except Exception: pass
    def headers(self): return {'X-API-Key':self.config['key'].strip(), 'X-Device-HWID':self.hwid}
    def endpoint(self, path): return self.config['url'].strip().rstrip('/') + path
    def initial(self): return {'config':self.config, 'printers':self.printers(), 'version': AGENT_VERSION, 'update': self.update_info}
    def printers(self):
        try: return [p[2] for p in win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)]
        except Exception: return []
    def choose_file(self):
        result = self._window.create_file_dialog(webview.OPEN_DIALOG, file_types=('Price files (*.csv;*.xlsx;*.xls)', 'All files (*.*)'))
        return result[0] if result else None
    def clipboard_text(self):
        win32clipboard.OpenClipboard()
        try:
            return win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()
    def minimize(self): self._window.minimize()
    def close(self): self._window.destroy()
    def save(self, config):
        try:
            candidate = {k:config.get(k, self.config[k]) for k in ('url','key','path','printer','autostart')}
            response = self.http.post(candidate['url'].strip().rstrip('/')+'/api/sync', headers={'X-API-Key':candidate['key'].strip(),'X-Device-HWID':self.hwid}, json=[], timeout=(8,20)); response.raise_for_status()
            write_config(candidate)
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER,RUN_KEY) as key:
                if candidate['autostart']:
                    command = f'"{sys.executable}"' if getattr(sys,'frozen',False) else f'"{sys.executable}" "{Path(sys.argv[0]).resolve()}"'
                    winreg.SetValueEx(key,'PriceAgent',0,winreg.REG_SZ,command)
                else:
                    try: winreg.DeleteValue(key,'PriceAgent')
                    except FileNotFoundError: pass
            self.config = candidate; self.watch(); self.connected(response); self.emit('log',message='Настройки сохранены',level='success'); return {'ok':True}
        except Exception as exc:
            self.emit('connection',online=False); self.emit('log',message=str(exc),level='error'); return {'ok':False,'error':str(exc)}
    def connected(self,response):
        try: data=response.json()
        except ValueError: data=None
        name=(data.get('company_name') or data.get('tenant_name')) if isinstance(data,dict) else None
        self.emit('connection',online=True,company=name or 'Магазин подключён')
    def watch(self):
        if self.observer: self.observer.stop(); self.observer.join(); self.observer=None
        path=Path(self.config['path'])
        if path.is_file(): self.observer=Observer(); self.observer.schedule(Watcher(self),str(path.resolve().parent),recursive=False); self.observer.start()
    def schedule_sync(self):
        if self.timer: self.timer.cancel()
        self.timer=threading.Timer(2,self.sync); self.timer.daemon=True; self.timer.start()
    def sync(self):
        if not self.lock.acquire(blocking=False): return {'ok':False,'error':'Синхронизация уже выполняется'}
        self.emit('sync',active=True)
        try:
            products=self.read_products(self.config['path'])
            for i in range(0,len(products),500):
                r=self.http.post(self.endpoint('/api/sync'),headers=self.headers(),json=products[i:i+500],timeout=(8,45)); r.raise_for_status(); self.connected(r)
            self.emit('log',message=f'Синхронизировано товаров: {len(products)}',level='success'); return {'ok':True,'count':len(products)}
        except Exception as exc:
            if isinstance(exc,requests.RequestException): self.emit('connection',online=False)
            self.emit('log',message=f'Ошибка синхронизации: {exc}',level='error'); return {'ok':False,'error':str(exc)}
        finally: self.emit('sync',active=False); self.lock.release()
    def poll(self):
        while not self.stop.wait(3):
            if not self.config['key'] or not self.config['printer']: continue
            try:
                jobs=self.http.get(self.endpoint('/api/agent/jobs'),headers=self.headers(),timeout=(8,25)); jobs.raise_for_status(); self.connected(jobs)
                for job in jobs.json():
                    headers={**self.headers(),'X-Job-Token':job['lock_token']}; response=self.http.get(self.endpoint(job['file_url']),headers=headers,timeout=(8,60)); response.raise_for_status()
                    with tempfile.TemporaryDirectory() as d:
                        path=Path(d)/'label.pdf'; path.write_bytes(response.content)
                        try: geometry=printer_geometry(self.config['printer'])
                        except Exception: geometry=None
                        output,thermal=prepare_pdf(path,Path(d)/'adapted.pdf',geometry); exe=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'SumatraPDF.exe'
                        if exe.is_file(): subprocess.run([str(exe),'-print-to',self.config['printer'],'-print-settings','shrink' if thermal else 'noscale','-silent',str(output)],check=True,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW)
                        elif thermal: win32api.ShellExecute(0,'printto',str(output),f'"{self.config["printer"]}"','.',0); time.sleep(5)
                        else: raise RuntimeError('SumatraPDF не найден: печать А4 без изменения масштаба недоступна')
                    ack=self.http.post(self.endpoint(f'/api/agent/jobs/{job["id"]}/ack'),headers=headers,timeout=(8,25)); ack.raise_for_status(); self.printed+=job.get('items_count',1); self.emit('printed',count=self.printed); self.emit('log',message=f'Задание {job["id"]} отправлено на принтер',level='success')
            except requests.RequestException as exc: self.emit('connection',online=False); self.emit('log',message=f'Сетевая ошибка: {exc}',level='error')
            except Exception as exc: self.emit('log',message=f'Ошибка печати: {exc}',level='error')
    def check_update(self):
        try:
            response = self.http.get('https://cardifyrbx.shop/api/agent/version', timeout=(8, 20))
            response.raise_for_status()
            data = response.json()
            if data.get('download_url') != UPDATE_URL:
                raise ValueError('Недопустимый адрес обновления')
            if Version(data['version']) > Version(AGENT_VERSION):
                self.update_info = {'version': data['version'], 'notes': str(data.get('release_notes', '')), 'mandatory': bool(data.get('mandatory', False))}
                self.emit('update', **self.update_info)
        except (requests.RequestException, ValueError, KeyError, InvalidVersion) as exc:
            self.emit('log', message=f'Не удалось проверить обновления: {exc}', level='error')

    def install_update(self):
        if not self.update_info:
            return {'ok': False, 'error': 'Обновление недоступно'}
        try:
            directory = Path(tempfile.mkdtemp(prefix='pricesnap-update-'))
            path = directory / 'PriceAgent_Setup.exe'
            with self.http.get(UPDATE_URL, stream=True, timeout=(8, 60), allow_redirects=False) as response:
                response.raise_for_status()
                if response.status_code != 200:
                    raise ValueError('Ошибка загрузки обновления')
                size = 0
                with path.open('wb') as file:
                    for chunk in response.iter_content(1024 * 1024):
                        size += len(chunk)
                        if size > 250 * 1024 * 1024:
                            raise ValueError('Слишком большой файл обновления')
                        file.write(chunk)
            with path.open('rb') as installer:
                valid_header = installer.read(2) == b'MZ'
            if size < 100000 or not valid_header:
                raise ValueError('Получен некорректный установщик')
            subprocess.Popen([str(path), '/SILENT', '/CLOSEAPPLICATIONS', '/RESTARTAPPLICATIONS'], close_fds=True)
            self._window.destroy()
            return {'ok': True}
        except Exception as exc:
            self.emit('log', message=f'Ошибка обновления: {exc}', level='error')
            return {'ok': False, 'error': str(exc)}

    def start(self):
        self.watch(); threading.Thread(target=self.poll,daemon=True).start(); threading.Thread(target=self.check_update,daemon=True).start()
    def shutdown(self):
        self.stop.set()
        if self.timer: self.timer.cancel()
        if self.observer: self.observer.stop(); self.observer.join()
        self.http.close()

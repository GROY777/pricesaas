#!/usr/bin/env python3
"""Back up the Compose PostgreSQL database and send it to the configured admin."""
import datetime as dt
import gzip
import http.client
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

ROOT = Path('/opt/price-saas')
BACKUPS = Path('/var/backups/pricesnap')
COMPOSE = ['docker', 'compose', '--project-directory', str(ROOT)]


def compose(*args):
    return subprocess.run([*COMPOSE, *args], check=True, stdout=subprocess.PIPE).stdout


def main():
    os.umask(0o077)
    BACKUPS.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(BACKUPS, 0o700)
    now = dt.datetime.now().astimezone()
    target = BACKUPS / ('pricesnap_backup_' + now.strftime('%Y-%m-%d_%H-%M') + '.sql.gz')
    temp = target.with_suffix('.partial')
    try:
        with temp.open('wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb') as archive:
            proc = subprocess.Popen([*COMPOSE, 'exec', '-T', 'db', 'sh', '-c',
                'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-acl'], stdout=subprocess.PIPE)
            try:
                shutil.copyfileobj(proc.stdout, archive)
            finally:
                proc.stdout.close()
            if proc.wait() != 0:
                raise RuntimeError('pg_dump failed')
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    for old in BACKUPS.glob('pricesnap_backup_*.sql.gz'):
        if old != target and old.stat().st_mtime < time.time() - 14 * 86400:
            old.unlink()
    count = compose('exec', '-T', 'db', 'sh', '-c',
        'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT count(*) FROM products"').decode().strip()
    if not count.isdigit():
        raise RuntimeError('Invalid product count')
    config = json.loads(compose('exec', '-T', 'backend', 'python', '-c',
        'import json,os; print(json.dumps({k:os.environ.get(k,"") for k in ("BOT_TOKEN","ADMIN_CHAT_ID")}))'))
    token, chat = config['BOT_TOKEN'], config['ADMIN_CHAT_ID']
    if not token or not chat:
        raise RuntimeError('BOT_TOKEN or ADMIN_CHAT_ID is missing')
    if target.stat().st_size > 50 * 1024 * 1024:
        raise RuntimeError('Backup exceeds Telegram Bot API upload limit; local backup retained')
    caption = f"PriceSnap: {now:%d.%m.%Y %H:%M %Z}; {target.stat().st_size / 1048576:.2f} MB; товаров: {count}"
    boundary = 'pricesnap-' + uuid.uuid4().hex
    def field(name, value):
        return (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n').encode('utf-8')
    prefix = field('chat_id', chat) + field('caption', caption) + (
        f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="{target.name}"\r\n'
        'Content-Type: application/gzip\r\n\r\n').encode('ascii')
    suffix = f'\r\n--{boundary}--\r\n'.encode('ascii')
    conn = http.client.HTTPSConnection('api.telegram.org', timeout=120)
    try:
        conn.putrequest('POST', f'/bot{token}/sendDocument')
        conn.putheader('Content-Type', f'multipart/form-data; boundary={boundary}')
        conn.putheader('Content-Length', str(len(prefix) + target.stat().st_size + len(suffix)))
        conn.endheaders()
        conn.send(prefix)
        with target.open('rb') as file:
            while chunk := file.read(1024 * 1024):
                conn.send(chunk)
        conn.send(suffix)
        response = conn.getresponse()
        result = json.loads(response.read())
        if response.status != 200 or not result.get('ok'):
            raise RuntimeError(f'Telegram upload failed (HTTP {response.status})')
    finally:
        conn.close()
    print(f'Backup saved and sent: {target.name}; products: {count}')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'Backup failed: {error}', file=sys.stderr)
        sys.exit(1)

import io
import zipfile
from pathlib import Path
from fastapi import HTTPException, UploadFile

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024

async def read_price_upload(file: UploadFile) -> bytes:
    suffix = Path(file.filename or '').suffix.lower()
    if suffix not in {'.xlsx', '.xls', '.csv'}:
        raise HTTPException(415, 'Поддерживаются XLSX, XLS и CSV')
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES: raise HTTPException(413, 'Размер файла превышает 5 МБ')
    if not raw: raise HTTPException(422, 'Файл пуст')
    if suffix == '.xlsx':
        if not raw.startswith(b'PK\x03\x04'): raise HTTPException(415, 'Файл не является XLSX')
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                entries = z.infolist()
                if len(entries) > 2000 or sum(x.file_size for x in entries) > MAX_UNCOMPRESSED_BYTES:
                    raise HTTPException(413, 'Содержимое файла слишком велико')
                if 'xl/workbook.xml' not in z.namelist() or '[Content_Types].xml' not in z.namelist():
                    raise HTTPException(415, 'Некорректный XLSX')
                if any(x.flag_bits & 1 for x in entries): raise HTTPException(415, 'Зашифрованные XLSX не поддерживаются')
        except (zipfile.BadZipFile, OSError): raise HTTPException(415, 'Некорректный XLSX')
    elif suffix == '.xls':
        if not raw.startswith(bytes.fromhex('D0CF11E0A1B11AE1')): raise HTTPException(415, 'Файл не является XLS')
    else:
        if b'\x00' in raw: raise HTTPException(415, 'Файл не является текстовым CSV')
        try: text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            try: text = raw.decode('cp1251')
            except UnicodeDecodeError: raise HTTPException(415, 'Неподдерживаемая кодировка CSV')
        if sum(ord(c) < 32 and c not in '\r\n\t' for c in text) > max(2, len(text) // 100):
            raise HTTPException(415, 'Файл не является текстовым CSV')
    return raw

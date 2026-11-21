import re
from io import BytesIO, StringIO
from pathlib import Path
import pandas as pd

SYNONYMS = {'sku':['артикул','код товара','код','sku','article','id','номенклатурный номер','внешний код'],'name':['наименование','номенклатура','товар','название','позиция','name','title','продукт'],'price':['розничная цена','цена продажи','новая цена','цена с ндс','цена','price','стоимость','итого цена','розничная'],'old_price':['старая цена','цена до скидки','базовая цена','зачеркнутая цена','old_price','old price'],'barcode':['штрихкод','штрих-код','шк','barcode','ean13','ean-13','ean'],'unit':['ед. изм','единица измерения','единица','ед','unit']}

def clean_header(value): return re.sub(r'[^a-zа-яё0-9]+', ' ', str(value or '').lower()).strip()
def read_table(source, filename='price.csv'):
    raw = source if isinstance(source, bytes) else Path(source).read_bytes()
    if Path(filename).suffix.lower() == '.csv':
        try: text = raw.decode('utf-8-sig')
        except UnicodeDecodeError: text = raw.decode('cp1251')
        candidates = [';', ',', '\t']
        sample = text.splitlines()[:60]
        delimiter = max(candidates, key=lambda item: sum(line.count(item) for line in sample))
        import csv
        rows = list(csv.reader(StringIO(text), delimiter=delimiter))
        width = max((len(row) for row in rows), default=0)
        return pd.DataFrame([row + [''] * (width - len(row)) for row in rows])
    return pd.read_excel(BytesIO(raw), header=None, dtype=str, keep_default_na=False)
def detect_mapping(frame, override=None):
    best_row, best_score = 0, 0
    for idx in range(min(len(frame), 60)):
        values = [clean_header(v) for v in frame.iloc[idx].tolist()]
        score = sum(any(term == value or term in value for term in terms) for value in values for terms in SYNONYMS.values())
        if score > best_score: best_row, best_score = idx, score
    headers = [str(v).strip() for v in frame.iloc[best_row].tolist()]
    mapping = {}
    for key, terms in SYNONYMS.items():
        for header in headers:
            normalized = clean_header(header)
            if any(term == normalized or term in normalized for term in terms): mapping[key] = header; break
    if override: mapping.update({k:v for k,v in override.items() if v in headers})
    return best_row, headers, mapping
def parse_products(source, filename='price.csv', override=None, preview=False):
    frame = read_table(source, filename); header_row, headers, mapping = detect_mapping(frame, override)
    if preview:
        data = frame.iloc[header_row+1:].copy(); data.columns = headers
        return {'headers':headers,'detected_mapping':mapping,'needs_manual_mapping':not {'name','price'} <= mapping.keys(),'rows':data.head(5).fillna('').astype(str).to_dict('records')}
    if not {'name','price'} <= mapping.keys(): raise ValueError('Не удалось определить колонки «Наименование» и «Цена». Выберите их вручную.')
    data = frame.iloc[header_row+1:].copy(); data.columns = headers; result=[]
    def value(row,key): return str(row.get(mapping.get(key,''),'') or '').strip()
    for _, row in data.iterrows():
        name=value(row,'name')
        if not name: continue
        code=value(row,'sku') or value(row,'barcode') or clean_header(name).replace(' ','-')
        price=re.sub(r'[^0-9,.-]','',re.sub(r'руб\.?','',value(row,'price'),flags=re.I)).replace(',','.')
        if not price: continue
        item={'barcode':code,'name':name,'price':price,'unit':value(row,'unit') or 'шт.'}; old=re.sub(r'[^0-9,.-]','',re.sub(r'руб\.?','',value(row,'old_price'),flags=re.I)).replace(',','.')
        if old: item['old_price']=old
        result.append(item)
    return result

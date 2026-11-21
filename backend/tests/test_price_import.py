import io
from app.price_import import parse_products

def test_1c_report_headers_and_prices():
    raw = 'Отчёт 1С\n\nПериод: сегодня\n\nКод;Номенклатура;Розничная цена;Старая цена\nA-1;Молоко;1 290,00 руб.;1 490,00 руб.\n'.encode('cp1251')
    rows = parse_products(raw, 'report.csv')
    assert rows == [{'barcode':'A-1','name':'Молоко','price':'1290.00','unit':'шт.','old_price':'1490.00'}]

def test_mapping_override_and_barcode_fallback():
    raw = 'Товар;Розничная;ШК\nЧай;99,50;46001\n'.encode('utf-8')
    rows = parse_products(raw, 'price.csv', {'name':'Товар','price':'Розничная','barcode':'ШК'})
    assert rows[0]['barcode'] == '46001' and rows[0]['price'] == '99.50'

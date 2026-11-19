import asyncio
import logging
from decimal import Decimal, InvalidOperation
import httpx
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from .database import SessionLocal
from .models import Product, Tenant
from .product_sync import price_update_values

URL = "https://api.moysklad.ru/api/remap/1.2/entity/assortment"
log = logging.getLogger(__name__)


async def sync_moysklad(tenant_id: int, token: str) -> int:
    products = {}
    async with httpx.AsyncClient(timeout=30, headers={"Authorization": f"Bearer {token}", "Accept-Encoding": "gzip"}) as client:
        offset = 0
        while True:
            response = await client.get(URL, params={"limit": 1000, "offset": offset})
            response.raise_for_status()
            rows = response.json()["rows"]
            for row in rows:
                name = str(row.get("name") or "").strip()[:255]
                prices = row.get("salePrices") or []
                if not name or not prices:
                    continue
                try:
                    price = Decimal(str(prices[0]["value"])) / 100
                    if not price.is_finite() or price < 0 or price >= Decimal("100000000"):
                        continue
                except (KeyError, InvalidOperation, ValueError, TypeError):
                    continue
                for barcode in row.get("barcodes") or []:
                    for code in barcode.values():
                        code = str(code).strip()
                        if code and len(code) <= 128:
                            products[code] = {"tenant_id": tenant_id, "barcode": code, "name": name, "price": price, "old_price": None, "unit": "шт."}
            if len(rows) < 1000:
                break
            offset += len(rows)
    async with SessionLocal() as db:
        # A removed or changed credential must not import data from an old sync.
        tenant = await db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
        if tenant is None or tenant.moysklad_token != token:
            raise ValueError("Токен МойСклад изменился во время синхронизации")
        values = list(products.values())
        for start in range(0, len(values), 500):
            statement = insert(Product).values(values[start:start + 500])
            await db.execute(statement.on_conflict_do_update(index_elements=["tenant_id", "barcode"], set_=price_update_values(statement)))
        await db.commit()
    return len(products)


async def sync_loop():
    while True:
        await asyncio.sleep(900)
        async with SessionLocal() as db:
            tenants = (await db.execute(select(Tenant.id, Tenant.moysklad_token).where(Tenant.moysklad_token.is_not(None), Tenant.moysklad_token != ""))).all()
        for tenant_id, token in tenants:
            try:
                await sync_moysklad(tenant_id, token)
            except Exception:
                log.exception("Ошибка синхронизации МойСклад для магазина %s", tenant_id)

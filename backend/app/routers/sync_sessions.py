from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, delete, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_db
from ..models import Product, ProductSyncSession, ProductSyncItem, Tenant
from ..product_sync import price_update_values
from ..schemas import ProductInput
from ..security import api_tenant

router = APIRouter(prefix='/api/agent/sync-sessions', tags=['agent sync'])

class SessionStart(BaseModel):
    id: UUID
    expected_items: int = Field(ge=1, le=200000)
    expected_batches: int = Field(ge=1, le=400)

class SyncProduct(ProductInput):
    article: str = Field(min_length=1, max_length=128)
    barcode: str | None = Field(default=None, min_length=1, max_length=128)

class Batch(BaseModel):
    index: int = Field(ge=0)
    items: list[SyncProduct] = Field(min_length=1, max_length=500)

@router.post('')
async def start(data: SessionStart, tenant: Tenant = Depends(api_tenant), db: AsyncSession = Depends(get_db)):
    if data.expected_batches != (data.expected_items + 499) // 500:
        raise HTTPException(422, 'Неверное количество пакетов')
    if await db.get(ProductSyncSession, str(data.id)):
        raise HTTPException(409, 'Сессия уже существует')
    db.add(ProductSyncSession(id=str(data.id), tenant_id=tenant.id, expected_items=data.expected_items, expected_batches=data.expected_batches, replace=tenant.replace_missing_products, received_batches=0, received_items=0, status='pending'))
    await db.commit()
    return {'id': str(data.id)}

async def get_session(session_id: UUID, tenant: Tenant, db: AsyncSession):
    session = await db.scalar(select(ProductSyncSession).where(ProductSyncSession.id == str(session_id), ProductSyncSession.tenant_id == tenant.id).with_for_update())
    if session is None: raise HTTPException(404, 'Сессия не найдена')
    return session

@router.post('/{session_id}/batch')
async def batch(session_id: UUID, data: Batch, tenant: Tenant = Depends(api_tenant), db: AsyncSession = Depends(get_db)):
    session = await get_session(session_id, tenant, db)
    if session.status != 'pending' or data.index != session.received_batches: raise HTTPException(409, 'Неверный порядок пакетов')
    expected_size = min(500, session.expected_items - session.received_items)
    if len(data.items) != expected_size: raise HTTPException(422, 'Неверный размер пакета')
    articles = [p.article for p in data.items]
    if len(set(articles)) != len(articles): raise HTTPException(422, 'Повторяющиеся артикулы')
    if await db.scalar(select(ProductSyncItem.id).where(ProductSyncItem.session_id == session.id, ProductSyncItem.article.in_(articles)).limit(1)):
        raise HTTPException(422, 'Повторяющиеся артикулы')
    db.add_all([ProductSyncItem(session_id=session.id, **item.model_dump()) for item in data.items])
    session.received_batches += 1; session.received_items += len(data.items)
    await db.commit()
    return {'received': session.received_items}

@router.post('/{session_id}/finish')
async def finish(session_id: UUID, tenant: Tenant = Depends(api_tenant), db: AsyncSession = Depends(get_db)):
    await db.scalar(select(Tenant.id).where(Tenant.id == tenant.id).with_for_update())
    session = await get_session(session_id, tenant, db)
    if session.status == 'complete': return {'synced': session.received_items}
    if session.status != 'pending' or session.received_items != session.expected_items or session.received_batches != session.expected_batches:
        raise HTTPException(409, 'Переданы не все пакеты')
    rows = (await db.scalars(select(ProductSyncItem).where(ProductSyncItem.session_id == session.id).order_by(ProductSyncItem.id))).all()
    if len(rows) != session.expected_items: raise HTTPException(409, 'Неполная сессия')
    barcodes = [r.barcode for r in rows if r.barcode]
    if len(barcodes) != len(set(barcodes)): raise HTTPException(422, 'В файле повторяются штрихкоды')
    for pos in range(0, len(rows), 500):
        values = [{'tenant_id': tenant.id, 'article': r.article, 'barcode': r.barcode, 'name': r.name, 'price': r.price, 'old_price': r.old_price, 'unit': r.unit} for r in rows[pos:pos+500]]
        stmt = insert(Product).values(values)
        updates = price_update_values(stmt); updates.update(barcode=stmt.excluded.barcode, old_price=stmt.excluded.old_price)
        await db.execute(stmt.on_conflict_do_update(index_elements=['tenant_id','article'], set_=updates))
    if session.replace:
        await db.execute(delete(Product).where(Product.tenant_id == tenant.id, ~Product.article.in_(select(ProductSyncItem.article).where(ProductSyncItem.session_id == session.id))))
        await db.execute(delete(Product).where(Product.tenant_id == tenant.id, Product.article.is_(None)))
    session.status = 'complete'
    await db.execute(update(ProductSyncSession).where(ProductSyncSession.tenant_id == tenant.id, ProductSyncSession.id != session.id, ProductSyncSession.status == 'pending', ProductSyncSession.created_at <= session.created_at).values(status='superseded'))
    await db.execute(delete(ProductSyncItem).where(ProductSyncItem.session_id == session.id))
    await db.commit()
    return {'synced': session.received_items}

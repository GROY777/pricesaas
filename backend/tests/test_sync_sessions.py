import asyncio
import os
from uuid import uuid4
import pytest
from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://test:test@localhost/test')
os.environ.setdefault('JWT_SECRET', 'test-secret-at-least-thirty-two-characters-long')
from app.database import Base
from app.models import Tenant, Product
from app.routers import sync_sessions as sync

def test_staged_replace_incomplete_then_atomic_completion():
    async def run():
        engine=create_async_engine('sqlite+aiosqlite:///:memory:')
        async with engine.begin() as connection: await connection.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine,expire_on_commit=False)() as db:
            tenant=Tenant(email='sync@example.test',password_hash='x',company_name='S',api_key='s',replace_missing_products=True)
            db.add(tenant); await db.flush(); db.add(Product(tenant_id=tenant.id,article='old',barcode='old',name='Old',price=10,unit='pc')); await db.commit()
            sid=uuid4(); await sync.start(sync.SessionStart(id=sid,expected_items=501,expected_batches=2),tenant,db)
            products=[sync.SyncProduct(article=f'A{i}',barcode=None,name=f'Item {i}',price=10) for i in range(501)]
            await sync.batch(sid,sync.Batch(index=0,items=products[:500]),tenant,db)
            with pytest.raises(HTTPException) as err: await sync.finish(sid,tenant,db)
            assert err.value.status_code == 409
            assert await db.scalar(select(func.count()).select_from(Product).where(Product.tenant_id==tenant.id)) == 1
            assert (await db.scalar(select(Product).where(Product.tenant_id==tenant.id))).article == 'old'
            await sync.batch(sid,sync.Batch(index=1,items=products[500:]),tenant,db)
            assert (await sync.finish(sid,tenant,db))['synced']==501
            assert await db.scalar(select(func.count()).select_from(Product).where(Product.tenant_id==tenant.id)) == 501
            assert await db.scalar(select(Product.id).where(Product.tenant_id==tenant.id,Product.article=='old')) is None
            assert (await sync.finish(sid,tenant,db))['synced']==501
        await engine.dispose()
    asyncio.run(run())

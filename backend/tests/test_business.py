import asyncio
import os
from decimal import Decimal
from urllib.parse import urlparse, parse_qs
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://test:test@localhost/test')
os.environ.setdefault('JWT_SECRET', 'test-secret-at-least-thirty-two-characters-long')
os.environ.setdefault('BOT_TOKEN', '123456:test-token')
from app.database import Base
from app.models import Tenant, TenantEmployee, Product, PrintJob
from app.routers import employees, agent, changed_prices
from app.schemas import ProductInput
from app.bot import activate_employee
from app import security


def test_invitation_price_sync_and_print(tmp_path, monkeypatch):
    async def scenario():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(changed_prices, 'JOBS_DIR', tmp_path)
        monkeypatch.setattr(security, 'verify_telegram_init_data', lambda _: {'id': 876543})
        async with sessions() as db:
            tenant = Tenant(email='owner@example.test', password_hash='x', company_name='Store', api_key='key', plan='free', free_prints_used=0, free_prints_bonus=0, template_type='a4_3x4')
            db.add(tenant); await db.commit()
            result = await employees.invite(employees.Invite(full_name='Cashier'), tenant, db)
            token = parse_qs(urlparse(result['url']).query)['start'][0][7:]
            assert await activate_employee(db, token, 876543, 'cashier') == 'activated'
            assert await activate_employee(db, token, 987654, 'other') == 'invalid'
            assert (await security.telegram_user('signed', db)).tenant_id == tenant.id
            await employees.revoke(result['id'], tenant, db)
            with pytest.raises(HTTPException) as exc:
                await security.telegram_user('signed', db)
            assert exc.value.status_code == 403
            await agent.sync([ProductInput(barcode='123', name='Milk', price=Decimal('10'))], tenant, db)
            await agent.sync([ProductInput(barcode='123', name='Milk', price=Decimal('12'))], tenant, db)
            await agent.sync([ProductInput(barcode='123', name='Milk', price=Decimal('12'))], tenant, db)
            db.expire_all()
            product = await db.scalar(select(Product))
            assert product.previous_price == Decimal('10.00') and product.needs_reprint
            result = await changed_prices.print_changed((product.tenant_id, None), db)
            assert result['items_count'] == 1
            assert (tmp_path / (await db.scalar(select(PrintJob))).pdf_filename).is_file()
            db.expire_all()
            product = await db.scalar(select(Product))
            assert not product.needs_reprint
        await engine.dispose()
    asyncio.run(scenario())

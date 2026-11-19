import asyncio
import os
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://test:test@localhost/test')
os.environ.setdefault('JWT_SECRET', 'test-secret-at-least-thirty-two-characters-long')
os.environ.setdefault('BOT_TOKEN', '123456:test-token')
from app.database import Base, get_db
from app.models import Tenant, TenantEmployee, User
from app.routers import employees
from app.security import current_tenant
from app import bot


def test_api_and_start_handler(monkeypatch):
    async def scenario():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(bot, 'SessionLocal', sessions)
        async with sessions() as db:
            tenant = Tenant(email='test@example.com', password_hash='x', company_name='Store', api_key='test-key')
            db.add(tenant); await db.commit(); tenant_id = tenant.id
        app = FastAPI(); app.include_router(employees.router)
        async def test_db():
            async with sessions() as db:
                yield db
        async def test_tenant():
            async with sessions() as db:
                return await db.get(Tenant, tenant_id)
        app.dependency_overrides[get_db] = test_db
        app.dependency_overrides[current_tenant] = test_tenant
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            response = await client.post('/api/employees/invite', json={'full_name':'Cashier'})
            assert response.status_code == 201
            payload = parse_qs(urlparse(response.json()['url']).query)['start'][0]
        assert re.fullmatch(r'invite_[A-Za-z0-9_-]{22}', payload)
        async with sessions() as db:
            employee = await db.get(TenantEmployee, response.json()['id'])
            assert employee.invite_token == payload.removeprefix('invite_')
        message = SimpleNamespace(from_user=SimpleNamespace(id=7654321, username='cashier'), answer=AsyncMock())
        await bot.start(message, SimpleNamespace(args=payload))
        assert 'подключён' in message.answer.await_args.args[0]
        async with sessions() as db:
            employee = await db.get(TenantEmployee, response.json()['id'])
            assert employee.telegram_id == 7654321 and employee.activated_at is not None
        await bot.start(message, SimpleNamespace(args=payload))
        assert 'уже подключён' in message.answer.await_args.args[0]
        async with sessions() as db:
            db.add(User(tenant_id=tenant_id, telegram_id=7654322, full_name='Owner', role='owner'))
            await db.commit()
        owner = SimpleNamespace(from_user=SimpleNamespace(id=7654322, username='owner'), answer=AsyncMock())
        await bot.start(owner, SimpleNamespace(args=payload))
        assert 'уже подключён' in owner.answer.await_args.args[0]
        async with sessions() as db:
            employee = await db.get(TenantEmployee, response.json()['id']); employee.is_active = False; await db.commit()
        await bot.start(message, SimpleNamespace(args=payload))
        assert 'отозван' in message.answer.await_args.args[0]
        await engine.dispose()
    asyncio.run(scenario())

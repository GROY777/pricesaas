import asyncio
import os
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://test:test@localhost/test')
os.environ.setdefault('JWT_SECRET', 'test-secret-at-least-thirty-two-characters-long')
os.environ.setdefault('BOT_TOKEN', '123456:test-token')
import httpx
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.database import Base, get_db
from app.models import Tenant, Payment, PriceTemplate, TenantTemplate
from app.routers import payments
from app.security import current_tenant

def test_payment_creation_and_verified_idempotent_webhook(monkeypatch):
    async def scenario():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db:
            tenant = Tenant(email='owner@example.test', password_hash='x', company_name='Store', api_key='x')
            db.add(tenant); await db.commit(); tenant_id = tenant.id
        settings = SimpleNamespace(yookassa_shop_id='shop', yookassa_secret_key='secret', yookassa_vat_code=1, yookassa_return_url='https://example.test/return', bot_token='')
        monkeypatch.setattr(payments, 'get_settings', lambda: settings)
        calls = {}; payment_id = str(uuid4())
        class FakeGateway:
            def __init__(self, *args, **kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def post(self, url, **kwargs):
                calls['payload'] = kwargs['json']; calls['headers'] = kwargs['headers']
                return httpx.Response(200, json={'id':payment_id, 'confirmation':{'confirmation_url':'https://yookassa.ru/pay'}}, request=httpx.Request('POST',url))
            async def get(self, url, **kwargs):
                p = calls['payload']
                return httpx.Response(200, json={'id':payment_id, 'status':calls.get('remote_status', 'succeeded'), 'paid':calls.get('remote_status', 'succeeded') == 'succeeded', 'amount':p['amount'], 'metadata':p['metadata']}, request=httpx.Request('GET',url))
        monkeypatch.setattr(payments.httpx, 'AsyncClient', FakeGateway)
        app = FastAPI(); app.include_router(payments.router)
        async def session():
            async with sessions() as db: yield db
        async def identity():
            async with sessions() as db: return await db.get(Tenant, tenant_id)
        app.dependency_overrides[get_db] = session; app.dependency_overrides[current_tenant] = identity
        transport = httpx.ASGITransport(app=app)
        # Gateway replacement shares the httpx module; retain the real client explicitly.
        monkeypatch.undo()
        real_client = httpx.AsyncClient
        monkeypatch.setattr(payments, 'get_settings', lambda: settings)
        monkeypatch.setattr(payments, 'SessionLocal', sessions)
        monkeypatch.setattr(payments, 'httpx', SimpleNamespace(AsyncClient=FakeGateway, HTTPError=httpx.HTTPError))
        async with real_client(transport=transport, base_url='http://test') as client:
            response = await client.post('/api/payments/create', json={'product_type':'pro_3m'})
            assert response.status_code == 200
            assert calls['payload']['amount']['value'] == '2490.00'
            assert calls['payload']['receipt']['items'][0]['vat_code'] == 1
            event = {'event':'payment.succeeded','object':{'id':payment_id}}
            calls['payload']['metadata']['tenant_id'] = 'wrong'
            assert (await client.post('/api/payments/yookassa/webhook', json=event)).status_code == 400
            calls['payload']['metadata']['tenant_id'] = str(tenant_id)
            sync_response = await client.post('/api/payments/sync')
            assert sync_response.status_code == 200 and sync_response.json()['succeeded'] == 1
            async with sessions() as db:
                tenant = await db.get(Tenant, tenant_id); until = tenant.subscription_until
                assert tenant.plan == 'pro' and 89 <= (until.replace(tzinfo=None) - __import__('datetime').datetime.now(__import__('datetime').timezone.utc).replace(tzinfo=None)).days <= 90
            sync_response = await client.post('/api/payments/sync')
            assert sync_response.json()['succeeded'] == 0
            assert (await client.post('/api/payments/yookassa/webhook', json=event)).status_code == 200
            async with sessions() as db:
                assert (await db.get(Tenant, tenant_id)).subscription_until == until
                assert (await db.scalar(select(Payment))).status == 'succeeded'
            payment_id = str(uuid4())
            assert (await client.post('/api/payments/create', json={'product_type':'pro_1m'})).status_code == 200
            event['object']['id'] = payment_id
            assert (await client.post('/api/payments/yookassa/webhook', json=event)).status_code == 200
            async with sessions() as db:
                assert ((await db.get(Tenant, tenant_id)).subscription_until - until).days == 30
            async with sessions() as db:
                db.add(PriceTemplate(slug='paid-test', name='Template', description='', format_type='a4', price_rub=290, preview_css_config='{}', is_active=True))
                await db.commit()
            payment_id = str(uuid4())
            response = await client.post('/api/payments/create', json={'product_type':'template', 'template_id':1})
            assert response.status_code == 200 and calls['payload']['amount']['value'] == '290.00'
            event['object']['id'] = payment_id
            assert (await client.post('/api/payments/yookassa/webhook', json=event)).status_code == 200
            assert (await client.post('/api/payments/yookassa/webhook', json=event)).status_code == 200
            async with sessions() as db:
                assert (await db.get(TenantTemplate, (tenant_id, 1))).source == 'purchase'
            payment_id = str(uuid4())
            assert (await client.post('/api/payments/create', json={'product_type':'pro_1m'})).status_code == 200
            calls['remote_status'] = 'canceled'
            assert (await client.post('/api/payments/sync')).json()['canceled'] == 1
            async with sessions() as db:
                canceled = await db.scalar(select(Payment).where(Payment.yookassa_payment_id == payment_id))
                assert canceled.status == 'canceled'
        await engine.dispose()
    asyncio.run(scenario())

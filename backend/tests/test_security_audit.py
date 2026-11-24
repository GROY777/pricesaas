import asyncio
import base64
import hashlib
import hmac
import io
import os
import time
import zipfile
import pytest
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
os.environ.setdefault('DATABASE_URL','postgresql+asyncpg://test:test@localhost/test')
os.environ.setdefault('JWT_SECRET','test-secret-at-least-thirty-two-characters-long')
from app.database import Base, get_db
from app.models import Tenant, Product
from app.routers.auth import router
from app.routers.catalog import router as catalog_router
from app.routers.admin import router as admin_router
from app.security import password_hasher, get_settings
from app.upload_security import read_price_upload, MAX_UPLOAD_BYTES

def test_http_only_cookie_and_csrf(monkeypatch):
    raw_key = b'0123456789abcdefghij'
    monkeypatch.setattr(get_settings(), 'admin_email', 'owner@example.com')
    monkeypatch.setattr(get_settings(), 'admin_totp_secret', base64.b32encode(raw_key).decode())
    engine=create_async_engine('sqlite+aiosqlite:///:memory:',poolclass=StaticPool)
    sessions=async_sessionmaker(engine,expire_on_commit=False)
    async def setup():
        async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
        async with sessions() as db:
            db.add(Tenant(email='owner@example.com',password_hash=password_hasher.hash('strong password'),company_name='Store',api_key='key'))
            db.add(Tenant(email='other@example.com',password_hash=password_hasher.hash('strong password'),company_name='Other',api_key='other-key'))
            await db.commit()
            other=await db.get(Tenant,2)
            db.add(Product(tenant_id=other.id,article='foreign',barcode='987',name='Foreign',price=10,unit='pc'))
            await db.commit()
    asyncio.run(setup())
    async def db_override():
        async with sessions() as db: yield db
    app=FastAPI(); app.include_router(router); app.include_router(catalog_router); app.include_router(admin_router); app.dependency_overrides[get_db]=db_override
    with TestClient(app,base_url='https://cardifyrbx.shop') as client:
        r=client.post('/api/auth/login',json={'email':'owner@example.com','password':'strong password'},headers={'Origin':'https://evil.example'})
        assert r.status_code==403
        r=client.post('/api/auth/login',json={'email':'owner@example.com','password':'strong password'},headers={'Origin':'https://cardifyrbx.shop'})
        assert r.status_code==200 and 'access_token' not in r.json()
        cookies=r.headers.get_list('set-cookie'); assert any('__Host-pricesnap_session=' in c and 'HttpOnly' in c and 'Secure' in c and 'SameSite=lax' in c for c in cookies)
        assert client.get('/api/me').status_code==200
        assert client.get('/api/admin/stats').status_code==403
        digest=hmac.new(raw_key,(int(time.time())//30).to_bytes(8,'big'),hashlib.sha1).digest(); offset=digest[-1]&15
        code=f"{(int.from_bytes(digest[offset:offset+4],'big') & 0x7fffffff)%1000000:06d}"
        assert client.get('/api/admin/stats',headers={'X-Admin-OTP':code}).status_code==200
        assert client.patch('/api/me/settings',json={'company_name':'No'}).status_code==403
        csrf=client.cookies.get('__Host-pricesnap_csrf')
        assert client.patch('/api/me/settings',json={'company_name':'Yes'},headers={'X-CSRF-Token':csrf}).status_code==200
        payload={'name':'<img src=x onerror=alert(1)>','article':'test','barcode':'123','price':'10','unit':'pc'}
        assert client.patch('/api/catalog/1',json=payload,headers={'X-CSRF-Token':csrf}).status_code==404
        created=client.post('/api/catalog',json=payload,headers={'X-CSRF-Token':csrf})
        assert created.status_code==200 and created.json()['name']==payload['name']
        assert client.get('/api/catalog',params={'q':"' OR 1=1 --"}).json()['total']==0
        assert client.post('/api/auth/logout',headers={'X-CSRF-Token':csrf}).status_code==200
        assert client.get('/api/me').status_code==401
    asyncio.run(engine.dispose())

def test_upload_rejects_fake_and_oversized():
    async def run():
        for name, data, status in [('test.xlsx', b'not a zip',415),('test.csv',b'\x00binary',415),('test.csv',b'a'*(MAX_UPLOAD_BYTES+1),413)]:
            with pytest.raises(HTTPException) as exc: await read_price_upload(UploadFile(filename=name,file=io.BytesIO(data)))
            assert exc.value.status_code==status
        assert await read_price_upload(UploadFile(filename='p.csv',file=io.BytesIO(b'name;price\nA;12\n')))
    asyncio.run(run())

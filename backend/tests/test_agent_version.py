import os
os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://test:test@localhost/test')
os.environ.setdefault('JWT_SECRET', 'test-secret-at-least-thirty-two-characters-long')
os.environ.setdefault('BOT_TOKEN', '123456:test-token')
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.routers.agent import router


def test_public_agent_version():
    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).get('/api/agent/version')
    assert response.status_code == 200
    assert response.json() == {
        'version': '2.1.3',
        'download_url': 'https://cardifyrbx.shop/releases/PriceAgent_Setup.exe',
        'release_notes': 'Раздельные артикулы и штрихкоды, безопасная синхронизация каталога',
        'mandatory': False,
    }

import asyncio
import json
import secrets
from contextlib import asynccontextmanager, suppress
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pathlib import Path
from sqlalchemy import text
from .database import Base, engine
from . import models
from .models import PriceTemplate, TenantTemplate
from .routers import auth, agent, scanner, billing, admin, templates, employees, changed_prices
from .config import get_settings
from .bot import run_bot
from .moysklad import sync_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.execute(text("ALTER TABLE tenant_employees ALTER COLUMN is_active SET DEFAULT TRUE"))
        await connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_active_employee_telegram ON tenant_employees (telegram_id) WHERE is_active AND telegram_id IS NOT NULL"))
        await connection.execute(text("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS invite_token VARCHAR(64)"))
        missing = (await connection.execute(text("SELECT id FROM tenants WHERE invite_token IS NULL"))).scalars().all()
        for tenant_id in missing:
            await connection.execute(text("UPDATE tenants SET invite_token = :token WHERE id = :id"), {"token": secrets.token_urlsafe(24), "id": tenant_id})
        await connection.execute(text("ALTER TABLE tenants ALTER COLUMN invite_token SET NOT NULL"))
        await connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_tenants_invite_token ON tenants (invite_token)"))
        await connection.execute(text("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS moysklad_token VARCHAR(1024)"))
        await connection.execute(text("ALTER TABLE print_jobs ADD COLUMN IF NOT EXISTS locked_at TIMESTAMPTZ"))
        await connection.execute(text("ALTER TABLE print_jobs ADD COLUMN IF NOT EXISTS lock_token VARCHAR(64)"))
        await connection.execute(text("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS free_prints_bonus INTEGER NOT NULL DEFAULT 0"))
        await connection.execute(text("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE"))
        await connection.execute(text("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS registered_ip VARCHAR(64)"))
        await connection.execute(text("ALTER TABLE products ADD COLUMN IF NOT EXISTS previous_price NUMERIC(10,2)"))
        await connection.execute(text("ALTER TABLE products ADD COLUMN IF NOT EXISTS price_changed_at TIMESTAMPTZ"))
        await connection.execute(text("ALTER TABLE products ADD COLUMN IF NOT EXISTS needs_reprint BOOLEAN NOT NULL DEFAULT FALSE"))
        defaults = [('classic-a4', 'Классика Ритейл (А4)', 'Строгий белый ценник', 'a4', 0, {'background': '#ffffff', 'header': '#475569', 'accent': '#475569', 'price': '#0f172a', 'border': 'solid', 'layout': 'classic'}), ('promo-a4', 'Яркая Акция / Скидка (А4)', 'Жёлтый ценник для акции', 'a4', 0, {'background': '#fef08a', 'header': '#dc2626', 'accent': '#dc2626', 'price': '#dc2626', 'border': 'none', 'layout': 'promo', 'badge': 'АКЦИЯ'}), ('boutique-a4', 'Бутик и Косметика Минимал (А4)', 'Минимализм с двойной рамкой', 'a4', 290, {'background': '#ffffff', 'header': '#111111', 'accent': '#111111', 'price': '#111111', 'border': 'double', 'layout': 'boutique'}), ('farmer-a4', 'Фермерская Лавка / Эко (А4)', 'Тёплый эко-дизайн', 'a4', 390, {'background': '#fef3c7', 'header': '#14532d', 'accent': '#15803d', 'price': '#15803d', 'border': 'dashed', 'layout': 'eco'}), ('premium-thermal', 'Термо Премиум (58×40 мм)', 'Контрастный термошаблон', 'thermo', 490, {'background': '#ffffff', 'header': '#000000', 'accent': '#000000', 'price': '#000000', 'border': 'solid', 'layout': 'thermal'}), ('promo-thermal', 'Термо Скидка / Хит (58×40 мм)', 'Термошаблон с акцентом', 'thermo', 290, {'background': '#ffffff', 'header': '#111111', 'accent': '#b91c1c', 'price': '#b91c1c', 'border': 'solid', 'layout': 'thermal-promo', 'badge': 'ХИТ'})]
        for slug, name, description, format_type, price, config in defaults:
            await connection.execute(text("INSERT INTO price_templates (slug,name,description,format_type,price_rub,preview_css_config,is_active) VALUES (:slug,:name,:description,:format,:price,:config,true) ON CONFLICT (slug) DO UPDATE SET name=EXCLUDED.name, description=EXCLUDED.description, format_type=EXCLUDED.format_type, price_rub=EXCLUDED.price_rub, preview_css_config=EXCLUDED.preview_css_config"), {"slug":slug,"name":name,"description":description,"format":format_type,"price":price,"config":json.dumps(config,ensure_ascii=False)})
        await connection.execute(text("CREATE TABLE IF NOT EXISTS schema_markers (name VARCHAR(128) PRIMARY KEY)"))
        marker = await connection.execute(text("INSERT INTO schema_markers(name) VALUES ('free_templates_v1') ON CONFLICT DO NOTHING RETURNING name"))
        if marker.scalar():
            await connection.execute(text("INSERT INTO tenant_templates (tenant_id,template_id,source) SELECT t.id,p.id,'free' FROM tenants t CROSS JOIN price_templates p WHERE p.price_rub=0 AND p.slug NOT LIKE 'custom-%' ON CONFLICT DO NOTHING"))

    task = asyncio.create_task(run_bot()) if get_settings().bot_token else None
    sync_task = asyncio.create_task(sync_loop())
    try:
        yield
    finally:
        sync_task.cancel()
        with suppress(asyncio.CancelledError):
            await sync_task
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await engine.dispose()


app = FastAPI(title="PriceSnap", lifespan=lifespan)

@app.get("/releases/PriceAgent_Setup.exe", include_in_schema=False)
async def public_agent_release():
    return FileResponse(Path("/app/releases/PriceAgent_Setup.exe"), filename="PriceAgent_Setup.exe", media_type="application/octet-stream")

app.include_router(auth.router)
app.include_router(agent.router)
app.include_router(employees.router)
app.include_router(changed_prices.router)
app.include_router(scanner.router)
app.include_router(billing.router)
app.include_router(admin.router)
app.include_router(templates.router)

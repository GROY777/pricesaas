import asyncio
import secrets
from contextlib import asynccontextmanager, suppress
from fastapi import FastAPI
from sqlalchemy import text
from .database import Base, engine
from . import models
from .models import PriceTemplate, TenantTemplate
from .routers import auth, agent, scanner, billing, admin, templates
from .config import get_settings
from .bot import run_bot
from .moysklad import sync_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
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
        defaults = [
            ("classic-a4", "Классика Retail A4", "Универсальный шаблон", "a4", 0),
            ("promo-a4", "Яркая Акция / Скидка", "Акцентный шаблон для акций", "a4", 0),
            ("boutique-a4", "Бутик и Косметика Минимал", "Минималистичный дизайн", "a4", 290),
            ("farmer-a4", "Фермерская Лавка / Крафт", "Тёплый стиль для фермерских товаров", "a4", 390),
            ("premium-thermal", "Термо Премиум 58×40", "Премиальный термошаблон", "thermo", 490),
            ("promo-thermal", "Термо Акция 58×40", "Термошаблон для акций", "thermo", 290),
        ]
        for slug, name, description, format_type, price in defaults:
            await connection.execute(text("INSERT INTO price_templates (slug,name,description,format_type,price_rub,preview_css_config,is_active) VALUES (:slug,:name,:description,:format,:price,'{}',true) ON CONFLICT (slug) DO NOTHING"), {"slug":slug,"name":name,"description":description,"format":format_type,"price":price})
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
app.include_router(auth.router)
app.include_router(agent.router)
app.include_router(scanner.router)
app.include_router(billing.router)
app.include_router(admin.router)
app.include_router(templates.router)

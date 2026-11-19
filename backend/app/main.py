import asyncio
import secrets
from contextlib import asynccontextmanager, suppress
from fastapi import FastAPI
from sqlalchemy import text
from .database import Base, engine
from . import models
from .routers import auth, agent, scanner, billing
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

from datetime import datetime, time, timezone, timedelta
from pathlib import Path
import secrets
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from ..config import get_settings
from ..database import get_db
from ..models import PrintJob, Tenant, PriceTemplate, TenantTemplate
from ..schemas import LoginRequest, RegisterRequest, SettingsRequest, TokenResponse
from ..security import create_token, current_tenant, new_api_key, password_hasher
from ..moysklad import sync_moysklad
import httpx

router = APIRouter(prefix="/api", tags=["auth"])


@router.post("/auth/register", response_model=TokenResponse, status_code=201)
async def register(data: RegisterRequest, request: Request, db: AsyncSession = Depends(get_db)):
    if not data.accepted_terms:
        raise HTTPException(422, "Примите Пользовательское соглашение и Политику конфиденциальности")
    # Limit free-account farming from one address while retaining paid signup access.
    # Nginx overwrites X-Real-IP and X-Forwarded-For; backend is not published externally.
    request_ip = request.headers.get("x-real-ip") or (request.client.host if request.client else None)
    if request_ip:
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        recent = await db.scalar(select(func.count(Tenant.id)).where(Tenant.registered_ip == request_ip, Tenant.created_at >= since)) or 0
        exhausted = await db.scalar(select(func.count(Tenant.id)).where(Tenant.registered_ip == request_ip, Tenant.free_prints_used >= 30, Tenant.plan == "free")) or 0
        if recent >= 2:
            raise HTTPException(429, "С этого IP уже создано максимальное число бесплатных аккаунтов за 24 часа")
    tenant = Tenant(email=str(data.email).lower(), password_hash=password_hasher.hash(data.password), company_name=data.company_name.strip(), api_key=new_api_key(), registered_ip=request_ip)
    if request_ip and exhausted:
        tenant.free_prints_used = 30
    if not tenant.company_name:
        raise HTTPException(422, "Укажите название компании")
    db.add(tenant)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Этот email уже зарегистрирован")
    await db.refresh(tenant)
    for template in (await db.scalars(select(PriceTemplate).where(PriceTemplate.price_rub == 0, PriceTemplate.is_active.is_(True), ~PriceTemplate.slug.startswith("custom-")))).all():
        db.add(TenantTemplate(tenant_id=tenant.id, template_id=template.id, source="free"))
    await db.commit()
    return TokenResponse(access_token=create_token(tenant.id))


@router.post("/auth/login", response_model=TokenResponse)
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)):
    tenant = await db.scalar(select(Tenant).where(Tenant.email == str(data.email).lower()))
    if tenant is None or not password_hasher.verify(data.password, tenant.password_hash):
        raise HTTPException(401, "Неверный email или пароль")
    if not tenant.is_active:
        raise HTTPException(403, "Store blocked")
    return TokenResponse(access_token=create_token(tenant.id))


@router.get("/me")
async def me(tenant: Tenant = Depends(current_tenant), db: AsyncSession = Depends(get_db)):
    start = datetime.combine(datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc)
    printed = await db.scalar(select(func.coalesce(func.sum(PrintJob.items_count), 0)).where(PrintJob.tenant_id == tenant.id, PrintJob.status == "printed", PrintJob.created_at >= start))
    return {"id": tenant.id, "email": tenant.email, "company_name": tenant.company_name, "api_key": tenant.api_key, "plan": tenant.plan, "subscription_until": tenant.subscription_until, "free_prints_used": tenant.free_prints_used, "free_prints_bonus": tenant.free_prints_bonus, "template_type": tenant.template_type, "printed_today": printed, "moysklad_configured": bool(tenant.moysklad_token), "deep_link": f"https://t.me/{get_settings().bot_username}?start={tenant.invite_token}"}


@router.patch("/me/settings")
async def settings(data: SettingsRequest, tenant: Tenant = Depends(current_tenant), db: AsyncSession = Depends(get_db)):
    if data.company_name is not None:
        company_name = data.company_name.strip()
        if not company_name:
            raise HTTPException(422, "Укажите название магазина")
        tenant.company_name = company_name
    if data.column_mapping is not None:
        tenant.column_mapping = data.column_mapping
    if data.template_type is not None:
        owned = await db.scalar(select(PriceTemplate.id).join(TenantTemplate, TenantTemplate.template_id == PriceTemplate.id).where(TenantTemplate.tenant_id == tenant.id, PriceTemplate.slug == data.template_type, PriceTemplate.is_active.is_(True)))
        if owned is None and data.template_type not in ("a4_3x4", "a4_promo", "thermo_58x40"):
            raise HTTPException(403, "Шаблон недоступен этому магазину")
        tenant.template_type = data.template_type
    if data.regenerate_api_key:
        tenant.api_key = new_api_key()
    if data.regenerate_invite_token:
        tenant.invite_token = secrets.token_urlsafe(24)
    if "moysklad_token" in data.model_fields_set:
        tenant.moysklad_token = data.moysklad_token.strip() if data.moysklad_token else None
    await db.commit()
    return {"template_type": tenant.template_type, "api_key": tenant.api_key, "company_name": tenant.company_name}


@router.post("/me/sync-moysklad")
async def sync_store(tenant: Tenant = Depends(current_tenant)):
    if not tenant.moysklad_token:
        raise HTTPException(400, "Укажите токен МойСклад в настройках")
    try:
        count = await sync_moysklad(tenant.id, tenant.moysklad_token)
    except (httpx.HTTPError, ValueError, KeyError):
        raise HTTPException(502, "Не удалось синхронизировать МойСклад. Проверьте токен и повторите попытку")
    return {"synced": count}


@router.get("/download/agent")
async def download_agent(tenant: Tenant = Depends(current_tenant)):
    path = Path("/app/releases/PriceAgent_Setup.exe")
    if not path.is_file():
        raise HTTPException(404, "Программа для Windows пока недоступна")
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")

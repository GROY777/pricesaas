from datetime import datetime, timedelta, timezone, time
from decimal import Decimal
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_db
from ..models import Payment, PrintJob, Product, Tenant, PriceTemplate, TenantTemplate
from ..security import get_current_admin

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(get_current_admin)])

class SubscriptionUpdate(BaseModel):
    plan: Literal["free", "pro"] = "pro"
    days: int = Field(default=0, ge=0, le=3650)
    bonus_prints: int = Field(default=0, ge=0, le=100000)

class BlockUpdate(BaseModel):
    is_active: bool

@router.get("/stats")
async def stats(db: AsyncSession = Depends(get_db)):
    today = datetime.combine(datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc)
    total = await db.scalar(select(func.count(Tenant.id))) or 0
    pro = await db.scalar(select(func.count(Tenant.id)).where(Tenant.plan == "pro", Tenant.subscription_until > datetime.now(timezone.utc))) or 0
    printed_total = await db.scalar(select(func.coalesce(func.sum(PrintJob.items_count), 0)).where(PrintJob.status == "printed")) or 0
    printed_today = await db.scalar(select(func.coalesce(func.sum(PrintJob.items_count), 0)).where(PrintJob.status == "printed", PrintJob.created_at >= today)) or 0
    revenue = await db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.status == "succeeded")) or Decimal("0")
    return {"tenants": total, "active_pro": pro, "printed_total": int(printed_total), "printed_today": int(printed_today), "revenue": float(revenue)}

@router.get("/tenants")
async def tenants(search: str = "", plan: str = "all", db: AsyncSession = Depends(get_db)):
    query = select(Tenant).order_by(Tenant.created_at.desc())
    if search:
        term = f"%{search.strip()}%"
        conditions = [Tenant.company_name.ilike(term), Tenant.email.ilike(term)]
        if search.isdigit(): conditions.append(Tenant.id == int(search))
        query = query.where(or_(*conditions))
    if plan == "pro": query = query.where(Tenant.plan == "pro", Tenant.subscription_until > datetime.now(timezone.utc))
    elif plan == "free": query = query.where(or_(Tenant.plan != "pro", Tenant.subscription_until <= datetime.now(timezone.utc), Tenant.subscription_until.is_(None)))
    elif plan == "blocked": query = query.where(Tenant.is_active.is_(False))
    rows = (await db.scalars(query)).all()
    result = []
    for tenant in rows:
        products = await db.scalar(select(func.count(Product.id)).where(Product.tenant_id == tenant.id)) or 0
        printed = await db.scalar(select(func.coalesce(func.sum(PrintJob.items_count), 0)).where(PrintJob.tenant_id == tenant.id, PrintJob.status == "printed")) or 0
        result.append({"id": tenant.id, "company_name": tenant.company_name, "email": tenant.email, "created_at": tenant.created_at, "plan": tenant.plan, "subscription_expires_at": tenant.subscription_until, "products": int(products), "printed": int(printed), "free_prints_remaining": max(0, 30 + tenant.free_prints_bonus - tenant.free_prints_used), "is_active": tenant.is_active})
    return result

@router.post("/tenants/{tenant_id}/subscription")
async def subscription(tenant_id: int, data: SubscriptionUpdate, db: AsyncSession = Depends(get_db)):
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None: raise HTTPException(404, "Магазин не найден")
    if data.plan == "free":
        tenant.plan = "free"; tenant.subscription_until = None
    elif data.days:
        now = datetime.now(timezone.utc)
        base = tenant.subscription_until if tenant.subscription_until and tenant.subscription_until > now else now
        tenant.subscription_until = base + timedelta(days=data.days)
        tenant.plan = "pro"
    if data.bonus_prints: tenant.free_prints_bonus = max(0, tenant.free_prints_bonus + data.bonus_prints)
    await db.commit()
    return {"ok": True}

@router.post("/tenants/{tenant_id}/toggle-block")
async def toggle_block(tenant_id: int, data: BlockUpdate | None = None, db: AsyncSession = Depends(get_db)):
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None: raise HTTPException(404, "Магазин не найден")
    tenant.is_active = data.is_active if data else not tenant.is_active
    await db.commit()
    return {"is_active": tenant.is_active}

@router.get("/tenants/{tenant_id}/templates")
async def tenant_templates(tenant_id: int, db: AsyncSession = Depends(get_db)):
    owned = {x for x in (await db.scalars(select(TenantTemplate.template_id).where(TenantTemplate.tenant_id == tenant_id))).all()}
    rows = (await db.scalars(select(PriceTemplate).where(PriceTemplate.is_active.is_(True), PriceTemplate.price_rub > 0))).all()
    return [{"id": x.id, "name": x.name, "price_rub": x.price_rub, "is_owned": x.id in owned} for x in rows]

@router.post("/tenants/{tenant_id}/templates/{template_id}")
async def grant_template(tenant_id: int, template_id: int, db: AsyncSession = Depends(get_db)):
    if await db.get(Tenant, tenant_id) is None or await db.get(PriceTemplate, template_id) is None: raise HTTPException(404, "Не найдено")
    row = await db.scalar(select(TenantTemplate).where(TenantTemplate.tenant_id == tenant_id, TenantTemplate.template_id == template_id))
    if row: await db.delete(row)
    else: db.add(TenantTemplate(tenant_id=tenant_id, template_id=template_id, source="admin"))
    await db.commit(); return {"owned": not bool(row)}

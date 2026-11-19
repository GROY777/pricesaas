from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_db
from ..models import PriceTemplate, Tenant, TenantTemplate
from ..security import current_tenant

router = APIRouter(prefix="/api/templates", tags=["templates"])

@router.get("")
async def list_templates(tenant: Tenant = Depends(current_tenant), db: AsyncSession = Depends(get_db)):
    owned = {x for x in (await db.scalars(select(TenantTemplate.template_id).where(TenantTemplate.tenant_id == tenant.id))).all()}
    rows = (await db.scalars(select(PriceTemplate).where(PriceTemplate.is_active.is_(True)).order_by(PriceTemplate.price_rub, PriceTemplate.id))).all()
    return [{"id": x.id, "slug": x.slug, "name": x.name, "description": x.description, "format_type": x.format_type, "price_rub": x.price_rub, "preview_css_config": x.preview_css_config, "is_owned": x.id in owned} for x in rows]

@router.post("/{template_id}/select")
async def select_template(template_id: int, tenant: Tenant = Depends(current_tenant), db: AsyncSession = Depends(get_db)):
    row = await db.scalar(select(TenantTemplate).where(TenantTemplate.tenant_id == tenant.id, TenantTemplate.template_id == template_id))
    template = await db.get(PriceTemplate, template_id)
    if template is None or not row: raise HTTPException(403, "Шаблон не приобретён")
    tenant.template_type = template.slug
    await db.commit()
    return {"template_type": tenant.template_type}

@router.post("/{template_id}/buy")
async def buy_template(template_id: int, tenant: Tenant = Depends(current_tenant), db: AsyncSession = Depends(get_db)):
    template = await db.get(PriceTemplate, template_id)
    if template is None or not template.is_active: raise HTTPException(404, "Шаблон не найден")
    exists = await db.scalar(select(TenantTemplate).where(TenantTemplate.tenant_id == tenant.id, TenantTemplate.template_id == template_id))
    if exists: return {"owned": True, "template_type": template.slug}
    if template.price_rub: raise HTTPException(402, "Покупка шаблонов будет доступна после подключения платежей")
    db.add(TenantTemplate(tenant_id=tenant.id, template_id=template.id, source="free")); await db.commit()
    return {"owned": True, "template_type": template.slug}

@router.post("/custom")
async def custom_template(config: dict, tenant: Tenant = Depends(current_tenant), db: AsyncSession = Depends(get_db)):
    name = str(config.get("name", "Мой шаблон"))[:255]
    slug = f"custom-{tenant.id}-{abs(hash(name)) % 1000000}"
    template = PriceTemplate(slug=slug, name=name, description="Пользовательский шаблон", format_type=str(config.get("format_type", "a4")), price_rub=0, preview_css_config=str(config.get("config", {})), is_active=True)
    db.add(template); await db.flush(); db.add(TenantTemplate(tenant_id=tenant.id, template_id=template.id, source="admin")); tenant.template_type = slug; await db.commit()
    return {"id": template.id, "template_type": slug}

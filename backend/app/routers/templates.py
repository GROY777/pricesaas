import json
import secrets
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_db
from ..models import PriceTemplate, Tenant, TenantTemplate
from ..security import current_tenant

router = APIRouter(prefix="/api/templates", tags=["templates"])

class TemplateConfig(BaseModel):
    header: str = Field(default="#1e293b", pattern=r"^#[0-9a-fA-F]{6}$")
    accent: str = Field(default="#2563eb", pattern=r"^#[0-9a-fA-F]{6}$")
    background: str = Field(default="#ffffff", pattern=r"^#[0-9a-fA-F]{6}$")
    price: str = Field(default="#0f172a", pattern=r"^#[0-9a-fA-F]{6}$")
    border: Literal["none", "solid", "dashed"] = "solid"
    show_company: bool = True
    show_old_price: bool = True
    show_barcode: bool = True
    show_date: bool = True
    show_unit: bool = True

class CustomTemplate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    format_type: Literal["a4", "thermo"] = "a4"
    config: TemplateConfig

@router.get("")
async def list_templates(tenant: Tenant = Depends(current_tenant), db: AsyncSession = Depends(get_db)):
    owned = set((await db.scalars(select(TenantTemplate.template_id).where(TenantTemplate.tenant_id == tenant.id))).all())
    rows = (await db.scalars(select(PriceTemplate).where(PriceTemplate.is_active.is_(True)).order_by(PriceTemplate.price_rub, PriceTemplate.id))).all()
    return [{"id": x.id, "slug": x.slug, "name": x.name, "description": x.description, "format_type": x.format_type, "price_rub": x.price_rub, "preview_css_config": json.loads(x.preview_css_config or "{}"), "is_owned": x.id in owned} for x in rows if not x.slug.startswith("custom-") or x.id in owned]

@router.post("/{template_id}/select")
async def select_template(template_id: int, tenant: Tenant = Depends(current_tenant), db: AsyncSession = Depends(get_db)):
    row = await db.get(TenantTemplate, (tenant.id, template_id))
    template = await db.get(PriceTemplate, template_id)
    if template is None or not template.is_active or not row: raise HTTPException(403, "Шаблон недоступен")
    tenant.template_type = template.slug
    await db.commit()
    return {"template_type": tenant.template_type}

@router.post("/custom")
async def custom_template(data: CustomTemplate, tenant: Tenant = Depends(current_tenant), db: AsyncSession = Depends(get_db)):
    template = PriceTemplate(slug="custom-" + secrets.token_hex(10), name=data.name.strip(), description="Пользовательский шаблон", format_type=data.format_type, price_rub=0, preview_css_config=json.dumps(data.config.model_dump()), is_active=True)
    db.add(template); await db.flush()
    db.add(TenantTemplate(tenant_id=tenant.id, template_id=template.id, source="custom")); tenant.template_type = template.slug
    await db.commit()
    return {"id": template.id, "template_type": template.slug}

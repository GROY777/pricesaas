from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_db
from ..models import Product, Tenant, PrintJob, PriceTemplate, TenantTemplate
from ..pdf_generator import generate_pdf
from ..security import bearer, current_tenant, telegram_user
from .agent import JOBS_DIR

router = APIRouter(prefix="/api", tags=["changed prices"])

async def principal(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), x_telegram_init_data: str | None = Header(default=None), db: AsyncSession = Depends(get_db)):
    if credentials is not None:
        tenant = await current_tenant(credentials, db)
        return tenant.id, None
    if x_telegram_init_data:
        user = await telegram_user(x_telegram_init_data, db)
        return user.tenant_id, user.telegram_id
    raise HTTPException(401, "Требуется авторизация")

@router.get("/products/changed-prices")
async def changed(identity=Depends(principal), db: AsyncSession = Depends(get_db)):
    items = (await db.scalars(select(Product).where(Product.tenant_id == identity[0], Product.needs_reprint.is_(True)).order_by(Product.id))).all()
    return [{"id": p.id, "name": p.name, "barcode": p.barcode, "previous_price": p.previous_price, "price": p.price, "price_changed_at": p.price_changed_at} for p in items]

@router.post("/products/changed-prices/clear")
async def clear(tenant: Tenant = Depends(current_tenant), db: AsyncSession = Depends(get_db)):
    await db.execute(update(Product).where(Product.tenant_id == tenant.id, Product.needs_reprint.is_(True)).values(needs_reprint=False))
    await db.commit()
    return {"ok": True}

@router.post("/print/changed-prices", status_code=201)
async def print_changed(identity=Depends(principal), db: AsyncSession = Depends(get_db)):
    tenant = await db.scalar(select(Tenant).where(Tenant.id == identity[0]).with_for_update())
    items = (await db.scalars(select(Product).where(Product.tenant_id == tenant.id, Product.needs_reprint.is_(True)).order_by(Product.id).with_for_update())).all()
    total = len(items)
    if not total:
        raise HTTPException(400, "Нет изменившихся цен")
    if total > 1000:
        raise HTTPException(422, "За один раз можно напечатать не более 1000 ценников")
    active = tenant.plan == "pro" and tenant.subscription_until is not None and tenant.subscription_until > datetime.now(timezone.utc)
    if not active and tenant.free_prints_used + total > 30 + tenant.free_prints_bonus:
        raise HTTPException(402, "Бесплатный лимит ценников исчерпан")
    template = await db.scalar(select(PriceTemplate).join(TenantTemplate, TenantTemplate.template_id == PriceTemplate.id).where(TenantTemplate.tenant_id == tenant.id, PriceTemplate.slug == tenant.template_type, PriceTemplate.is_active.is_(True)))
    if tenant.template_type not in ("a4_3x4", "a4_promo", "thermo_58x40") and template is None:
        raise HTTPException(403, "Шаблон недоступен")
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    path = JOBS_DIR / f"{uuid4().hex}.pdf"
    try:
        labels = [(SimpleNamespace(name=p.name, barcode=p.barcode, price=p.price, old_price=p.old_price if p.old_price is not None else p.previous_price, unit=p.unit), 1) for p in items]
        generate_pdf(path, labels, tenant.template_type, company_name=tenant.company_name, config=template.preview_css_config if template else None, format_type=template.format_type if template else None, label_settings=tenant.label_settings)
        if not active:
            tenant.free_prints_used += total
        for product in items:
            product.needs_reprint = False
        job = PrintJob(tenant_id=tenant.id, created_by_tg_id=identity[1], items_count=total, pdf_filename=path.name)
        db.add(job)
        await db.commit()
    except Exception:
        path.unlink(missing_ok=True)
        raise
    await db.refresh(job)
    return {"id": job.id, "items_count": total, "status": job.status}

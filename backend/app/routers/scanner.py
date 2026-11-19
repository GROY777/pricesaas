from collections import Counter
from datetime import datetime, timezone
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_db
from ..models import PrintJob, Product, Tenant, User, PriceTemplate, TenantTemplate
from ..pdf_generator import generate_pdf
from ..schemas import PrintItem, ProductResponse
from ..security import telegram_user
from .agent import JOBS_DIR

router = APIRouter(prefix="/api", tags=["scanner"])


@router.get("/products/{barcode}", response_model=ProductResponse)
async def product(barcode: str, user: User = Depends(telegram_user), db: AsyncSession = Depends(get_db)):
    item = await db.scalar(select(Product).where(Product.tenant_id == user.tenant_id, Product.barcode == barcode))
    if item is None:
        raise HTTPException(404, "Товар не найден")
    return item


@router.post("/print", status_code=201)
async def print_labels(items: list[PrintItem], user: User = Depends(telegram_user), db: AsyncSession = Depends(get_db)):
    quantities = Counter()
    for item in items:
        quantities[item.barcode] += item.quantity
    total = sum(quantities.values())
    if total < 1 or total > 1000:
        raise HTTPException(422, "Укажите от 1 до 1000 ценников")
    tenant = await db.scalar(select(Tenant).where(Tenant.id == user.tenant_id).with_for_update())
    active = tenant.plan == "pro" and tenant.subscription_until is not None and tenant.subscription_until > datetime.now(timezone.utc)
    if not active and tenant.free_prints_used + total > 30 + tenant.free_prints_bonus:
        raise HTTPException(402, "Бесплатный лимит 30 ценников исчерпан. Оформите подписку в личном кабинете")
    products = (await db.scalars(select(Product).where(Product.tenant_id == tenant.id, Product.barcode.in_(quantities)))).all()
    by_barcode = {p.barcode: p for p in products}
    if len(by_barcode) != len(quantities):
        raise HTTPException(404, "Один или несколько товаров не найдены")
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}.pdf"
    path = JOBS_DIR / filename
    try:
        template = await db.scalar(select(PriceTemplate).join(TenantTemplate, TenantTemplate.template_id == PriceTemplate.id).where(TenantTemplate.tenant_id == tenant.id, PriceTemplate.slug == tenant.template_type, PriceTemplate.is_active.is_(True)))
        if tenant.template_type not in ("a4_3x4", "a4_promo", "thermo_58x40") and template is None:
            raise HTTPException(403, "Шаблон недоступен")
        generate_pdf(path, [(by_barcode[code], quantity) for code, quantity in quantities.items()], tenant.template_type, company_name=tenant.company_name, config=template.preview_css_config if template else None, format_type=template.format_type if template else None)
        if not active:
            tenant.free_prints_used += total
        job = PrintJob(tenant_id=tenant.id, created_by_tg_id=user.telegram_id, items_count=total, pdf_filename=filename)
        db.add(job)
        await db.commit()
    except Exception:
        path.unlink(missing_ok=True)
        raise
    await db.refresh(job)
    return {"id": job.id, "items_count": total, "status": job.status}

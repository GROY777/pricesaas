import io
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, func, or_, delete
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_db
from ..models import Product, Tenant, PrintJob, PriceTemplate, TenantTemplate
from ..security import current_tenant
from ..pdf_generator import generate_pdf
from .agent import JOBS_DIR

router = APIRouter(prefix='/api/catalog', tags=['catalog'])

class ProductForm(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    barcode: str | None = Field(default=None, max_length=128)
    article: str = Field(min_length=1, max_length=128)
    price: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    unit: str = Field(default='шт.', min_length=1, max_length=32)

class Selection(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=1000)

def record(p):
    return {'id': p.id, 'name': p.name, 'article': p.article, 'barcode': p.barcode, 'price': p.price, 'unit': p.unit, 'updated_at': p.updated_at}

@router.get('')
async def listing(q: str = '', filter: str = 'all', page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=100), tenant: Tenant = Depends(current_tenant), db: AsyncSession = Depends(get_db)):
    conditions = [Product.tenant_id == tenant.id]
    if q.strip():
        escaped = q.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        conditions.append(or_(Product.name.ilike(f'%{escaped}%', escape='\\'), Product.article.ilike(f'%{escaped}%', escape='\\'), Product.barcode.ilike(f'%{escaped}%', escape='\\')))
    if filter == 'no_price': conditions.append(Product.price == 0)
    elif filter == 'no_barcode': conditions.append(or_(Product.barcode == '', Product.barcode.is_(None)))
    elif filter != 'all': raise HTTPException(422, 'Неизвестный фильтр')
    total = await db.scalar(select(func.count()).select_from(Product).where(*conditions))
    products = (await db.scalars(select(Product).where(*conditions).order_by(Product.id).offset((page-1)*limit).limit(limit))).all()
    return {'items': [record(p) for p in products], 'total': total, 'page': page, 'limit': limit}

@router.get('/export')
async def export(tenant: Tenant = Depends(current_tenant), db: AsyncSession = Depends(get_db)):
    import openpyxl
    book = openpyxl.Workbook(write_only=True); sheet = book.create_sheet('Товары')
    sheet.append(['Наименование', 'Артикул', 'Штрихкод', 'Цена', 'Ед. изм.', 'Дата обновления'])
    result = await db.stream_scalars(select(Product).where(Product.tenant_id == tenant.id).order_by(Product.id))
    async for p in result:
        # Prevent spreadsheet programs from interpreting product data as formulas.
        safe = lambda value: "'" + value if value and value[0] in '=+-@\t\r' else value
        sheet.append([safe(p.name), safe(p.article), safe(p.barcode), float(p.price), safe(p.unit), p.updated_at.isoformat() if p.updated_at else ''])
    output = io.BytesIO(); book.save(output); output.seek(0)
    return StreamingResponse(output, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={'Content-Disposition':'attachment; filename=PriceSnap_Products.xlsx'})

@router.post('')
async def create(data: ProductForm, tenant: Tenant = Depends(current_tenant), db: AsyncSession = Depends(get_db)):
    data.barcode = data.barcode or None
    if await db.scalar(select(Product.id).where(Product.tenant_id == tenant.id, or_(Product.article == data.article, Product.barcode == data.barcode if data.barcode else False))): raise HTTPException(409, 'Такой артикул или штрихкод уже существует')
    product = Product(tenant_id=tenant.id, **data.model_dump()); db.add(product); await db.commit(); await db.refresh(product); return record(product)

@router.patch('/{product_id}')
async def edit(product_id: int, data: ProductForm, tenant: Tenant = Depends(current_tenant), db: AsyncSession = Depends(get_db)):
    product = await db.scalar(select(Product).where(Product.id == product_id, Product.tenant_id == tenant.id).with_for_update())
    if product is None: raise HTTPException(404, 'Товар не найден')
    data.barcode = data.barcode or None
    if await db.scalar(select(Product.id).where(Product.tenant_id == tenant.id, or_(Product.article == data.article, Product.barcode == data.barcode if data.barcode else False), Product.id != product_id)): raise HTTPException(409, 'Такой артикул или штрихкод уже существует')
    if product.price != data.price:
        product.previous_price = product.price; product.price_changed_at = datetime.now(timezone.utc); product.needs_reprint = True
    for key, value in data.model_dump().items(): setattr(product, key, value)
    await db.commit(); await db.refresh(product); return record(product)

@router.post('/delete')
async def delete_selected(data: Selection, tenant: Tenant = Depends(current_tenant), db: AsyncSession = Depends(get_db)):
    result = await db.execute(delete(Product).where(Product.tenant_id == tenant.id, Product.id.in_(data.ids)))
    await db.commit(); return {'deleted': result.rowcount}

@router.delete('')
async def delete_all(tenant: Tenant = Depends(current_tenant), db: AsyncSession = Depends(get_db)):
    result = await db.execute(delete(Product).where(Product.tenant_id == tenant.id)); await db.commit(); return {'deleted': result.rowcount}

@router.post('/print')
async def print_selected(data: Selection, tenant: Tenant = Depends(current_tenant), db: AsyncSession = Depends(get_db)):
    tenant = await db.scalar(select(Tenant).where(Tenant.id == tenant.id).with_for_update())
    ids = set(data.ids)
    items = (await db.scalars(select(Product).where(Product.tenant_id == tenant.id, Product.id.in_(ids)).order_by(Product.id))).all()
    if len(items) != len(ids): raise HTTPException(404, 'Один или несколько товаров не найдены')
    active = tenant.plan == 'pro' and tenant.subscription_until and tenant.subscription_until > datetime.now(timezone.utc)
    if not active and tenant.free_prints_used + len(items) > 30 + tenant.free_prints_bonus: raise HTTPException(402, 'Бесплатный лимит исчерпан')
    template = await db.scalar(select(PriceTemplate).join(TenantTemplate, TenantTemplate.template_id == PriceTemplate.id).where(TenantTemplate.tenant_id == tenant.id, PriceTemplate.slug == tenant.template_type, PriceTemplate.is_active.is_(True)))
    if tenant.template_type not in ('a4_3x4', 'a4_promo', 'thermo_58x40') and not template: raise HTTPException(403, 'Шаблон недоступен')
    JOBS_DIR.mkdir(parents=True, exist_ok=True); path = JOBS_DIR / f'{uuid4().hex}.pdf'
    try:
        generate_pdf(path, [(p, 1) for p in items], tenant.template_type, company_name=tenant.company_name, config=template.preview_css_config if template else None, format_type=template.format_type if template else None, label_settings=tenant.label_settings)
        if not active: tenant.free_prints_used += len(items)
        job = PrintJob(tenant_id=tenant.id, items_count=len(items), pdf_filename=path.name); db.add(job); await db.commit()
    except Exception:
        path.unlink(missing_ok=True); raise
    return {'id': job.id, 'items_count': len(items)}

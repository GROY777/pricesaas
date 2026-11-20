from pathlib import Path
from datetime import datetime, timedelta, timezone
import secrets
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import func, select, or_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_db
from ..models import PrintJob, Product, Tenant
from ..schemas import ProductInput
from ..security import api_tenant
from ..product_sync import price_update_values
from ..config import get_settings

router = APIRouter(prefix="/api", tags=["agent"])
JOBS_DIR = Path("/app/media/jobs")

@router.get("/agent/version")
async def agent_version():
    return {"version": get_settings().agent_version, "download_url": "https://cardifyrbx.shop/releases/PriceAgent_Setup.exe", "release_notes": "Новый интерфейс, автообновление и улучшенная стабильность печати", "mandatory": False}


@router.post("/sync")
async def sync(items: list[ProductInput], tenant: Tenant = Depends(api_tenant), db: AsyncSession = Depends(get_db)):
    if len(items) > 500:
        raise HTTPException(422, "Не более 500 товаров за запрос")
    unique = {item.barcode: item for item in items}
    if unique:
        rows = [{**item.model_dump(), "tenant_id": tenant.id} for item in unique.values()]
        statement = insert(Product).values(rows)
        values = price_update_values(statement)
        values["old_price"] = statement.excluded.old_price
        statement = statement.on_conflict_do_update(index_elements=["tenant_id", "barcode"], set_=values)
        await db.execute(statement)
        await db.commit()
    return {"synced": len(unique)}


@router.get("/agent/jobs")
async def jobs(tenant: Tenant = Depends(api_tenant), db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    job = await db.scalar(select(PrintJob).where(PrintJob.tenant_id == tenant.id, or_(PrintJob.status == "pending", (PrintJob.status == "processing") & (PrintJob.locked_at < now - timedelta(minutes=2)))).order_by(PrintJob.id).limit(1).with_for_update(skip_locked=True))
    if job is None:
        await db.commit()
        return []
    job.status = "processing"
    job.locked_at = now
    job.lock_token = secrets.token_urlsafe(32)
    result = {"id": job.id, "items_count": job.items_count, "file_url": f"/api/agent/jobs/{job.id}/file", "lock_token": job.lock_token}
    await db.commit()
    return [result]


async def find_job(job_id: int, tenant: Tenant, db: AsyncSession, lock_token: str):
    job = await db.scalar(select(PrintJob).where(PrintJob.id == job_id, PrintJob.tenant_id == tenant.id, PrintJob.status == "processing", PrintJob.lock_token == lock_token, PrintJob.locked_at >= datetime.now(timezone.utc) - timedelta(minutes=2)).with_for_update())
    if job is None:
        raise HTTPException(404, "Задание не найдено")
    return job


@router.get("/agent/jobs/{job_id}/file")
async def job_file(job_id: int, x_job_token: str = Header(), tenant: Tenant = Depends(api_tenant), db: AsyncSession = Depends(get_db)):
    job = await find_job(job_id, tenant, db, x_job_token)
    path = JOBS_DIR / Path(job.pdf_filename).name
    if not path.is_file():
        raise HTTPException(404, "Файл задания не найден")
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@router.post("/agent/jobs/{job_id}/ack")
async def ack(job_id: int, x_job_token: str = Header(), tenant: Tenant = Depends(api_tenant), db: AsyncSession = Depends(get_db)):
    job = await find_job(job_id, tenant, db, x_job_token)
    job.status = "printed"
    job.locked_at = None
    job.lock_token = None
    await db.commit()
    return {"status": job.status}

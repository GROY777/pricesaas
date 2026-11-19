from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..config import get_settings
from ..database import get_db
from ..models import Tenant, TenantEmployee
from ..security import current_tenant

router = APIRouter(prefix="/api/employees", tags=["employees"])

class Invite(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)

@router.get("")
async def list_employees(tenant: Tenant = Depends(current_tenant), db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(TenantEmployee).where(TenantEmployee.tenant_id == tenant.id).order_by(TenantEmployee.id.desc()))).all()
    return [{"id": e.id, "full_name": e.full_name, "telegram_username": e.telegram_username, "is_active": e.is_active, "activated_at": e.activated_at, "created_at": e.created_at} for e in rows]

@router.post("/invite", status_code=201)
async def invite(data: Invite, tenant: Tenant = Depends(current_tenant), db: AsyncSession = Depends(get_db)):
    name = data.full_name.strip()
    if not name:
        raise HTTPException(422, "Укажите имя сотрудника")
    employee = TenantEmployee(tenant_id=tenant.id, full_name=name)
    db.add(employee)
    await db.commit()
    await db.refresh(employee)
    return {"id": employee.id, "url": f"https://t.me/{get_settings().bot_username}?start=invite_{employee.invite_token}"}

@router.delete("/{employee_id}")
async def revoke(employee_id: int, tenant: Tenant = Depends(current_tenant), db: AsyncSession = Depends(get_db)):
    employee = await db.scalar(select(TenantEmployee).where(TenantEmployee.id == employee_id, TenantEmployee.tenant_id == tenant.id).with_for_update())
    if employee is None:
        raise HTTPException(404, "Сотрудник не найден")
    employee.is_active = False
    await db.commit()
    return {"ok": True}

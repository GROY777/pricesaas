from datetime import datetime, timedelta, timezone
from uuid import uuid4
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..config import get_settings
from ..database import get_db
from ..models import Payment, Tenant
from ..security import current_tenant

router = APIRouter(prefix="/api/billing", tags=["billing"])
API = "https://api.yookassa.ru/v3/payments"


def credentials():
    settings = get_settings()
    if not settings.yookassa_shop_id or not settings.yookassa_secret_key:
        raise HTTPException(503, "Оплата не настроена")
    return settings.yookassa_shop_id, settings.yookassa_secret_key


@router.post("/create-payment")
async def create_payment(tenant: Tenant = Depends(current_tenant), db: AsyncSession = Depends(get_db)):
    auth = credentials()
    payload = {"amount": {"value": "1490.00", "currency": "RUB"}, "capture": True, "confirmation": {"type": "redirect", "return_url": get_settings().webapp_url.rstrip("/") + "/dashboard.html?payment=success"}, "description": "PriceSnap: подписка на 30 дней", "metadata": {"tenant_id": str(tenant.id)}}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(API, auth=auth, headers={"Idempotence-Key": str(uuid4())}, json=payload)
            response.raise_for_status()
            data = response.json()
        payment = Payment(tenant_id=tenant.id, yookassa_payment_id=data["id"], amount=1490, status="pending")
        db.add(payment)
        await db.commit()
        return {"confirmation_url": data["confirmation"]["confirmation_url"]}
    except (httpx.HTTPError, KeyError, ValueError):
        raise HTTPException(502, "Не удалось создать платёж")


@router.post("/webhook")
async def webhook(request: Request, db: AsyncSession = Depends(get_db)):
    auth = credentials()
    try:
        payload = await request.json()
        if payload.get("event") != "payment.succeeded":
            return {"ok": True}
        payment_id = payload["object"]["id"]
        if not isinstance(payment_id, str) or len(payment_id) > 128 or "/" in payment_id:
            raise ValueError("invalid payment id")
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(f"{API}/{payment_id}", auth=auth)
            response.raise_for_status()
            remote = response.json()
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise HTTPException(400, "Не удалось проверить платёж")
    payment = await db.scalar(select(Payment).where(Payment.yookassa_payment_id == payment_id).with_for_update())
    if payment is None:
        raise HTTPException(404, "Платёж не найден")
    if remote.get("status") != "succeeded" or remote.get("amount", {}).get("value") != "1490.00" or remote.get("amount", {}).get("currency") != "RUB" or remote.get("metadata", {}).get("tenant_id") != str(payment.tenant_id):
        raise HTTPException(400, "Данные платежа не совпадают")
    if payment.status != "succeeded":
        tenant = await db.scalar(select(Tenant).where(Tenant.id == payment.tenant_id).with_for_update())
        now = datetime.now(timezone.utc)
        tenant.subscription_until = max(now, tenant.subscription_until or now) + timedelta(days=30)
        tenant.plan = "pro"
        payment.status = "succeeded"
        await db.commit()
    return {"ok": True}

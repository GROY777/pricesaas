import logging
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Literal
from uuid import UUID, uuid4
import httpx
from aiogram import Bot
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from ..config import get_settings
from ..database import get_db, SessionLocal
from ..models import Payment, Tenant, TenantTemplate, PriceTemplate, User
from ..security import current_tenant

router = APIRouter(prefix='/api/payments', tags=['payments'])
API = 'https://api.yookassa.ru/v3/payments'
PLANS = {'pro_1m': (Decimal('990.00'), 30, 'Подписка PRO на 30 дней'), 'pro_3m': (Decimal('2490.00'), 90, 'Подписка PRO на 90 дней'), 'pro_12m': (Decimal('7990.00'), 365, 'Подписка PRO на 365 дней')}
log = logging.getLogger(__name__)

class Purchase(BaseModel):
    product_type: Literal['pro_1m', 'pro_3m', 'pro_12m', 'template']
    template_id: int | None = None

def credentials():
    s = get_settings()
    if not s.yookassa_shop_id or not s.yookassa_secret_key:
        raise HTTPException(503, 'Платёжный шлюз настраивается, обратитесь в поддержку')
    return s.yookassa_shop_id, s.yookassa_secret_key

@router.post('/create')
async def create(data: Purchase, tenant: Tenant = Depends(current_tenant), db: AsyncSession = Depends(get_db)):
    auth = credentials()
    s = get_settings()
    if s.yookassa_vat_code not in range(1, 7):
        raise HTTPException(503, 'Платёжный шлюз настраивается, обратитесь в поддержку')
    target = None
    if data.product_type == 'template':
        template = await db.get(PriceTemplate, data.template_id) if data.template_id else None
        if not template or not template.is_active or template.price_rub <= 0 or template.slug.startswith('custom-'):
            raise HTTPException(404, 'Платный шаблон не найден')
        if await db.get(TenantTemplate, (tenant.id, template.id)):
            raise HTTPException(409, 'Шаблон уже доступен')
        target, amount, description = template.id, Decimal(template.price_rub), f'Шаблон PriceSnap: {template.name}'[:128]
    else:
        if data.template_id is not None:
            raise HTTPException(422, 'Шаблон не относится к подписке')
        amount, _, description = PLANS[data.product_type]
    value = f'{amount:.2f}'
    metadata = {'tenant_id': str(tenant.id), 'product_type': data.product_type, 'template_id': str(target) if target else ''}
    payload = {'amount': {'value': value, 'currency': 'RUB'}, 'capture': True, 'confirmation': {'type':'redirect', 'return_url':s.yookassa_return_url}, 'description':description, 'metadata':metadata, 'receipt': {'customer': {'email': tenant.email or 'receipt@cardifyrbx.shop'}, 'items': [{'description': description, 'quantity':'1.00', 'amount': {'value':value, 'currency':'RUB'}, 'vat_code':s.yookassa_vat_code, 'payment_subject':'service', 'payment_mode':'full_payment'}]}}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(API, auth=auth, headers={'Idempotence-Key': str(uuid4())}, json=payload)
            response.raise_for_status()
            result = response.json()
            UUID(result['id'])
            url = result['confirmation']['confirmation_url']
            if not url.startswith('https://'):
                raise ValueError('invalid redirect')
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise HTTPException(502, 'Не удалось создать платёж')
    db.add(Payment(tenant_id=tenant.id, yookassa_payment_id=result['id'], amount=amount, currency='RUB', product_type=data.product_type, target_id=target, status='pending'))
    await db.commit()
    return {'confirmation_url':url}

@router.post('/yookassa/webhook')
async def webhook(request: Request, db: AsyncSession = Depends(get_db)):
    auth = credentials()
    try:
        payload = await request.json()
        if payload.get('event') != 'payment.succeeded':
            return {'ok':True}
        payment_id = str(UUID(payload['object']['id']))
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(f'{API}/{payment_id}', auth=auth)
            response.raise_for_status()
            remote = response.json()
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
        raise HTTPException(400, 'Не удалось проверить платёж')
    result = await apply_remote(payment_id, remote, db)
    if result == 'pending':
        raise HTTPException(400, 'Платёж ещё не подтверждён')
    return {'ok':True}

async def apply_remote(payment_id: str, remote: dict, db: AsyncSession):
    payment = await db.scalar(select(Payment).where(Payment.yookassa_payment_id == payment_id).with_for_update())
    if not payment:
        raise HTTPException(404, 'Платёж не найден')
    if payment.status == 'succeeded':
        return 'already_processed'
    if payment.status != 'pending':
        return 'already_processed'
    meta = remote.get('metadata') or {}
    try:
        legacy = payment.product_type == 'pro_1m' and payment.amount == Decimal('1490.00') and not meta.get('product_type')
        valid = remote.get('id') == payment_id and Decimal(remote['amount']['value']) == payment.amount and remote['amount']['currency'] == payment.currency and meta.get('tenant_id') == str(payment.tenant_id) and (legacy or (meta.get('product_type') == payment.product_type and (meta.get('template_id') or '') == (str(payment.target_id) if payment.target_id else '')))
    except (KeyError, TypeError, ValueError, InvalidOperation):
        valid = False
    if not valid:
        raise HTTPException(400, 'Данные платежа не совпадают')
    if remote.get('status') == 'canceled':
        payment.status = 'canceled'
        await db.commit()
        return 'canceled'
    if remote.get('status') != 'succeeded' or remote.get('paid') is not True:
        return 'pending'
    tenant = await db.scalar(select(Tenant).where(Tenant.id == payment.tenant_id).with_for_update())
    now = datetime.now(timezone.utc)
    if payment.product_type in PLANS:
        until = tenant.subscription_until
        if until and until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        tenant.subscription_until = max(now, until or now) + timedelta(days=PLANS[payment.product_type][1])
        tenant.plan = 'pro'
        message = f'Оплата получена. PRO активен до {tenant.subscription_until:%d.%m.%Y}.'
    elif payment.product_type == 'template' and payment.target_id:
        await db.execute(insert(TenantTemplate).values(tenant_id=tenant.id, template_id=payment.target_id, source='purchase').on_conflict_do_nothing(index_elements=['tenant_id','template_id']))
        message = 'Оплата получена. Шаблон доступен в вашем магазине.'
    else:
        raise HTTPException(400, 'Неизвестный тип платежа')
    payment.status = 'succeeded'; payment.paid_at = now
    owner_id = await db.scalar(select(User.telegram_id).where(User.tenant_id == tenant.id, User.role == 'owner').limit(1))
    await db.commit()
    if owner_id and get_settings().bot_token:
        bot = Bot(get_settings().bot_token)
        try:
            await bot.send_message(owner_id, message)
        except Exception:
            log.warning('Could not notify owner of payment', exc_info=True)
        finally:
            await bot.session.close()
    return 'succeeded'

async def fetch_remote(client, payment_id, auth):
    try:
        payment_id = str(UUID(payment_id))
        response = await client.get(f'{API}/{payment_id}', auth=auth)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError('invalid response')
        return data
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise HTTPException(502, 'Не удалось проверить платёж') from exc

async def sync_pending(tenant_id=None):
    auth = credentials()
    async with SessionLocal() as db:
        query = select(Payment.yookassa_payment_id).where(Payment.status == 'pending', Payment.created_at >= datetime.now(timezone.utc) - timedelta(hours=24)).order_by(Payment.id)
        if tenant_id is not None:
            query = query.where(Payment.tenant_id == tenant_id)
        ids = (await db.scalars(query)).all()
    counts = {'checked': 0, 'succeeded': 0, 'canceled': 0, 'errors': 0}
    async with httpx.AsyncClient(timeout=20) as client:
        limit = asyncio.Semaphore(8)
        async def check(payment_id):
            async with limit:
                try:
                    remote = await fetch_remote(client, payment_id, auth)
                    async with SessionLocal() as db:
                        result = await apply_remote(payment_id, remote, db)
                    counts['checked'] += 1
                    if result in ('succeeded', 'canceled'):
                        counts[result] += 1
                except Exception:
                    counts['errors'] += 1
                    log.warning('Unable to reconcile payment %s', payment_id, exc_info=True)
        await asyncio.gather(*(check(payment_id) for payment_id in ids))
    return counts

@router.post('/sync')
async def sync(tenant: Tenant = Depends(current_tenant)):
    return await sync_pending(tenant.id)

async def sync_loop():
    while True:
        await asyncio.sleep(20)
        try:
            if get_settings().yookassa_shop_id and get_settings().yookassa_secret_key:
                await sync_pending()
        except Exception:
            log.exception('Payment reconciliation failed')

@router.get('/history')
async def history(tenant: Tenant = Depends(current_tenant), db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(Payment).where(Payment.tenant_id == tenant.id).order_by(Payment.id.desc()).limit(100))).all()
    return [{'id':p.id, 'amount':p.amount, 'currency':p.currency, 'product_type':p.product_type, 'target_id':p.target_id, 'status':p.status, 'created_at':p.created_at, 'paid_at':p.paid_at} for p in rows]

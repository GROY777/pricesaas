import hashlib
import base64
import hmac
import json
import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl

import jwt
from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from .config import get_settings
from .database import get_db
from .models import Tenant, User, UsedFreeDevice, TenantEmployee

password_hasher = PasswordHash.recommended()
bearer = HTTPBearer(auto_error=False)


def new_api_key() -> str:
    return "ps_live_" + secrets.token_hex(16)


def create_token(tenant_id: int, csrf: str | None = None) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(tenant_id), "iat": now, "exp": now + timedelta(minutes=settings.jwt_expire_minutes), **({'csrf': csrf} if csrf else {})}, settings.jwt_secret, algorithm="HS256")


async def current_tenant(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: AsyncSession = Depends(get_db), request: Request = None) -> Tenant:
    try:
        token = credentials.credentials if credentials else (request.cookies.get('__Host-pricesnap_session') if request else None)
        if not token:
            raise ValueError("missing token")
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"], options={"require": ["sub", "exp"]})
        if not credentials and request and request.method not in ('GET', 'HEAD', 'OPTIONS'):
            expected = payload.get('csrf')
            supplied = request.headers.get('x-csrf-token', '')
            if not isinstance(expected, str) or not hmac.compare_digest(expected, supplied):
                raise HTTPException(403, 'Неверный CSRF-токен')
        tenant_id = int(payload["sub"])
    except (jwt.InvalidTokenError, ValueError, TypeError, KeyError):
        raise HTTPException(status_code=401, detail="Неверный токен")
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=401, detail="Магазин не найден")
    if not tenant.is_active:
        raise HTTPException(status_code=403, detail="Store blocked")
    return tenant


async def get_current_admin(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: AsyncSession = Depends(get_db), request: Request = None) -> Tenant:
    try:
        tenant = await current_tenant(credentials, db, request)
    except HTTPException:
        raise HTTPException(status_code=403, detail="Access denied")
    if tenant.email.lower() not in get_settings().admin_emails:
        raise HTTPException(status_code=403, detail="Access denied")
    secret = get_settings().admin_totp_secret.strip().replace(' ', '').upper()
    if secret:
        code = request.headers.get('X-Admin-OTP', '') if request else ''
        try:
            key = base64.b32decode(secret + '=' * (-len(secret) % 8), casefold=True)
            if len(key) < 16 or len(code) != 6 or not code.isascii() or not code.isdigit(): raise ValueError('Invalid OTP')
            valid = False
            for counter in range(int(time.time()) // 30 - 1, int(time.time()) // 30 + 2):
                digest = hmac.new(key, counter.to_bytes(8, 'big'), hashlib.sha1).digest()
                offset = digest[-1] & 15
                value = (int.from_bytes(digest[offset:offset + 4], 'big') & 0x7fffffff) % 1000000
                valid |= hmac.compare_digest(f'{value:06d}', code)
            if not valid: raise ValueError('Invalid OTP')
        except (ValueError, TypeError):
            raise HTTPException(status_code=403, detail='Требуется действующий код администратора')
    return tenant


async def api_tenant(x_api_key: str = Header(), x_device_hwid: str | None = Header(default=None), db: AsyncSession = Depends(get_db)) -> Tenant:
    tenant = await db.scalar(select(Tenant).where(Tenant.api_key == x_api_key))
    if tenant is None:
        raise HTTPException(status_code=401, detail="Неверный API-ключ")
    if not tenant.is_active:
        raise HTTPException(status_code=403, detail="Store blocked")
    active_pro = tenant.plan == "pro" and tenant.subscription_until and tenant.subscription_until > datetime.now(timezone.utc)
    if x_device_hwid and not active_pro:
        hwid = x_device_hwid.strip().lower()
        if not hwid or len(hwid) > 255:
            raise HTTPException(status_code=422, detail="Invalid device identifier")
        await db.execute(insert(UsedFreeDevice).values(hwid=hwid, first_tenant_id=tenant.id).on_conflict_do_nothing(index_elements=[UsedFreeDevice.hwid]))
        used = await db.get(UsedFreeDevice, hwid)
        if used.first_tenant_id != tenant.id:
            tenant.free_prints_used = max(tenant.free_prints_used, 30)
            await db.commit()
            raise HTTPException(status_code=402, detail="Бесплатный пробный лимит уже был использован на этом компьютере. Оформите подписку PRO")
        await db.commit()
    return tenant


def verify_telegram_init_data(raw: str) -> dict:
    settings = get_settings()
    if not settings.bot_token:
        raise HTTPException(status_code=503, detail="Telegram не настроен")
    pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
    values = dict(pairs)
    if len(values) != len(pairs) or "hash" not in values:
        raise ValueError("Invalid init data")
    supplied_hash = values.pop("hash")
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", settings.bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, supplied_hash):
        raise ValueError("Invalid signature")
    age = time.time() - int(values["auth_date"])
    if age < -60 or age > settings.telegram_max_age_seconds:
        raise ValueError("Expired init data")
    user = json.loads(values["user"])
    if not isinstance(user, dict) or not isinstance(user.get("id"), int):
        raise ValueError("Invalid user")
    return user


async def telegram_user(x_telegram_init_data: str = Header(), db: AsyncSession = Depends(get_db)) -> User:
    try:
        data = verify_telegram_init_data(x_telegram_init_data)
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        raise HTTPException(status_code=401, detail="Неверные данные Telegram")
    employee = await db.scalar(select(TenantEmployee).where(TenantEmployee.telegram_id == data["id"]).order_by(TenantEmployee.is_active.desc(), TenantEmployee.id.desc()).limit(1))
    if employee is not None:
        if not employee.is_active:
            raise HTTPException(status_code=403, detail="Ваш доступ к печати ценников отозван владельцем магазина")
        user = employee
    else:
        user = await db.scalar(select(User).where(User.telegram_id == data["id"]))
    if user is None:
        raise HTTPException(status_code=403, detail="Сначала подключитесь к магазину через бота")
    tenant = await db.get(Tenant, user.tenant_id)
    if tenant is None or not tenant.is_active:
        raise HTTPException(status_code=403, detail="Store blocked")
    return user

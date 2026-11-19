import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl

import jwt
from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from .config import get_settings
from .database import get_db
from .models import Tenant, User

password_hasher = PasswordHash.recommended()
bearer = HTTPBearer(auto_error=False)


def new_api_key() -> str:
    return "ps_live_" + secrets.token_hex(16)


def create_token(tenant_id: int) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(tenant_id), "iat": now, "exp": now + timedelta(minutes=settings.jwt_expire_minutes)}, settings.jwt_secret, algorithm="HS256")


async def current_tenant(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: AsyncSession = Depends(get_db)) -> Tenant:
    try:
        if credentials is None:
            raise ValueError("missing token")
        payload = jwt.decode(credentials.credentials, get_settings().jwt_secret, algorithms=["HS256"], options={"require": ["sub", "exp"]})
        tenant_id = int(payload["sub"])
    except (jwt.InvalidTokenError, ValueError, TypeError, KeyError):
        raise HTTPException(status_code=401, detail="Неверный токен")
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=401, detail="Магазин не найден")
    return tenant


async def api_tenant(x_api_key: str = Header(), db: AsyncSession = Depends(get_db)) -> Tenant:
    tenant = await db.scalar(select(Tenant).where(Tenant.api_key == x_api_key))
    if tenant is None:
        raise HTTPException(status_code=401, detail="Неверный API-ключ")
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
    user = await db.scalar(select(User).where(User.telegram_id == data["id"]))
    if user is None:
        raise HTTPException(status_code=403, detail="Сначала подключитесь к магазину через бота")
    return user

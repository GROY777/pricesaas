from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup, WebAppInfo
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from .config import get_settings
from .database import SessionLocal
from .models import Tenant, User
from .models import TenantEmployee
from datetime import datetime, timezone


async def activate_employee(db, token, telegram_id, username):
    employee = await db.scalar(select(TenantEmployee).where(TenantEmployee.invite_token == token).with_for_update())
    if employee is None or not employee.is_active:
        return "invalid"
    existing = await db.scalar(select(User).where(User.telegram_id == telegram_id))
    active = await db.scalar(select(TenantEmployee).where(TenantEmployee.telegram_id == telegram_id, TenantEmployee.is_active.is_(True)))
    if (existing and existing.tenant_id == employee.tenant_id) or (active and active.tenant_id == employee.tenant_id):
        return "already_connected"
    if employee.telegram_id is not None:
        return "invalid"
    if existing or active:
        return "other_store"
    employee.telegram_id = telegram_id
    employee.telegram_username = username
    employee.activated_at = datetime.now(timezone.utc)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return "other_store"
    return "activated"


async def handle_invite(message: Message, payload: str, db, settings):
    result = await activate_employee(db, payload.removeprefix("invite_"), message.from_user.id, message.from_user.username)
    if result == "invalid":
        await message.answer("Доступ к магазину недействителен или отозван владельцем")
    elif result == "other_store":
        await message.answer("Этот аккаунт Telegram уже подключён к другому магазину.")
    else:
        keyboard = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Открыть сканер", web_app=WebAppInfo(url=settings.webapp_url.rstrip("/") + "/app.html"))]], resize_keyboard=True)
        text = "Этот аккаунт уже подключён к магазину." if result == "already_connected" else "Магазин подключён. Откройте сканер кнопкой ниже."
        await message.answer(text, reply_markup=keyboard)


async def start(message: Message, command: CommandObject):
    settings = get_settings()
    if not command.args or not message.from_user:
        await message.answer("Откройте ссылку-приглашение из кабинета магазина.")
        return
    async with SessionLocal() as db:
        if command.args.startswith("invite_"):
            await handle_invite(message, command.args, db, settings)
            return
        if await db.scalar(select(TenantEmployee.id).where(TenantEmployee.telegram_id == message.from_user.id).limit(1)):
            await message.answer("Используйте личное приглашение сотрудника от владельца магазина.")
            return
        tenant = await db.scalar(select(Tenant).where(Tenant.invite_token == command.args).with_for_update())
        if tenant is None:
            await message.answer("Ссылка недействительна. Попросите владельца прислать новую.")
            return
        existing = await db.scalar(select(User).where(User.telegram_id == message.from_user.id))
        if existing is None:
            count = await db.scalar(select(func.count(User.id)).where(User.tenant_id == tenant.id))
            existing = User(tenant_id=tenant.id, telegram_id=message.from_user.id, full_name=message.from_user.full_name, role="owner" if count == 0 else "cashier")
            db.add(existing)
        else:
            if existing.tenant_id != tenant.id:
                existing.tenant_id = tenant.id
                existing.role = "cashier"
            existing.full_name = message.from_user.full_name
        await db.commit()
    keyboard = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Открыть сканер", web_app=WebAppInfo(url=settings.webapp_url.rstrip("/") + "/app.html"))]], resize_keyboard=True)
    await message.answer("Магазин подключён. Откройте сканер кнопкой ниже.", reply_markup=keyboard)


async def run_bot():
    settings = get_settings()
    bot = Bot(settings.bot_token)
    dispatcher = Dispatcher()
    dispatcher.message.register(start, CommandStart())

    try:
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()

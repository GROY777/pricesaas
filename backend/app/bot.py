from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup, WebAppInfo
from sqlalchemy import func, select
from .config import get_settings
from .database import SessionLocal
from .models import Tenant, User


async def run_bot():
    settings = get_settings()
    bot = Bot(settings.bot_token)
    dispatcher = Dispatcher()

    @dispatcher.message(CommandStart())
    async def start(message: Message, command: CommandObject):
        if not command.args or not message.from_user:
            await message.answer("Откройте ссылку-приглашение из кабинета магазина.")
            return
        async with SessionLocal() as db:
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

    try:
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()

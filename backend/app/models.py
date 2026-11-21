from datetime import datetime
from decimal import Decimal
import secrets
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, func, Text, Boolean, JSON
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    company_name: Mapped[str] = mapped_column(String(255))
    api_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    moysklad_token: Mapped[str | None] = mapped_column(String(1024))
    invite_token: Mapped[str] = mapped_column(String(64), unique=True, index=True, default=lambda: secrets.token_urlsafe(24))
    plan: Mapped[str] = mapped_column(String(16), default="free")
    subscription_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    free_prints_used: Mapped[int] = mapped_column(Integer, default=0)
    free_prints_bonus: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(default=True, index=True)
    template_type: Mapped[str] = mapped_column(String(32), default="a4_3x4")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    registered_ip: Mapped[str | None] = mapped_column(String(64), index=True)
    column_mapping: Mapped[dict | None] = mapped_column(JSON)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="cashier")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TenantEmployee(Base):
    __tablename__ = "tenant_employees"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    telegram_username: Mapped[str | None] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255))
    invite_token: Mapped[str] = mapped_column(String(64), unique=True, default=lambda: secrets.token_urlsafe(16))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("tenant_id", "barcode"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    barcode: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(255))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    old_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    previous_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    price_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    needs_reprint: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    unit: Mapped[str] = mapped_column(String(32), default="шт.")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PrintJob(Base):
    __tablename__ = "print_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    created_by_tg_id: Mapped[int | None] = mapped_column(BigInteger)
    items_count: Mapped[int] = mapped_column(Integer)
    pdf_filename: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lock_token: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    yookassa_payment_id: Mapped[str] = mapped_column(String(128), unique=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3), default="RUB", server_default="RUB")
    product_type: Mapped[str] = mapped_column(String(16), default="pro_1m", server_default="pro_1m")
    target_id: Mapped[int | None] = mapped_column(ForeignKey("price_templates.id"))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UsedFreeDevice(Base):
    __tablename__ = "used_free_devices"
    hwid: Mapped[str] = mapped_column(String(255), primary_key=True)
    first_tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PriceTemplate(Base):
    __tablename__ = "price_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    format_type: Mapped[str] = mapped_column(String(16), default="a4")
    price_rub: Mapped[int] = mapped_column(Integer, default=0)
    preview_css_config: Mapped[str] = mapped_column(Text, default="{}")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class TenantTemplate(Base):
    __tablename__ = "tenant_templates"
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("price_templates.id"), primary_key=True)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source: Mapped[str] = mapped_column(String(16), default="free")

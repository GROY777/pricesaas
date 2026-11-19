from datetime import datetime
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, EmailStr, Field

Template = Literal["a4_3x4", "a4_promo", "thermo_58x40"]


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)
    company_name: str = Field(min_length=1, max_length=255)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class SettingsRequest(BaseModel):
    template_type: Template | None = None
    regenerate_api_key: bool = False
    regenerate_invite_token: bool = False
    moysklad_token: str | None = Field(default=None, max_length=1024)


class ProductInput(BaseModel):
    barcode: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    price: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    old_price: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    unit: str = Field(default="шт.", min_length=1, max_length=32)


class ProductResponse(ProductInput):
    model_config = ConfigDict(from_attributes=True)


class PrintItem(BaseModel):
    barcode: str = Field(min_length=1, max_length=128)
    quantity: int = Field(ge=1, le=1000)

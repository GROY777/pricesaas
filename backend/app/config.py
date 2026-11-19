from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    jwt_secret: str = Field(min_length=32)
    bot_token: str = ""
    bot_username: str = ""
    webapp_url: str = "https://yourdomain.ru"
    yookassa_shop_id: str = ""
    yookassa_secret_key: str = ""
    jwt_expire_minutes: int = 60 * 24
    telegram_max_age_seconds: int = 86400
    admin_email: str = ""

    @property
    def admin_emails(self) -> set[str]:
        return {value.strip().lower() for value in self.admin_email.split(",") if value.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()

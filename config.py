from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    # DSN format asyncpg: postgresql+asyncpg://user:pass@host:port/dbname
    database_url: str = Field(..., env="DATABASE_URL")
    node_js_url: str = Field(..., env="NODE_JS_URL")
    internal_api_key: str = Field(..., env="INTERNAL_API_KEY")
    log_level: str = Field("INFO", env="LOG_LEVEL")

    # Membaca dari file .env di root directory
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

# Inisialisasi Singleton
settings = Settings()
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_env: str = "development"
    api_cors_origins: str = "http://localhost:3000"
    binance_base_url: str = "https://api.binance.com"
    live_trading_enabled: bool = False
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()

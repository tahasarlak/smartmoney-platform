from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    api_cors_origins: str = "http://localhost:3000"
    # Binance public market-data-only host. Can be overridden with BINANCE_BASE_URL.
    binance_base_url: str = "https://data-api.binance.vision"
    live_trading_enabled: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

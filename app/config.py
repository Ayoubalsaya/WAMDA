from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str
    work_timezone: str = "Africa/Tripoli"
    app_env: str = "local"


settings = Settings()

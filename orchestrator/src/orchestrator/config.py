from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql://agent:agent@localhost:5432/agents_platform"
    rabbitmq_url: str = "amqp://agent:agent@localhost:5672/"
    langfuse_secret_key: str = ""
    langfuse_public_key: str = ""
    langfuse_host: str = "http://localhost:3000"
    anthropic_api_key: str = ""
    approval_service_url: str = "http://localhost:8001"


settings = Settings()

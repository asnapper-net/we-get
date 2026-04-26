from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql://agent:agent@localhost:5432/agents_platform"
    rabbitmq_url: str = "amqp://agent:agent@localhost:5672/"
    github_webhook_secret: str = ""
    approval_service_url: str = "http://approval-service.agents-services.svc:8001"
    slack_bot_token: str = ""
    slack_review_channel: str = "agent-approvals-prs"
    max_review_cycles: int = 3


settings = Settings()

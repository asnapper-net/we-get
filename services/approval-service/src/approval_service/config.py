from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql://agent:agent@localhost:5432/agents_platform"
    slack_bot_token: str = ""
    slack_signing_secret: str = ""
    orchestrator_url: str = "http://orchestrator.agents-runtime.svc:8000"

    channel_arch: str = "agent-approvals-arch"
    channel_prs: str = "agent-approvals-prs"
    channel_prod: str = "agent-approvals-prod"
    channel_incidents: str = "agent-incidents"

    approver_roles: dict[str, list[str]] = {
        "architecture": ["senior-eng", "tech-lead", "architect"],
        "deployment-staging": ["senior-eng", "tech-lead"],
        "deployment-production": ["tech-lead", "engineering-manager"],
    }


settings = Settings()

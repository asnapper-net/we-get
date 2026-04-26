from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str = ""
    database_url: str = "postgresql://agent:agent@localhost:5432/agents_platform"
    langfuse_secret_key: str = ""
    langfuse_public_key: str = ""
    langfuse_host: str = "http://localhost:3000"

    # MCP server base URLs (internal K8s DNS in prod)
    mcp_github_url: str = "http://github-mcp.agents-mcp.svc:8080"
    mcp_jira_url: str = "http://atlassian-mcp.agents-mcp.svc:8080"
    mcp_confluence_url: str = "http://atlassian-mcp.agents-mcp.svc:8080"
    mcp_kubernetes_url: str = "http://kubernetes-mcp.agents-mcp.svc:8080"
    mcp_slack_url: str = "http://slack-mcp.agents-mcp.svc:8080"
    mcp_playwright_url: str = "http://playwright-mcp.agents-mcp.svc:8080"
    mcp_filesystem_url: str = "http://filesystem-mcp.agents-mcp.svc:8080"
    mcp_qdrant_url: str = "http://qdrant-mcp.agents-mcp.svc:8080"


agent_settings = AgentSettings()

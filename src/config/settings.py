"""Application settings using pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, SecretStr
from decimal import Decimal


class Settings(BaseSettings):
    """Agent configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Venice AI (A0T Staking Benefits)
    venice_api_key: SecretStr = Field(..., description="Venice API key from A0T staking")
    venice_base_url: str = "https://api.venice.ai/api/v1"

    # Blockchain
    base_rpc_url: str = "https://mainnet.base.org"
    base_wallet_private_key: SecretStr = Field(..., description="Base wallet private key")
    base_wallet_address: str = Field(..., description="Base wallet address")

    # Database
    database_url: SecretStr = Field(..., description="PostgreSQL connection string")
    redis_url: str = "redis://localhost:6379/0"

    # Dune Analytics
    dune_api_key: SecretStr = Field(default=SecretStr(""), description="Dune Analytics API key")

    # Nansen
    nansen_api_key: SecretStr = Field(default=SecretStr(""), description="Nansen API key")

    # BaseScan
    basescan_api_key: SecretStr = Field(default=SecretStr(""), description="BaseScan API key")

    # WhatShouldICharge Integration
    wsic_api_key: SecretStr = Field(..., description="WhatShouldICharge API key")
    wsic_base_url: str = "https://api.whatshouldicharge.app"

    # Fly.io
    fly_app_name: str = "autonomous-revenue-agent"
    fly_region: str = "ord"

    # Agent Identity
    agent_name: str = "RevenueSeeker"
    agent_mode: str = "live"  # live, paper, or maintenance

    # Trading Limits
    max_trade_size_usd: Decimal = Field(default=Decimal("100.00"))
    daily_budget_usd: Decimal = Field(default=Decimal("50.00"))
    risk_per_trade_pct: Decimal = Field(default=Decimal("2.0"))

    # Survival Thresholds
    min_balance_usd: Decimal = Field(default=Decimal("10.00"))
    hosting_cost_usd_per_day: Decimal = Field(default=Decimal("2.50"))
    emergency_shutdown_balance: Decimal = Field(default=Decimal("5.00"))

    # Monitoring
    sentry_dsn: SecretStr | None = None
    prometheus_port: int = 8000

    @property
    def is_live(self) -> bool:
        return self.agent_mode == "live"

    @property
    def is_paper(self) -> bool:
        return self.agent_mode == "paper"


settings = Settings()

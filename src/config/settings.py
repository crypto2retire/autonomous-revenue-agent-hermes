"""Application settings using pydantic-settings."""

from typing import Optional
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

    # Odos Protocol
    odos_api_key: SecretStr = Field(default=SecretStr(""), description="Odos Protocol API key")

    # BaseScan
    basescan_api_key: SecretStr = Field(default=SecretStr(""), description="BaseScan API key")

    # WhatShouldICharge Integration
    wsic_api_key: SecretStr = Field(default=SecretStr(""), description="WhatShouldICharge API key")
    wsic_base_url: str = "https://api.whatshouldicharge.app"

    # Fly.io
    fly_app_name: str = "autonomous-revenue-agent"
    fly_region: str = "ord"

    # Agent Configuration
    agent_name: str = "AutonomousRevenueAgent"
    agent_mode: str = "paper"  # "paper" or "live"
    agent_version: str = "1.0.0"

    # Risk Management
    max_position_pct: Decimal = Decimal("0.10")  # Max 10% of portfolio per position
    min_liquidity_usd: Decimal = Decimal("10000")  # Minimum $10k liquidity
    min_holders: int = 100
    max_slippage_pct: Decimal = Decimal("2.0")

    # Monitoring
    sentry_dsn: Optional[SecretStr] = None
    log_level: str = "INFO"

    @property
    def is_live(self) -> bool:
        return self.agent_mode == "live"

    @property
    def is_paper(self) -> bool:
        return self.agent_mode == "paper"


settings = Settings()

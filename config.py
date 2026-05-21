"""Application configuration."""

import os
from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings
from pydantic import Field, SecretStr


class Settings(BaseSettings):
    """Agent settings loaded from environment."""

    # Venice AI
    venice_api_key: SecretStr = Field(..., description="Venice AI API key")
    venice_model: str = "claude-opus-4.6"
    venice_base_url: str = "https://api.venice.ai/api/v1"

    # Wallet
    base_wallet_private_key: SecretStr = Field(..., description="Base chain private key")
    base_wallet_address: str = Field(..., description="Base chain wallet address")

    # Database
    database_url: SecretStr = Field(..., description="PostgreSQL connection string")

    # Optional APIs
    basescan_api_key: Optional[SecretStr] = None
    wsic_api_key: Optional[SecretStr] = None

    # Trading
    agent_mode: str = Field(default="paper", pattern="^(paper|live)$")
    min_trade_size_usd: float = 10.0
    max_trade_size_usd: float = 1000.0
    max_slippage: float = 0.02
    scan_interval_seconds: int = 300

    # Risk
    max_daily_loss_usd: float = 100.0
    max_positions: int = 10
    stop_loss_pct: float = 0.05
    take_profit_pct: float = 0.10

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    @property
    def is_live(self) -> bool:
        return self.agent_mode == "live"

    @property
    def is_paper(self) -> bool:
        return self.agent_mode == "paper"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()

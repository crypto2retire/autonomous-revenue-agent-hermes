"""Application configuration."""

import os
from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings
from pydantic import Field, SecretStr


class Settings(BaseSettings):
    """Agent settings loaded from environment."""

    # LLM Provider (DeepSeek)
    llm_provider: str = Field(default="deepseek", description="LLM provider: deepseek or venice")
    deepseek_api_key: SecretStr = Field(..., description="DeepSeek API key")
    # Current DeepSeek public model name. The old "deepseek-v4-flash" alias returns 404.
    deepseek_model: str = "deepseek-chat"
    deepseek_base_url: str = "https://api.deepseek.com/v1"

    # Venice AI (fallback)
    venice_api_key: Optional[SecretStr] = None
    venice_model: str = "claude-opus-4.6"
    venice_base_url: str = "https://api.venice.ai/api/v1"

    # Base Chain
    base_wallet_private_key: SecretStr = Field(..., description="Base chain private key")
    base_wallet_address: str = Field(..., description="Base chain wallet address")
    base_rpc: str = "https://mainnet.base.org"

    # Solana Chain
    solana_wallet_private_key: Optional[SecretStr] = Field(None, description="Solana wallet private key (base58)")
    solana_wallet_address: Optional[str] = Field(None, description="Solana wallet address")
    solana_rpc: str = "https://api.mainnet-beta.solana.com"

    # Solana Price/Data APIs
    birdeye_api_key: Optional[SecretStr] = Field(None, description="Birdeye API key for real-time Solana token prices")
    helius_api_key: Optional[SecretStr] = Field(None, description="Helius API key for Solana RPC")
    jupiter_api_key: Optional[SecretStr] = Field(None, description="Jupiter API key for priority quotes")

    # Optional: Turso (cloud SQLite)
    turso_database_url: Optional[str] = Field(None, description="Turso database URL (e.g., libsql://your-db.turso.io)")
    turso_auth_token: Optional[SecretStr] = Field(None, description="Turso auth token")

    # Database
    database_url: SecretStr = Field(default=SecretStr("sqlite:///app.db"), description="Database connection string (PostgreSQL or SQLite)")

    # Render PostgreSQL adds ?sslmode=require — we need to handle that
    @property
    def database_url_clean(self) -> str:
        """Return database URL suitable for async SQLAlchemy."""
        url = self.database_url.get_secret_value()
        # Render PostgreSQL uses postgresql:// — convert to postgresql+asyncpg://
        if url.startswith("postgresql://") and "+asyncpg" not in url:
            url = url.replace("postgresql://", "postgresql+asyncpg://")
        # Remove sslmode=require for asyncpg (it handles SSL differently)
        if "?sslmode=require" in url:
            url = url.replace("?sslmode=require", "")
        elif "&sslmode=require" in url:
            url = url.replace("&sslmode=require", "")
        return url

    # BaseScan
    basescan_api_key: Optional[SecretStr] = None

    # CoinGecko
    coingecko_api_key: Optional[SecretStr] = None
    coingecko_plan: str = "demo"  # "demo" or "pro"

    # Dune Analytics
    dune_api_key: Optional[SecretStr] = None

    # Odos (aggregator)
    odos_api_key: Optional[SecretStr] = None

    # WhatShouldICharge API
    wsic_api_key: Optional[SecretStr] = None

    # Agent mode: "paper" or "live"
    agent_mode: str = "paper"

    # Trading settings
    min_trade_size_usd: float = 10.0
    max_trade_size_usd: float = 1000.0
    max_slippage: float = 0.02
    scan_interval_seconds: int = 300
    chains_to_scan: str = "solana"

    # Risk / Position Management
    max_daily_loss_usd: float = 100.0
    max_positions: int = 10
    stop_loss_pct: float = 0.15
    take_profit_pct: float = 0.25

    # Pump.fun specific settings
    pumpfun_min_liquidity_usd: float = 5000.0
    pumpfun_max_age_hours: int = 24
    pumpfun_profit_target_1: float = 0.25  # 25% profit = sell 60%
    pumpfun_profit_target_2: float = 0.50  # 50% profit = sell 80%
    pumpfun_stop_loss: float = 0.15  # -15% stop loss

    # Sell Agent Settings
    sell_agent_enabled: bool = True
    sell_check_interval_seconds: int = 30
    trailing_stop_enabled: bool = True
    trailing_stop_distance_pct: float = 0.10
    profit_target_1_pct: float = 0.25
    profit_target_1_sell_pct: float = 0.60
    profit_target_2_pct: float = 0.50
    profit_target_2_sell_pct: float = 0.80
    max_hold_hours: int = 168
    underperform_sell_threshold_pct: float = -0.20
    capital_recycle_enabled: bool = True
    min_free_capital_pct: float = 0.20
    emergency_stop_loss_pct: float = 0.30

    # Server settings
    host: str = "0.0.0.0"
    port: int = 8000

    @property
    def is_live(self) -> bool:
        return self.agent_mode == "live"

    @property
    def is_paper(self) -> bool:
        return self.agent_mode == "paper"

    @property
    def enabled_chains(self) -> list:
        return [c.strip().lower() for c in self.chains_to_scan.split(",") if c.strip()]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()

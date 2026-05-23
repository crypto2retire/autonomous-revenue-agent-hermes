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

    # Database
    database_url: SecretStr = Field(..., description="PostgreSQL connection string")

    # BaseScan
    basescan_api_key: Optional[SecretStr] = None

    # Optional APIs
    wsic_api_key: Optional[SecretStr] = None
    odos_api_key: Optional[SecretStr] = Field(None, description="Odos API key for V3 enterprise endpoints")

    # CoinGecko
    coingecko_api_key: Optional[SecretStr] = None
    coingecko_plan: str = Field(default="demo", pattern="^(demo|pro)$")

    # Dune Analytics
    dune_api_key: Optional[SecretStr] = None

    # Trading
    agent_mode: str = Field(default="paper", pattern="^(paper|live)$")
    min_trade_size_usd: float = 10.0
    max_trade_size_usd: float = 1000.0
    max_slippage: float = 0.02
    scan_interval_seconds: int = 300
    chains_to_scan: str = Field(default="base,solana", description="Comma-separated chains to scan")

    # Risk
    max_daily_loss_usd: float = 100.0
    max_positions: int = 10
    stop_loss_pct: float = 0.05
    take_profit_pct: float = 0.10

    # Helius
    helius_api_key: Optional[SecretStr] = Field(None, description="Helius API key for Solana RPC")

    # Server
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

"""Data models for trading opportunities."""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class OpportunityStatus(str, Enum):
    """Status of an opportunity."""
    DISCOVERED = "discovered"
    ANALYZING = "analyzing"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    EXECUTED = "executed"
    FAILED = "failed"
    CLOSED = "closed"


class HolderMetrics(BaseModel):
    """On-chain holder metrics for a token."""
    total_holders: int = Field(..., description="Total number of holders")
    new_holders_24h: int = Field(..., description="New holders in last 24h")
    new_holders_7d: int = Field(..., description="New holders in last 7d")
    active_holders_24h: int = Field(..., description="Holders with activity in 24h")
    concentration_top_10: Decimal = Field(..., description="% held by top 10 wallets")
    concentration_top_50: Decimal = Field(..., description="% held by top 50 wallets")
    smart_money_inflows_24h: Decimal = Field(..., description="Smart money inflow USD")
    smart_money_outflows_24h: Decimal = Field(..., description="Smart money outflow USD")
    avg_hold_time_days: Decimal = Field(..., description="Average hold time")
    holder_growth_rate: Decimal = Field(..., description="Holder growth rate %")


class VolumeMetrics(BaseModel):
    """Volume and liquidity metrics."""
    volume_24h_usd: Decimal = Field(..., description="24h trading volume")
    volume_7d_usd: Decimal = Field(..., description="7d trading volume")
    volume_change_24h_pct: Decimal = Field(..., description="Volume change %")
    buy_volume_24h_usd: Decimal = Field(..., description="Buy volume 24h")
    sell_volume_24h_usd: Decimal = Field(..., description="Sell volume 24h")
    buy_sell_ratio: Decimal = Field(..., description="Buy/sell ratio")
    liquidity_usd: Decimal = Field(..., description="Total liquidity")
    liquidity_change_24h_pct: Decimal = Field(..., description="Liquidity change %")
    unique_traders_24h: int = Field(..., description="Unique traders 24h")
    avg_trade_size_usd: Decimal = Field(..., description="Average trade size")


class Opportunity(BaseModel):
    """A discovered trading opportunity."""
    id: Optional[str] = None
    token_address: str = Field(..., description="Token contract address")
    token_symbol: str = Field(..., description="Token symbol")
    token_name: str = Field(..., description="Token name")
    chain: str = Field(default="base", description="Blockchain")
    
    # Price data
    current_price_usd: Decimal = Field(..., description="Current price")
    price_change_24h_pct: Decimal = Field(..., description="24h price change %")
    price_change_7d_pct: Decimal = Field(..., description="7d price change %")
    market_cap_usd: Optional[Decimal] = None
    fdv_usd: Optional[Decimal] = None
    
    # Key metrics
    holder_metrics: HolderMetrics
    volume_metrics: VolumeMetrics
    
    # AI Analysis
    ai_signal: Optional[str] = None
    ai_confidence: Optional[Decimal] = None
    ai_reasoning: Optional[str] = None
    ai_risk_level: Optional[str] = None
    suggested_position_size_pct: Optional[Decimal] = None
    
    # Execution
    status: OpportunityStatus = OpportunityStatus.DISCOVERED
    entry_price: Optional[Decimal] = None
    exit_price: Optional[Decimal] = None
    position_size_usd: Optional[Decimal] = None
    pnl_usd: Optional[Decimal] = None
    pnl_pct: Optional[Decimal] = None
    
    # Metadata
    discovered_at: datetime = Field(default_factory=datetime.utcnow)
    executed_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    
    # Source
    data_source: str = Field(default="on_chain", description="Where discovered")
    scanner_version: str = Field(default="1.0.0")


class OpportunityFilter(BaseModel):
    """Filter criteria for opportunities."""
    min_holders: int = Field(default=10)
    min_volume_24h_usd: Decimal = Field(default=Decimal("1000"))
    min_liquidity_usd: Decimal = Field(default=Decimal("5000"))
    max_concentration_top_10: Decimal = Field(default=Decimal("80.0"))
    min_holder_growth_rate: Decimal = Field(default=Decimal("-100.0"))
    min_buy_sell_ratio: Decimal = Field(default=Decimal("0.5"))
    chains: list[str] = Field(default=["base", "solana", "ethereum"])
    exclude_tokens: list[str] = Field(default_factory=list)

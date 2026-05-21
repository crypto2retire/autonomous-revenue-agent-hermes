"""SQLAlchemy models for persistent agent data storage."""

from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum

from sqlalchemy import (
    Column, Integer, String, DateTime, Numeric, Text,
    Boolean, ForeignKey, Index, create_engine,
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

Base = declarative_base()


class TradeStatus(str, PyEnum):
    """Trade execution status."""
    PENDING = "pending"
    EXECUTED = "executed"
    FAILED = "failed"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class TradeType(str, PyEnum):
    """Trade direction."""
    BUY = "buy"
    SELL = "sell"


class TradeRecord(Base):
    """A executed or attempted trade."""
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True)
    trade_id = Column(String(64), unique=True, nullable=False, index=True)

    # Token info
    token_address = Column(String(42), nullable=False, index=True)
    token_symbol = Column(String(20), nullable=False)
    token_name = Column(String(100))
    chain = Column(String(20), default="base")

    # Trade details
    trade_type = Column(String(10), nullable=False)  # buy / sell
    status = Column(String(20), nullable=False, default="pending")
    mode = Column(String(10), nullable=False, default="paper")  # paper / live

    # Pricing
    entry_price = Column(Numeric(36, 18))
    exit_price = Column(Numeric(36, 18))
    position_size_usd = Column(Numeric(36, 6))
    quantity = Column(Numeric(36, 18))

    # P&L
    pnl_usd = Column(Numeric(36, 6), default=Decimal("0"))
    pnl_pct = Column(Numeric(10, 4), default=Decimal("0"))
    fees_usd = Column(Numeric(36, 6), default=Decimal("0"))

    # Execution
    tx_hash = Column(String(66), unique=True, nullable=True)
    executed_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

    # Metadata
    ai_signal = Column(String(10))
    ai_confidence = Column(Numeric(5, 4))
    ai_risk_level = Column(String(10))
    ai_reasoning = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    transactions = relationship("TransactionRecord", back_populates="trade", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_trades_status_created", "status", "created_at"),
        Index("ix_trades_token_created", "token_address", "created_at"),
    )


class TransactionRecord(Base):
    """On-chain or paper transaction record."""
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True)
    tx_id = Column(String(64), unique=True, nullable=False, index=True)

    # Link to trade
    trade_id = Column(String(64), ForeignKey("trades.trade_id"), nullable=True, index=True)

    # Transaction details
    tx_hash = Column(String(66), unique=True, nullable=True)
    tx_type = Column(String(20), nullable=False)  # swap, approve, transfer, fee, etc.
    status = Column(String(20), nullable=False, default="pending")  # pending, confirmed, failed

    # Token / asset
    token_address = Column(String(42), nullable=False, index=True)
    token_symbol = Column(String(20))
    chain = Column(String(20), default="base")

    # Amounts
    amount_in = Column(Numeric(36, 18))
    amount_out = Column(Numeric(36, 18))
    amount_usd = Column(Numeric(36, 6))
    fee_eth = Column(Numeric(36, 18))
    fee_usd = Column(Numeric(36, 6))

    # Addresses
    from_address = Column(String(42))
    to_address = Column(String(42))

    # Block info
    block_number = Column(Integer)
    block_timestamp = Column(DateTime)
    confirmations = Column(Integer, default=0)

    # Metadata
    mode = Column(String(10), default="paper")
    error_message = Column(Text)
    raw_data = Column(Text)  # JSON blob for extra data

    created_at = Column(DateTime, default=datetime.utcnow)
    confirmed_at = Column(DateTime)

    # Relationships
    trade = relationship("TradeRecord", back_populates="transactions")

    __table_args__ = (
        Index("ix_txs_status_created", "status", "created_at"),
        Index("ix_txs_type_created", "tx_type", "created_at"),
    )


class OpportunityRecord(Base):
    """Discovered opportunity stored for history and analysis."""
    __tablename__ = "opportunities"

    id = Column(Integer, primary_key=True)
    opp_id = Column(String(64), unique=True, nullable=False, index=True)

    # Token
    token_address = Column(String(42), nullable=False, index=True)
    token_symbol = Column(String(20), nullable=False)
    token_name = Column(String(100))
    chain = Column(String(20), default="base")

    # Price at discovery
    price_usd = Column(Numeric(36, 18))
    price_change_24h_pct = Column(Numeric(10, 4))
    price_change_7d_pct = Column(Numeric(10, 4))
    market_cap_usd = Column(Numeric(36, 2))
    fdv_usd = Column(Numeric(36, 2))

    # Volume metrics
    volume_24h_usd = Column(Numeric(36, 2))
    volume_7d_usd = Column(Numeric(36, 2))
    volume_change_24h_pct = Column(Numeric(10, 4))
    buy_volume_24h_usd = Column(Numeric(36, 2))
    sell_volume_24h_usd = Column(Numeric(36, 2))
    buy_sell_ratio = Column(Numeric(10, 4))
    liquidity_usd = Column(Numeric(36, 2))
    liquidity_change_24h_pct = Column(Numeric(10, 4))
    unique_traders_24h = Column(Integer)
    avg_trade_size_usd = Column(Numeric(36, 2))

    # Holder metrics
    total_holders = Column(Integer)
    new_holders_24h = Column(Integer)
    new_holders_7d = Column(Integer)
    active_holders_24h = Column(Integer)
    concentration_top_10 = Column(Numeric(5, 2))
    concentration_top_50 = Column(Numeric(5, 2))
    smart_money_inflows_24h = Column(Numeric(36, 2))
    smart_money_outflows_24h = Column(Numeric(36, 2))
    avg_hold_time_days = Column(Numeric(10, 2))
    holder_growth_rate = Column(Numeric(10, 4))

    # AI analysis
    ai_signal = Column(String(10))
    ai_confidence = Column(Numeric(5, 4))
    ai_risk_level = Column(String(10))
    ai_reasoning = Column(Text)
    suggested_position_size_pct = Column(Numeric(5, 4))

    # Outcome
    trade_executed = Column(Boolean, default=False)
    trade_id = Column(String(64), ForeignKey("trades.trade_id"), nullable=True)
    pnl_usd = Column(Numeric(36, 6))
    pnl_pct = Column(Numeric(10, 4))

    discovered_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_opps_signal_discovered", "ai_signal", "discovered_at"),
        Index("ix_opps_token_discovered", "token_address", "discovered_at"),
    )


class WalletSnapshot(Base):
    """Periodic wallet balance snapshot."""
    __tablename__ = "wallet_snapshots"

    id = Column(Integer, primary_key=True)
    wallet_address = Column(String(42), nullable=False, index=True)
    chain = Column(String(20), default="base")

    # Balances
    eth_balance = Column(Numeric(36, 18))
    eth_price_usd = Column(Numeric(36, 6))
    total_balance_usd = Column(Numeric(36, 6))

    # Token breakdown (stored as JSON in raw_data)
    token_count = Column(Integer, default=0)
    raw_data = Column(Text)

    snapshot_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_wallet_snapshots_address_at", "wallet_address", "snapshot_at"),
    )


class AgentLog(Base):
    """Structured log entry from the agent."""
    __tablename__ = "agent_logs"

    id = Column(Integer, primary_key=True)
    log_id = Column(String(64), unique=True, nullable=False, index=True)

    # Log content
    logger_name = Column(String(100), nullable=False)
    level = Column(String(10), nullable=False, index=True)  # INFO, WARNING, ERROR, CRITICAL
    event = Column(String(100), nullable=False, index=True)
    message = Column(Text)

    # Context
    cycle = Column(Integer)
    token_address = Column(String(42))
    trade_id = Column(String(64))
    tx_hash = Column(String(66))

    # Structured data (JSON)
    raw_data = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_logs_level_created", "level", "created_at"),
        Index("ix_logs_event_created", "event", "created_at"),
        Index("ix_logs_logger_created", "logger_name", "created_at"),
    )


class PerformanceMetric(Base):
    """Aggregated performance metrics per cycle / day."""
    __tablename__ = "performance_metrics"

    id = Column(Integer, primary_key=True)
    metric_id = Column(String(64), unique=True, nullable=False, index=True)

    # Period
    period_type = Column(String(10), nullable=False, default="cycle")  # cycle, day, week
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)

    # Trading
    trades_executed = Column(Integer, default=0)
    trades_closed = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    total_pnl_usd = Column(Numeric(36, 6), default=Decimal("0"))
    total_fees_usd = Column(Numeric(36, 6), default=Decimal("0"))
    max_drawdown_pct = Column(Numeric(10, 4), default=Decimal("0"))

    # Portfolio
    starting_balance_usd = Column(Numeric(36, 6))
    ending_balance_usd = Column(Numeric(36, 6))
    open_positions_count = Column(Integer, default=0)

    # Opportunities
    opportunities_found = Column(Integer, default=0)
    opportunities_executed = Column(Integer, default=0)

    # Services
    service_revenue_usd = Column(Numeric(36, 6), default=Decimal("0"))
    service_requests = Column(Integer, default=0)

    # Costs
    hosting_cost_usd = Column(Numeric(36, 6), default=Decimal("0"))
    api_cost_usd = Column(Numeric(36, 6), default=Decimal("0"))

    # Agent state
    cycle_count = Column(Integer)
    trading_enabled = Column(Boolean, default=True)
    survival_mode = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_perf_period", "period_type", "period_start"),
    )


class OpenPosition(Base):
    """Currently open trading position."""
    __tablename__ = "open_positions"

    id = Column(Integer, primary_key=True)
    position_id = Column(String(64), unique=True, nullable=False, index=True)
    trade_id = Column(String(64), ForeignKey("trades.trade_id"), nullable=False, unique=True)

    # Token
    token_address = Column(String(42), nullable=False, index=True)
    token_symbol = Column(String(20), nullable=False)
    chain = Column(String(20), default="base")

    # Position details
    entry_price = Column(Numeric(36, 18), nullable=False)
    current_price = Column(Numeric(36, 18))
    position_size_usd = Column(Numeric(36, 6), nullable=False)
    quantity = Column(Numeric(36, 18))
    unrealized_pnl_usd = Column(Numeric(36, 6), default=Decimal("0"))
    unrealized_pnl_pct = Column(Numeric(10, 4), default=Decimal("0"))

    # Risk
    stop_loss_price = Column(Numeric(36, 18))
    take_profit_price = Column(Numeric(36, 18))
    highest_price = Column(Numeric(36, 18))
    max_drawdown_pct = Column(Numeric(10, 4), default=Decimal("0"))

    # Status
    mode = Column(String(10), default="paper")
    status = Column(String(20), default="open")  # open, closing, closed

    opened_at = Column(DateTime, default=datetime.utcnow)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_positions_status", "status", "last_updated"),
    )

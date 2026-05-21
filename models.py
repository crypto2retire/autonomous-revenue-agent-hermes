"""Database models for the crypto trading agent."""

from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum

from sqlalchemy import (
    Column, Integer, String, DateTime, Numeric, Text,
    Boolean, Index
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Signal(str, PyEnum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    AVOID = "avoid"


class TradeStatus(str, PyEnum):
    PENDING = "pending"
    EXECUTED = "executed"
    FAILED = "failed"
    CLOSED = "closed"


def _f(val):
    """Safely convert Numeric/Decimal to float."""
    if val is None:
        return None
    return float(val)


class CoinWatch(Base):
    """Every coin the scanner has ever seen — the watchlist."""
    __tablename__ = "coin_watch"

    id = Column(Integer, primary_key=True)
    token_address = Column(String(66), nullable=False, index=True)
    chain = Column(String(20), default="base")
    symbol = Column(String(20))
    name = Column(String(100))
    first_seen_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    last_seen_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    first_price_usd = Column(Numeric(24, 12))
    last_price_usd = Column(Numeric(24, 12))
    price_change_pct = Column(Numeric(10, 4))
    volume_24h = Column(Numeric(24, 6))
    liquidity_usd = Column(Numeric(24, 6))
    market_cap = Column(Numeric(24, 6))
    holder_count = Column(Integer)
    signal = Column(String(20))
    confidence = Column(Numeric(5, 4))
    ai_analysis = Column(Text)
    scan_count = Column(Integer, default=1)
    is_watching = Column(Boolean, default=True)
    tags = Column(Text)

    __table_args__ = (
        Index("idx_coin_watch_symbol", "symbol"),
        Index("idx_coin_watch_signal", "signal"),
        Index("idx_coin_watch_tags", "tags"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "token_address": self.token_address,
            "chain": self.chain,
            "symbol": self.symbol,
            "name": self.name,
            "first_seen_at": self.first_seen_at.isoformat() if self.first_seen_at else None,
            "last_seen_at": self.last_seen_at.isoformat() if self.last_seen_at else None,
            "first_price_usd": _f(self.first_price_usd),
            "last_price_usd": _f(self.last_price_usd),
            "price_change_pct": _f(self.price_change_pct),
            "volume_24h": _f(self.volume_24h),
            "liquidity_usd": _f(self.liquidity_usd),
            "market_cap": _f(self.market_cap),
            "holder_count": self.holder_count,
            "signal": self.signal,
            "confidence": _f(self.confidence),
            "ai_analysis": self.ai_analysis,
            "scan_count": self.scan_count,
            "is_watching": self.is_watching,
            "tags": self.tags,
        }


class Trade(Base):
    """Executed trades."""
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True)
    trade_id = Column(String(50), unique=True, index=True)
    token_address = Column(String(66), nullable=False, index=True)
    symbol = Column(String(20))
    side = Column(String(10))
    status = Column(String(20), default=TradeStatus.PENDING)
    amount_token = Column(Numeric(24, 12))
    amount_usd = Column(Numeric(16, 6))
    entry_price = Column(Numeric(24, 12))
    exit_price = Column(Numeric(24, 12))
    pnl_usd = Column(Numeric(16, 6))
    pnl_pct = Column(Numeric(10, 4))
    tx_hash = Column(String(100))
    signal = Column(String(20))
    confidence = Column(Numeric(5, 4))
    is_paper = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    executed_at = Column(DateTime(timezone=True))
    closed_at = Column(DateTime(timezone=True))
    close_reason = Column(String(50))

    __table_args__ = (
        Index("idx_trades_status", "status"),
        Index("idx_trades_created", "created_at"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "trade_id": self.trade_id,
            "token_address": self.token_address,
            "symbol": self.symbol,
            "side": self.side,
            "status": self.status,
            "amount_token": _f(self.amount_token),
            "amount_usd": _f(self.amount_usd),
            "entry_price": _f(self.entry_price),
            "exit_price": _f(self.exit_price),
            "pnl_usd": _f(self.pnl_usd),
            "pnl_pct": _f(self.pnl_pct),
            "tx_hash": self.tx_hash,
            "signal": self.signal,
            "confidence": _f(self.confidence),
            "is_paper": self.is_paper,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
            "close_reason": self.close_reason,
        }


class WalletSnapshot(Base):
    """Periodic wallet balance snapshots."""
    __tablename__ = "wallet_snapshots"

    id = Column(Integer, primary_key=True)
    address = Column(String(66), nullable=False)
    chain = Column(String(20), default="base")
    eth_balance = Column(Numeric(24, 12))
    eth_price_usd = Column(Numeric(16, 6))
    total_usd = Column(Numeric(16, 6))
    token_balances = Column(Text)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "address": self.address,
            "chain": self.chain,
            "eth_balance": _f(self.eth_balance),
            "eth_price_usd": _f(self.eth_price_usd),
            "total_usd": _f(self.total_usd),
            "token_balances": self.token_balances,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AgentLog(Base):
    """Structured agent logs."""
    __tablename__ = "agent_logs"

    id = Column(Integer, primary_key=True)
    level = Column(String(10), default="info")
    event = Column(String(100), nullable=False)
    message = Column(Text)
    token_address = Column(String(66), index=True)
    symbol = Column(String(20))
    data = Column(Text)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    __table_args__ = (
        Index("idx_logs_event", "event"),
        Index("idx_logs_created", "created_at"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "level": self.level,
            "event": self.event,
            "message": self.message,
            "token_address": self.token_address,
            "symbol": self.symbol,
            "data": self.data,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class PerformanceMetric(Base):
    """Daily / hourly performance metrics."""
    __tablename__ = "performance_metrics"

    id = Column(Integer, primary_key=True)
    period = Column(String(20))
    period_start = Column(DateTime(timezone=True))
    trades_count = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    total_pnl_usd = Column(Numeric(16, 6))
    total_fees_usd = Column(Numeric(16, 6))
    win_rate = Column(Numeric(5, 4))
    avg_trade_size = Column(Numeric(16, 6))
    max_drawdown_pct = Column(Numeric(10, 4))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "period": self.period,
            "period_start": self.period_start.isoformat() if self.period_start else None,
            "trades_count": self.trades_count,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "total_pnl_usd": _f(self.total_pnl_usd),
            "total_fees_usd": _f(self.total_fees_usd),
            "win_rate": _f(self.win_rate),
            "avg_trade_size": _f(self.avg_trade_size),
            "max_drawdown_pct": _f(self.max_drawdown_pct),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

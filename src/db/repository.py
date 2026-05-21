"""Repository layer for all agent database operations.

Provides async CRUD operations for trades, transactions, opportunities,
wallet snapshots, logs, performance metrics, and open positions.
"""

import json
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, List, Dict, Any

from sqlalchemy import select, desc, func, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import settings
from src.db.models import (
    Base,
    TradeRecord,
    TransactionRecord,
    OpportunityRecord,
    WalletSnapshot,
    AgentLog,
    PerformanceMetric,
    OpenPosition,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


class AgentRepository:
    """Central repository for all agent data persistence."""

    def __init__(self, database_url: str = None):
        raw_url = database_url or settings.database_url.get_secret_value()
        # Ensure asyncpg driver
        if raw_url.startswith("postgresql://"):
            self.database_url = raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        else:
            self.database_url = raw_url

        self.engine = None
        self.Session = None
        self._initialized = False

    async def initialize(self):
        """Create tables and session factory."""
        if self._initialized:
            return

        try:
            self.engine = create_async_engine(self.database_url, echo=False)
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            self.Session = async_sessionmaker(
                self.engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )
            self._initialized = True
            logger.info("db_repository_initialized")
        except Exception as e:
            logger.error("db_repository_init_failed", error=str(e))
            raise

    async def close(self):
        """Dispose engine."""
        if self.engine:
            await self.engine.dispose()
            logger.info("db_repository_closed")

    # ── Helpers ──────────────────────────────────────────────────────────

    def _generate_id(self, prefix: str = "") -> str:
        return f"{prefix}{uuid.uuid4().hex[:16]}"

    # ═════════════════════════════════════════════════════════════════════
    # TRADES
    # ═════════════════════════════════════════════════════════════════════

    async def create_trade(self, **kwargs) -> TradeRecord:
        """Create a new trade record."""
        trade_id = kwargs.get("trade_id") or self._generate_id("trd_")
        trade = TradeRecord(trade_id=trade_id, **kwargs)
        async with self.Session() as session:
            session.add(trade)
            await session.commit()
            await session.refresh(trade)
        logger.info("trade_recorded", trade_id=trade_id, token=kwargs.get("token_symbol"))
        return trade

    async def get_trade(self, trade_id: str) -> Optional[TradeRecord]:
        async with self.Session() as session:
            result = await session.execute(
                select(TradeRecord).where(TradeRecord.trade_id == trade_id)
            )
            return result.scalar_one_or_none()

    async def update_trade(self, trade_id: str, **kwargs) -> Optional[TradeRecord]:
        async with self.Session() as session:
            result = await session.execute(
                select(TradeRecord).where(TradeRecord.trade_id == trade_id)
            )
            trade = result.scalar_one_or_none()
            if not trade:
                return None
            for key, value in kwargs.items():
                if hasattr(trade, key):
                    setattr(trade, key, value)
            trade.updated_at = datetime.utcnow()
            await session.commit()
            await session.refresh(trade)
            return trade

    async def list_trades(
        self,
        status: str = None,
        token_address: str = None,
        mode: str = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[TradeRecord]:
        async with self.Session() as session:
            q = select(TradeRecord).order_by(desc(TradeRecord.created_at))
            if status:
                q = q.where(TradeRecord.status == status)
            if token_address:
                q = q.where(TradeRecord.token_address == token_address)
            if mode:
                q = q.where(TradeRecord.mode == mode)
            q = q.limit(limit).offset(offset)
            result = await session.execute(q)
            return result.scalars().all()

    async def get_trade_stats(self) -> Dict[str, Any]:
        async with self.Session() as session:
            total = await session.execute(select(func.count()).select_from(TradeRecord))
            total_count = total.scalar()

            executed = await session.execute(
                select(func.count()).select_from(TradeRecord).where(TradeRecord.status == "executed")
            )
            executed_count = executed.scalar()

            closed = await session.execute(
                select(func.count()).select_from(TradeRecord).where(TradeRecord.status == "closed")
            )
            closed_count = closed.scalar()

            total_pnl = await session.execute(
                select(func.coalesce(func.sum(TradeRecord.pnl_usd), Decimal("0")))
            )
            total_pnl_val = total_pnl.scalar()

            winning = await session.execute(
                select(func.count()).select_from(TradeRecord).where(TradeRecord.pnl_usd > 0)
            )
            winning_count = winning.scalar()

            return {
                "total_trades": total_count,
                "executed": executed_count,
                "closed": closed_count,
                "winning": winning_count,
                "losing": closed_count - winning_count if closed_count else 0,
                "total_pnl_usd": float(total_pnl_val) if total_pnl_val else 0,
                "win_rate": (winning_count / closed_count * 100) if closed_count else 0,
            }

    # ═════════════════════════════════════════════════════════════════════
    # TRANSACTIONS
    # ═════════════════════════════════════════════════════════════════════

    async def create_transaction(self, **kwargs) -> TransactionRecord:
        tx_id = kwargs.get("tx_id") or self._generate_id("tx_")
        tx = TransactionRecord(tx_id=tx_id, **kwargs)
        async with self.Session() as session:
            session.add(tx)
            await session.commit()
            await session.refresh(tx)
        return tx

    async def list_transactions(
        self,
        trade_id: str = None,
        status: str = None,
        tx_type: str = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[TransactionRecord]:
        async with self.Session() as session:
            q = select(TransactionRecord).order_by(desc(TransactionRecord.created_at))
            if trade_id:
                q = q.where(TransactionRecord.trade_id == trade_id)
            if status:
                q = q.where(TransactionRecord.status == status)
            if tx_type:
                q = q.where(TransactionRecord.tx_type == tx_type)
            q = q.limit(limit).offset(offset)
            result = await session.execute(q)
            return result.scalars().all()

    # ═════════════════════════════════════════════════════════════════════
    # OPPORTUNITIES
    # ═════════════════════════════════════════════════════════════════════

    async def create_opportunity(self, **kwargs) -> OpportunityRecord:
        opp_id = kwargs.get("opp_id") or self._generate_id("opp_")
        opp = OpportunityRecord(opp_id=opp_id, **kwargs)
        async with self.Session() as session:
            session.add(opp)
            await session.commit()
            await session.refresh(opp)
        return opp

    async def list_opportunities(
        self,
        ai_signal: str = None,
        token_address: str = None,
        trade_executed: bool = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[OpportunityRecord]:
        async with self.Session() as session:
            q = select(OpportunityRecord).order_by(desc(OpportunityRecord.discovered_at))
            if ai_signal:
                q = q.where(OpportunityRecord.ai_signal == ai_signal)
            if token_address:
                q = q.where(OpportunityRecord.token_address == token_address)
            if trade_executed is not None:
                q = q.where(OpportunityRecord.trade_executed == trade_executed)
            q = q.limit(limit).offset(offset)
            result = await session.execute(q)
            return result.scalars().all()

    async def update_opportunity(self, opp_id: str, **kwargs) -> Optional[OpportunityRecord]:
        async with self.Session() as session:
            result = await session.execute(
                select(OpportunityRecord).where(OpportunityRecord.opp_id == opp_id)
            )
            opp = result.scalar_one_or_none()
            if not opp:
                return None
            for key, value in kwargs.items():
                if hasattr(opp, key):
                    setattr(opp, key, value)
            opp.updated_at = datetime.utcnow()
            await session.commit()
            await session.refresh(opp)
            return opp

    # ═════════════════════════════════════════════════════════════════════
    # WALLET SNAPSHOTS
    # ═════════════════════════════════════════════════════════════════════

    async def create_wallet_snapshot(self, **kwargs) -> WalletSnapshot:
        snap = WalletSnapshot(**kwargs)
        async with self.Session() as session:
            session.add(snap)
            await session.commit()
            await session.refresh(snap)
        return snap

    async def get_latest_wallet_snapshot(self, wallet_address: str) -> Optional[WalletSnapshot]:
        async with self.Session() as session:
            result = await session.execute(
                select(WalletSnapshot)
                .where(WalletSnapshot.wallet_address == wallet_address)
                .order_by(desc(WalletSnapshot.snapshot_at))
                .limit(1)
            )
            return result.scalar_one_or_none()

    async def get_wallet_history(
        self, wallet_address: str, hours: int = 168, limit: int = 500
    ) -> List[WalletSnapshot]:
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        async with self.Session() as session:
            result = await session.execute(
                select(WalletSnapshot)
                .where(
                    and_(
                        WalletSnapshot.wallet_address == wallet_address,
                        WalletSnapshot.snapshot_at >= cutoff,
                    )
                )
                .order_by(WalletSnapshot.snapshot_at)
                .limit(limit)
            )
            return result.scalars().all()

    # ═════════════════════════════════════════════════════════════════════
    # AGENT LOGS
    # ═════════════════════════════════════════════════════════════════════

    async def create_log(self, **kwargs) -> AgentLog:
        log_id = kwargs.get("log_id") or self._generate_id("log_")
        log = AgentLog(log_id=log_id, **kwargs)
        async with self.Session() as session:
            session.add(log)
            await session.commit()
            await session.refresh(log)
        return log

    async def list_logs(
        self,
        level: str = None,
        event: str = None,
        limit: int = 200,
        offset: int = 0,
    ) -> List[AgentLog]:
        async with self.Session() as session:
            q = select(AgentLog).order_by(desc(AgentLog.created_at))
            if level:
                q = q.where(AgentLog.level == level)
            if event:
                q = q.where(AgentLog.event == event)
            q = q.limit(limit).offset(offset)
            result = await session.execute(q)
            return result.scalars().all()

    async def cleanup_old_logs(self, days: int = 30):
        cutoff = datetime.utcnow() - timedelta(days=days)
        async with self.Session() as session:
            result = await session.execute(
                delete(AgentLog).where(AgentLog.created_at < cutoff)
            )
            await session.commit()
            logger.info("old_logs_cleaned", days=days, deleted=result.rowcount)

    # ═════════════════════════════════════════════════════════════════════
    # PERFORMANCE METRICS
    # ═════════════════════════════════════════════════════════════════════

    async def create_performance_metric(self, **kwargs) -> PerformanceMetric:
        metric_id = kwargs.get("metric_id") or self._generate_id("perf_")
        metric = PerformanceMetric(metric_id=metric_id, **kwargs)
        async with self.Session() as session:
            session.add(metric)
            await session.commit()
            await session.refresh(metric)
        return metric

    async def get_latest_performance(self) -> Optional[PerformanceMetric]:
        async with self.Session() as session:
            result = await session.execute(
                select(PerformanceMetric)
                .order_by(desc(PerformanceMetric.created_at))
                .limit(1)
            )
            return result.scalar_one_or_none()

    async def get_performance_history(
        self, period_type: str = "day", limit: int = 30
    ) -> List[PerformanceMetric]:
        async with self.Session() as session:
            result = await session.execute(
                select(PerformanceMetric)
                .where(PerformanceMetric.period_type == period_type)
                .order_by(desc(PerformanceMetric.period_start))
                .limit(limit)
            )
            return result.scalars().all()

    # ═════════════════════════════════════════════════════════════════════
    # OPEN POSITIONS
    # ═════════════════════════════════════════════════════════════════════

    async def create_open_position(self, **kwargs) -> OpenPosition:
        pos_id = kwargs.get("position_id") or self._generate_id("pos_")
        pos = OpenPosition(position_id=pos_id, **kwargs)
        async with self.Session() as session:
            session.add(pos)
            await session.commit()
            await session.refresh(pos)
        return pos

    async def get_open_position(self, position_id: str) -> Optional[OpenPosition]:
        async with self.Session() as session:
            result = await session.execute(
                select(OpenPosition).where(OpenPosition.position_id == position_id)
            )
            return result.scalar_one_or_none()

    async def list_open_positions(
        self, status: str = "open", limit: int = 100
    ) -> List[OpenPosition]:
        async with self.Session() as session:
            q = (
                select(OpenPosition)
                .where(OpenPosition.status == status)
                .order_by(desc(OpenPosition.opened_at))
                .limit(limit)
            )
            result = await session.execute(q)
            return result.scalars().all()

    async def update_open_position(self, position_id: str, **kwargs) -> Optional[OpenPosition]:
        async with self.Session() as session:
            result = await session.execute(
                select(OpenPosition).where(OpenPosition.position_id == position_id)
            )
            pos = result.scalar_one_or_none()
            if not pos:
                return None
            for key, value in kwargs.items():
                if hasattr(pos, key):
                    setattr(pos, key, value)
            pos.last_updated = datetime.utcnow()
            await session.commit()
            await session.refresh(pos)
            return pos

    async def close_open_position(self, position_id: str, **kwargs) -> Optional[OpenPosition]:
        return await self.update_open_position(
            position_id, status="closed", **kwargs
        )

    async def get_position_summary(self) -> Dict[str, Any]:
        async with self.Session() as session:
            open_count = await session.execute(
                select(func.count())
                .select_from(OpenPosition)
                .where(OpenPosition.status == "open")
            )
            total_unrealized = await session.execute(
                select(func.coalesce(func.sum(OpenPosition.unrealized_pnl_usd), Decimal("0")))
                .where(OpenPosition.status == "open")
            )
            return {
                "open_positions": open_count.scalar(),
                "unrealized_pnl_usd": float(total_unrealized.scalar() or 0),
            }

"""Historical data tracking for holder growth and volume change calculations."""

from decimal import Decimal
from datetime import datetime, timedelta
from typing import Any, Optional
from collections import defaultdict

from sqlalchemy import (
    create_engine, Column, String, DateTime, Numeric, Integer,
    select, desc, func
)
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from src.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

Base = declarative_base()


class TokenSnapshot(Base):
    """Historical snapshot of token metrics."""
    __tablename__ = "token_snapshots"

    id = Column(Integer, primary_key=True)
    token_address = Column(String(42), nullable=False, index=True)
    chain = Column(String(20), default="base")
    
    # Price data
    price_usd = Column(Numeric(36, 18))
    market_cap = Column(Numeric(36, 2))
    fdv = Column(Numeric(36, 2))
    
    # Holder metrics
    total_holders = Column(Integer)
    concentration_top_10 = Column(Numeric(5, 2))
    concentration_top_50 = Column(Numeric(5, 2))
    
    # Volume metrics
    volume_24h = Column(Numeric(36, 2))
    liquidity_usd = Column(Numeric(36, 2))
    buy_sell_ratio = Column(Numeric(10, 4))
    
    # Metadata
    snapshot_at = Column(DateTime, default=datetime.utcnow, index=True)
    data_source = Column(String(50), default="combined")


class HistoricalTracker:
    """Tracks historical token data for trend analysis.
    
    Stores snapshots in PostgreSQL and calculates:
    - Holder growth rate (24h, 7d)
    - Volume change (24h, 7d)
    - Price momentum
    - Liquidity trends
    """

    def __init__(self, database_url: str = None):
        self.database_url = database_url or settings.database_url.get_secret_value()
        # Convert to async URL if needed
        if self.database_url.startswith("postgresql://"):
            self.async_url = self.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        else:
            self.async_url = self.database_url
        
        self.engine = None
        self.async_engine = None
        self.Session = None
        self._initialized = False

    async def initialize(self):
        """Initialize database tables."""
        if self._initialized:
            return

        try:
            self.async_engine = create_async_engine(self.async_url)
            async with self.async_engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            
            self.Session = async_sessionmaker(
                self.async_engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )
            
            self._initialized = True
            logger.info("historical_tracker_initialized")
            
        except Exception as e:
            logger.error("historical_tracker_init_failed", error=str(e))
            # Fallback to in-memory storage
            self._memory_storage = defaultdict(list)
            self._initialized = True

    async def store_snapshot(
        self,
        token_address: str,
        chain: str,
        price_usd: Decimal,
        total_holders: int,
        volume_24h: Decimal,
        liquidity_usd: Decimal,
        market_cap: Optional[Decimal] = None,
        fdv: Optional[Decimal] = None,
        concentration_top_10: Optional[Decimal] = None,
        concentration_top_50: Optional[Decimal] = None,
        buy_sell_ratio: Optional[Decimal] = None,
    ):
        """Store a new snapshot for a token."""
        snapshot = TokenSnapshot(
            token_address=token_address.lower(),
            chain=chain,
            price_usd=price_usd,
            total_holders=total_holders,
            volume_24h=volume_24h,
            liquidity_usd=liquidity_usd,
            market_cap=market_cap,
            fdv=fdv,
            concentration_top_10=concentration_top_10,
            concentration_top_50=concentration_top_50,
            buy_sell_ratio=buy_sell_ratio,
            snapshot_at=datetime.utcnow(),
        )

        if hasattr(self, '_memory_storage'):
            # In-memory fallback
            self._memory_storage[token_address.lower()].append({
                "price_usd": price_usd,
                "total_holders": total_holders,
                "volume_24h": volume_24h,
                "liquidity_usd": liquidity_usd,
                "snapshot_at": datetime.utcnow(),
            })
            return

        try:
            async with self.Session() as session:
                session.add(snapshot)
                await session.commit()
                
            logger.debug(
                "snapshot_stored",
                token=token_address,
                holders=total_holders,
                volume=float(volume_24h),
            )
            
        except Exception as e:
            logger.error("snapshot_store_failed", token=token_address, error=str(e))

    async def get_holder_growth_rate(
        self,
        token_address: str,
        hours: int = 24,
    ) -> Decimal:
        """Calculate holder growth rate over time period.
        
        Returns:
            Percentage growth (e.g., 15.5 for 15.5% growth)
        """
        token_address = token_address.lower()
        
        if hasattr(self, '_memory_storage'):
            return self._calc_memory_growth(token_address, hours, "total_holders")
        
        try:
            cutoff = datetime.utcnow() - timedelta(hours=hours)
            
            async with self.Session() as session:
                # Get oldest snapshot in period
                oldest = await session.execute(
                    select(TokenSnapshot)
                    .where(
                        TokenSnapshot.token_address == token_address,
                        TokenSnapshot.snapshot_at >= cutoff,
                    )
                    .order_by(TokenSnapshot.snapshot_at.asc())
                    .limit(1)
                )
                oldest = oldest.scalar_one_or_none()
                
                # Get latest snapshot
                latest = await session.execute(
                    select(TokenSnapshot)
                    .where(TokenSnapshot.token_address == token_address)
                    .order_by(TokenSnapshot.snapshot_at.desc())
                    .limit(1)
                )
                latest = latest.scalar_one_or_none()
                
                if not oldest or not latest or oldest.id == latest.id:
                    return Decimal("0")
                
                old_count = Decimal(str(oldest.total_holders or 0))
                new_count = Decimal(str(latest.total_holders or 0))
                
                if old_count == 0:
                    return Decimal("0")
                
                growth = ((new_count - old_count) / old_count) * Decimal("100")
                
                logger.debug(
                    "holder_growth_calculated",
                    token=token_address,
                    hours=hours,
                    old=int(old_count),
                    new=int(new_count),
                    growth=float(growth),
                )
                
                return growth
                
        except Exception as e:
            logger.error("holder_growth_calc_failed", token=token_address, error=str(e))
            return Decimal("0")

    async def get_volume_change(
        self,
        token_address: str,
        hours: int = 24,
    ) -> Decimal:
        """Calculate volume change over time period.
        
        Returns:
            Percentage change (e.g., -25.3 for 25.3% decrease)
        """
        token_address = token_address.lower()
        
        if hasattr(self, '_memory_storage'):
            return self._calc_memory_growth(token_address, hours, "volume_24h")
        
        try:
            cutoff = datetime.utcnow() - timedelta(hours=hours)
            
            async with self.Session() as session:
                # Get oldest snapshot in period
                oldest = await session.execute(
                    select(TokenSnapshot)
                    .where(
                        TokenSnapshot.token_address == token_address,
                        TokenSnapshot.snapshot_at >= cutoff,
                    )
                    .order_by(TokenSnapshot.snapshot_at.asc())
                    .limit(1)
                )
                oldest = oldest.scalar_one_or_none()
                
                # Get latest snapshot
                latest = await session.execute(
                    select(TokenSnapshot)
                    .where(TokenSnapshot.token_address == token_address)
                    .order_by(TokenSnapshot.snapshot_at.desc())
                    .limit(1)
                )
                latest = latest.scalar_one_or_none()
                
                if not oldest or not latest or oldest.id == latest.id:
                    return Decimal("0")
                
                old_volume = oldest.volume_24h or Decimal("0")
                new_volume = latest.volume_24h or Decimal("0")
                
                if old_volume == 0:
                    return Decimal("0")
                
                change = ((new_volume - old_volume) / old_volume) * Decimal("100")
                
                logger.debug(
                    "volume_change_calculated",
                    token=token_address,
                    hours=hours,
                    old=float(old_volume),
                    new=float(new_volume),
                    change=float(change),
                )
                
                return change
                
        except Exception as e:
            logger.error("volume_change_calc_failed", token=token_address, error=str(e))
            return Decimal("0")

    async def get_liquidity_change(
        self,
        token_address: str,
        hours: int = 24,
    ) -> Decimal:
        """Calculate liquidity change over time period."""
        token_address = token_address.lower()
        
        if hasattr(self, '_memory_storage'):
            return self._calc_memory_growth(token_address, hours, "liquidity_usd")
        
        try:
            cutoff = datetime.utcnow() - timedelta(hours=hours)
            
            async with self.Session() as session:
                oldest = await session.execute(
                    select(TokenSnapshot)
                    .where(
                        TokenSnapshot.token_address == token_address,
                        TokenSnapshot.snapshot_at >= cutoff,
                    )
                    .order_by(TokenSnapshot.snapshot_at.asc())
                    .limit(1)
                )
                oldest = oldest.scalar_one_or_none()
                
                latest = await session.execute(
                    select(TokenSnapshot)
                    .where(TokenSnapshot.token_address == token_address)
                    .order_by(TokenSnapshot.snapshot_at.desc())
                    .limit(1)
                )
                latest = latest.scalar_one_or_none()
                
                if not oldest or not latest:
                    return Decimal("0")
                
                old_liq = oldest.liquidity_usd or Decimal("0")
                new_liq = latest.liquidity_usd or Decimal("0")
                
                if old_liq == 0:
                    return Decimal("0")
                
                return ((new_liq - old_liq) / old_liq) * Decimal("100")
                
        except Exception as e:
            logger.error("liquidity_change_calc_failed", token=token_address, error=str(e))
            return Decimal("0")

    async def get_price_momentum(
        self,
        token_address: str,
        hours: int = 24,
    ) -> dict[str, Any]:
        """Calculate price momentum metrics."""
        token_address = token_address.lower()
        
        try:
            cutoff = datetime.utcnow() - timedelta(hours=hours)
            
            async with self.Session() as session:
                snapshots = await session.execute(
                    select(TokenSnapshot)
                    .where(
                        TokenSnapshot.token_address == token_address,
                        TokenSnapshot.snapshot_at >= cutoff,
                    )
                    .order_by(TokenSnapshot.snapshot_at.asc())
                )
                snapshots = snapshots.scalars().all()
                
                if len(snapshots) < 2:
                    return {
                        "change_pct": Decimal("0"),
                        "trend": "insufficient_data",
                        "volatility": Decimal("0"),
                    }
                
                prices = [s.price_usd or Decimal("0") for s in snapshots]
                
                # Calculate change
                first_price = prices[0]
                last_price = prices[-1]
                
                if first_price == 0:
                    change_pct = Decimal("0")
                else:
                    change_pct = ((last_price - first_price) / first_price) * Decimal("100")
                
                # Calculate volatility (standard deviation of returns)
                returns = []
                for i in range(1, len(prices)):
                    if prices[i-1] > 0:
                        ret = (prices[i] - prices[i-1]) / prices[i-1]
                        returns.append(ret)
                
                if returns:
                    mean_return = sum(returns) / len(returns)
                    variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
                    volatility = (variance ** Decimal("0.5")) * Decimal("100")
                else:
                    volatility = Decimal("0")
                
                # Determine trend
                if change_pct > 5:
                    trend = "strong_up"
                elif change_pct > 0:
                    trend = "up"
                elif change_pct > -5:
                    trend = "down"
                else:
                    trend = "strong_down"
                
                return {
                    "change_pct": change_pct,
                    "trend": trend,
                    "volatility": volatility,
                    "samples": len(prices),
                }
                
        except Exception as e:
            logger.error("price_momentum_calc_failed", token=token_address, error=str(e))
            return {
                "change_pct": Decimal("0"),
                "trend": "error",
                "volatility": Decimal("0"),
            }

    async def get_trend_summary(self, token_address: str) -> dict[str, Any]:
        """Get comprehensive trend summary for a token."""
        token_address = token_address.lower()
        
        holder_growth_24h = await self.get_holder_growth_rate(token_address, hours=24)
        holder_growth_7d = await self.get_holder_growth_rate(token_address, hours=168)
        volume_change_24h = await self.get_volume_change(token_address, hours=24)
        volume_change_7d = await self.get_volume_change(token_address, hours=168)
        liquidity_change_24h = await self.get_liquidity_change(token_address, hours=24)
        price_momentum = await self.get_price_momentum(token_address, hours=24)
        
        return {
            "token_address": token_address,
            "holder_growth_24h": float(holder_growth_24h),
            "holder_growth_7d": float(holder_growth_7d),
            "volume_change_24h": float(volume_change_24h),
            "volume_change_7d": float(volume_change_7d),
            "liquidity_change_24h": float(liquidity_change_24h),
            "price_change_24h": float(price_momentum["change_pct"]),
            "price_trend": price_momentum["trend"],
            "price_volatility": float(price_momentum["volatility"]),
            "calculated_at": datetime.utcnow().isoformat(),
        }

    def _calc_memory_growth(
        self,
        token_address: str,
        hours: int,
        field: str,
    ) -> Decimal:
        """Calculate growth from in-memory storage."""
        snapshots = self._memory_storage.get(token_address, [])
        if len(snapshots) < 2:
            return Decimal("0")
        
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        period_snapshots = [s for s in snapshots if s["snapshot_at"] >= cutoff]
        
        if len(period_snapshots) < 2:
            return Decimal("0")
        
        old_val = Decimal(str(period_snapshots[0].get(field, 0)))
        new_val = Decimal(str(period_snapshots[-1].get(field, 0)))
        
        if old_val == 0:
            return Decimal("0")
        
        return ((new_val - old_val) / old_val) * Decimal("100")

    async def cleanup_old_snapshots(self, days: int = 30):
        """Remove snapshots older than specified days."""
        if hasattr(self, '_memory_storage'):
            cutoff = datetime.utcnow() - timedelta(days=days)
            for token in self._memory_storage:
                self._memory_storage[token] = [
                    s for s in self._memory_storage[token]
                    if s["snapshot_at"] >= cutoff
                ]
            return
        
        try:
            cutoff = datetime.utcnow() - timedelta(days=days)
            
            async with self.Session() as session:
                from sqlalchemy import delete
                result = await session.execute(
                    delete(TokenSnapshot)
                    .where(TokenSnapshot.snapshot_at < cutoff)
                )
                await session.commit()
                
                logger.info(
                    "old_snapshots_cleaned",
                    days=days,
                    deleted=result.rowcount,
                )
                
        except Exception as e:
            logger.error("snapshot_cleanup_failed", error=str(e))

    async def close(self):
        """Close database connections."""
        if self.async_engine:
            await self.async_engine.dispose()
            logger.info("historical_tracker_closed")

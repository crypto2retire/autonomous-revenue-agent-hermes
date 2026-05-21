"""Async database engine and session management."""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select, desc, func, and_
from typing import Optional, List
from datetime import datetime, timedelta

from config import get_settings
from models import Base, CoinWatch, Trade, WalletSnapshot, AgentLog, PerformanceMetric

settings = get_settings()

engine = create_async_engine(
    settings.database_url.get_secret_value(),
    echo=False,
    pool_pre_ping=True,
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    """Create all tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


class DB:
    """Database operations for the trading agent."""

    # ── Coin Watchlist ───────────────────────────────────────────────

    @staticmethod
    async def upsert_coin(
        token_address: str,
        chain: str,
        symbol: str,
        name: str,
        price_usd: float,
        volume_24h: float,
        liquidity_usd: float,
        market_cap: float,
        holder_count: int,
        signal: str,
        confidence: float,
        ai_analysis: str,
        tags: str = "",
    ) -> CoinWatch:
        async with async_session() as session:
            result = await session.execute(
                select(CoinWatch).where(
                    and_(CoinWatch.token_address == token_address, CoinWatch.chain == chain)
                )
            )
            coin = result.scalar_one_or_none()

            if coin:
                coin.last_seen_at = datetime.utcnow()  # type: ignore[assignment]
                coin.last_price_usd = price_usd  # type: ignore[assignment]
                coin.scan_count = (coin.scan_count or 0) + 1  # type: ignore[assignment]
                if coin.first_price_usd and float(coin.first_price_usd) > 0:  # type: ignore[arg-type]
                    change = (price_usd - float(coin.first_price_usd)) / float(coin.first_price_usd) * 100
                    coin.price_change_pct = change  # type: ignore[assignment]
                coin.volume_24h = volume_24h  # type: ignore[assignment]
                coin.liquidity_usd = liquidity_usd  # type: ignore[assignment]
                coin.market_cap = market_cap  # type: ignore[assignment]
                coin.holder_count = holder_count  # type: ignore[assignment]
                coin.signal = signal  # type: ignore[assignment]
                coin.confidence = confidence  # type: ignore[assignment]
                coin.ai_analysis = ai_analysis  # type: ignore[assignment]
                if tags:
                    coin.tags = tags  # type: ignore[assignment]
            else:
                coin = CoinWatch(
                    token_address=token_address,
                    chain=chain,
                    symbol=symbol,
                    name=name,
                    first_price_usd=price_usd,
                    last_price_usd=price_usd,
                    volume_24h=volume_24h,
                    liquidity_usd=liquidity_usd,
                    market_cap=market_cap,
                    holder_count=holder_count,
                    signal=signal,
                    confidence=confidence,
                    ai_analysis=ai_analysis,
                    tags=tags,
                )
                session.add(coin)

            await session.commit()
            await session.refresh(coin)
            return coin

    @staticmethod
    async def get_coins(
        signal: Optional[str] = None,
        tags: Optional[str] = None,
        is_watching: Optional[bool] = None,
        min_price_change: Optional[float] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[CoinWatch]:
        async with async_session() as session:
            q = select(CoinWatch).order_by(desc(CoinWatch.last_seen_at))
            if signal:
                q = q.where(CoinWatch.signal == signal)
            if tags:
                q = q.where(CoinWatch.tags.contains(tags))
            if is_watching is not None:
                q = q.where(CoinWatch.is_watching == is_watching)
            if min_price_change is not None:
                q = q.where(CoinWatch.price_change_pct >= min_price_change)
            q = q.limit(limit).offset(offset)
            result = await session.execute(q)
            return result.scalars().all()

    @staticmethod
    async def get_coin_stats() -> dict:
        async with async_session() as session:
            total = await session.scalar(select(func.count(CoinWatch.id)))
            watching = await session.scalar(
                select(func.count(CoinWatch.id)).where(CoinWatch.is_watching == True)  # type: ignore[arg-type]
            )
            buy_signals = await session.scalar(
                select(func.count(CoinWatch.id)).where(CoinWatch.signal == "buy")
            )
            gainer = await session.scalar(
                select(func.max(CoinWatch.price_change_pct))
            )
            loser = await session.scalar(
                select(func.min(CoinWatch.price_change_pct))
            )
            return {
                "total_coins": total,
                "watching": watching,
                "buy_signals": buy_signals,
                "top_gainer_pct": float(gainer) if gainer else None,
                "top_loser_pct": float(loser) if loser else None,
            }

    # ── Trades ───────────────────────────────────────────────────────

    @staticmethod
    async def create_trade(**kwargs) -> Trade:
        async with async_session() as session:
            trade = Trade(**kwargs)
            session.add(trade)
            await session.commit()
            await session.refresh(trade)
            return trade

    @staticmethod
    async def get_trades(status: Optional[str] = None, limit: int = 100) -> List[Trade]:
        async with async_session() as session:
            q = select(Trade).order_by(desc(Trade.created_at)).limit(limit)
            if status:
                q = q.where(Trade.status == status)
            result = await session.execute(q)
            return result.scalars().all()

    @staticmethod
    async def update_trade(trade_id: str, **kwargs):
        async with async_session() as session:
            result = await session.execute(select(Trade).where(Trade.trade_id == trade_id))
            trade = result.scalar_one_or_none()
            if trade:
                for k, v in kwargs.items():
                    setattr(trade, k, v)
                await session.commit()

    # ── Wallet Snapshots ─────────────────────────────────────────────

    @staticmethod
    async def save_snapshot(**kwargs) -> WalletSnapshot:
        async with async_session() as session:
            snap = WalletSnapshot(**kwargs)
            session.add(snap)
            await session.commit()
            await session.refresh(snap)
            return snap

    @staticmethod
    async def get_wallet_history(address: str, hours: int = 24) -> List[WalletSnapshot]:
        async with async_session() as session:
            since = datetime.utcnow() - timedelta(hours=hours)
            result = await session.execute(
                select(WalletSnapshot)
                .where(
                    and_(
                        WalletSnapshot.address == address,
                        WalletSnapshot.created_at >= since,
                    )
                )
                .order_by(WalletSnapshot.created_at)
            )
            return result.scalars().all()

    # ── Logs ─────────────────────────────────────────────────────────

    @staticmethod
    async def log_event(level: str, event: str, message: str = "", **kwargs):
        async with async_session() as session:
            log = AgentLog(level=level, event=event, message=message, **kwargs)
            session.add(log)
            await session.commit()

    @staticmethod
    async def get_logs(event: Optional[str] = None, limit: int = 100) -> List[AgentLog]:
        async with async_session() as session:
            q = select(AgentLog).order_by(desc(AgentLog.created_at)).limit(limit)
            if event:
                q = q.where(AgentLog.event == event)
            result = await session.execute(q)
            return result.scalars().all()

    # ── Performance ──────────────────────────────────────────────────

    @staticmethod
    async def save_metric(**kwargs) -> PerformanceMetric:
        async with async_session() as session:
            metric = PerformanceMetric(**kwargs)
            session.add(metric)
            await session.commit()
            await session.refresh(metric)
            return metric

    @staticmethod
    async def get_performance(days: int = 7) -> List[PerformanceMetric]:
        async with async_session() as session:
            since = datetime.utcnow() - timedelta(days=days)
            result = await session.execute(
                select(PerformanceMetric)
                .where(PerformanceMetric.period_start >= since)
                .order_by(PerformanceMetric.period_start)
            )
            return result.scalars().all()

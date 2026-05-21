"""Async database engine and session management."""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select, desc, func, and_
from typing import Optional, List
from datetime import datetime, timedelta

from config import get_settings
from models import Base, CoinWatch, Trade, WalletSnapshot, AgentLog, PerformanceMetric

settings = get_settings()

# Handle both PostgreSQL and SQLite async URLs
database_url = settings.database_url.get_secret_value()
if database_url.startswith("sqlite:///"):
    # Convert to async SQLite URL
    database_url = database_url.replace("sqlite:///", "sqlite+aiosqlite:///")
    engine = create_async_engine(
        database_url,
        echo=False,
        pool_pre_ping=True,
    )
else:
    engine = create_async_engine(
        database_url,
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

    @staticmethod
    async def get_session():
        """Get a database session."""
        async with async_session() as session:
            yield session

    # --- Coin Watchlist ---

    @staticmethod
    async def add_coin(
        token_address: str,
        symbol: str,
        name: str,
        price_at_discovery: float,
        ai_score: float = 0.0,
        signal: str = "neutral",
        metadata: dict = None,
    ) -> CoinWatch:
        """Add a new coin to the watchlist."""
        async with async_session() as session:
            coin = CoinWatch(
                token_address=token_address,
                symbol=symbol,
                name=name,
                price_at_discovery=price_at_discovery,
                ai_score=ai_score,
                signal=signal,
                metadata=metadata or {},
            )
            session.add(coin)
            await session.commit()
            await session.refresh(coin)
            return coin

    @staticmethod
    async def get_coin(token_address: str) -> Optional[CoinWatch]:
        """Get a coin by token address."""
        async with async_session() as session:
            result = await session.execute(
                select(CoinWatch).where(CoinWatch.token_address == token_address)
            )
            return result.scalar_one_or_none()

    @staticmethod
    async def get_all_coins(
        signal: str = None,
        min_score: float = None,
        limit: int = 100,
    ) -> List[CoinWatch]:
        """Get coins with optional filtering."""
        async with async_session() as session:
            query = select(CoinWatch).order_by(desc(CoinWatch.ai_score))

            if signal:
                query = query.where(CoinWatch.signal == signal)
            if min_score is not None:
                query = query.where(CoinWatch.ai_score >= min_score)

            query = query.limit(limit)
            result = await session.execute(query)
            return result.scalars().all()

    @staticmethod
    async def update_coin_price(token_address: str, current_price: float):
        """Update current price and calculate price change."""
        async with async_session() as session:
            result = await session.execute(
                select(CoinWatch).where(CoinWatch.token_address == token_address)
            )
            coin = result.scalar_one_or_none()
            if coin:
                coin.current_price = current_price
                if coin.price_at_discovery > 0:
                    coin.price_change_pct = (
                        (current_price - coin.price_at_discovery)
                        / coin.price_at_discovery
                    ) * 100
                coin.last_updated = datetime.utcnow()
                await session.commit()

    @staticmethod
    async def update_coin_signal(
        token_address: str, signal: str, ai_score: float = None
    ):
        """Update coin signal and score."""
        async with async_session() as session:
            result = await session.execute(
                select(CoinWatch).where(CoinWatch.token_address == token_address)
            )
            coin = result.scalar_one_or_none()
            if coin:
                coin.signal = signal
                coin.scan_count += 1
                if ai_score is not None:
                    coin.ai_score = ai_score
                coin.last_updated = datetime.utcnow()
                await session.commit()

    # --- Trades ---

    @staticmethod
    async def record_trade(
        token_address: str,
        symbol: str,
        side: str,
        amount: float,
        price: float,
        total_value: float,
        trade_type: str = "paper",
        tx_hash: str = None,
        status: str = "completed",
    ) -> Trade:
        """Record a trade."""
        async with async_session() as session:
            trade = Trade(
                token_address=token_address,
                symbol=symbol,
                side=side,
                amount=amount,
                price=price,
                total_value=total_value,
                trade_type=trade_type,
                tx_hash=tx_hash,
                status=status,
            )
            session.add(trade)
            await session.commit()
            await session.refresh(trade)
            return trade

    @staticmethod
    async def get_trades(
        token_address: str = None,
        side: str = None,
        status: str = None,
        limit: int = 100,
    ) -> List[Trade]:
        """Get trades with filtering."""
        async with async_session() as session:
            query = select(Trade).order_by(desc(Trade.created_at))

            if token_address:
                query = query.where(Trade.token_address == token_address)
            if side:
                query = query.where(Trade.side == side)
            if status:
                query = query.where(Trade.status == status)

            query = query.limit(limit)
            result = await session.execute(query)
            return result.scalars().all()

    @staticmethod
    async def get_trade_stats() -> dict:
        """Get trade statistics."""
        async with async_session() as session:
            total_trades = await session.scalar(select(func.count(Trade.id)))
            buy_trades = await session.scalar(
                select(func.count(Trade.id)).where(Trade.side == "buy")
            )
            sell_trades = await session.scalar(
                select(func.count(Trade.id)).where(Trade.side == "sell")
            )
            total_volume = await session.scalar(
                select(func.sum(Trade.total_value))
            ) or 0.0

            return {
                "total_trades": total_trades,
                "buy_trades": buy_trades,
                "sell_trades": sell_trades,
                "total_volume": float(total_volume),
            }

    # --- Wallet Snapshots ---

    @staticmethod
    async def record_wallet_snapshot(
        total_balance_usd: float,
        eth_balance: float,
        token_balances: dict = None,
    ) -> WalletSnapshot:
        """Record wallet snapshot."""
        async with async_session() as session:
            snapshot = WalletSnapshot(
                total_balance_usd=total_balance_usd,
                eth_balance=eth_balance,
                token_balances=token_balances or {},
            )
            session.add(snapshot)
            await session.commit()
            await session.refresh(snapshot)
            return snapshot

    @staticmethod
    async def get_wallet_history(hours: int = 24) -> List[WalletSnapshot]:
        """Get wallet snapshots for the last N hours."""
        async with async_session() as session:
            since = datetime.utcnow() - timedelta(hours=hours)
            result = await session.execute(
                select(WalletSnapshot)
                .where(WalletSnapshot.created_at >= since)
                .order_by(WalletSnapshot.created_at)
            )
            return result.scalars().all()

    # --- Agent Logs ---

    @staticmethod
    async def log_event(
        level: str, event: str, message: str, metadata: dict = None
    ) -> AgentLog:
        """Log an agent event."""
        async with async_session() as session:
            log = AgentLog(
                level=level,
                event=event,
                message=message,
                metadata=metadata or {},
            )
            session.add(log)
            await session.commit()
            await session.refresh(log)
            return log

    @staticmethod
    async def get_logs(
        level: str = None,
        event: str = None,
        hours: int = 24,
        limit: int = 100,
    ) -> List[AgentLog]:
        """Get logs with filtering."""
        async with async_session() as session:
            since = datetime.utcnow() - timedelta(hours=hours)
            query = (
                select(AgentLog)
                .where(AgentLog.created_at >= since)
                .order_by(desc(AgentLog.created_at))
            )

            if level:
                query = query.where(AgentLog.level == level)
            if event:
                query = query.where(AgentLog.event == event)

            query = query.limit(limit)
            result = await session.execute(query)
            return result.scalars().all()

    # --- Performance Metrics ---

    @staticmethod
    async def record_performance(
        metric_name: str,
        metric_value: float,
        metadata: dict = None,
    ) -> PerformanceMetric:
        """Record a performance metric."""
        async with async_session() as session:
            metric = PerformanceMetric(
                metric_name=metric_name,
                metric_value=metric_value,
                metadata=metadata or {},
            )
            session.add(metric)
            await session.commit()
            await session.refresh(metric)
            return metric

    @staticmethod
    async def get_performance_summary(hours: int = 24) -> dict:
        """Get performance summary."""
        async with async_session() as session:
            since = datetime.utcnow() - timedelta(hours=hours)

            # Get latest wallet balance
            latest_snapshot = await session.execute(
                select(WalletSnapshot)
                .where(WalletSnapshot.created_at >= since)
                .order_by(desc(WalletSnapshot.created_at))
                .limit(1)
            )
            latest = latest_snapshot.scalar_one_or_none()

            # Get trade stats
            trade_stats = await DB.get_trade_stats()

            # Get coin counts
            total_coins = await session.scalar(select(func.count(CoinWatch.id)))
            bullish_coins = await session.scalar(
                select(func.count(CoinWatch.id)).where(CoinWatch.signal == "bullish")
            )
            bearish_coins = await session.scalar(
                select(func.count(CoinWatch.id)).where(CoinWatch.signal == "bearish")
            )

            return {
                "current_balance": latest.total_balance_usd if latest else 0.0,
                "eth_balance": latest.eth_balance if latest else 0.0,
                "total_coins_scanned": total_coins,
                "bullish_signals": bullish_coins,
                "bearish_signals": bearish_coins,
                **trade_stats,
            }

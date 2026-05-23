"""Async database engine and session management."""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select, desc, func, and_, update
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

from config import get_settings
from models import (
    Base, CoinWatch, Trade, WalletSnapshot, AgentLog, PerformanceMetric,
    Deployer, PriceHistory, AgentSettings
)

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
    # For PostgreSQL, ensure async driver
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
    elif database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+asyncpg://")
    engine = create_async_engine(
        database_url,
        echo=False,
        pool_pre_ping=True,
    )

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class DB:
    """Database operations."""

    @staticmethod
    async def init():
        """Create all tables."""
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    @staticmethod
    async def get_session():
        """Get a database session."""
        async with async_session() as session:
            yield session

    # --- Deployer Tracking ---

    @staticmethod
    async def get_or_create_deployer(address: str) -> Deployer:
        """Get existing deployer or create new one."""
        async with async_session() as session:
            result = await session.execute(
                select(Deployer).where(Deployer.address == address)
            )
            deployer = result.scalar_one_or_none()
            if not deployer:
                deployer = Deployer(address=address)
                session.add(deployer)
                await session.commit()
                await session.refresh(deployer)
            return deployer

    @staticmethod
    async def update_deployer_stats(address: str, is_success: bool = False, is_rug: bool = False):
        """Update deployer statistics."""
        async with async_session() as session:
            result = await session.execute(
                select(Deployer).where(Deployer.address == address)
            )
            deployer = result.scalar_one_or_none()
            if deployer:
                deployer.total_tokens_deployed = (deployer.total_tokens_deployed or 0) + 1
                if is_success:
                    deployer.successful_tokens = (deployer.successful_tokens or 0) + 1
                if is_rug:
                    deployer.rugged_tokens = (deployer.rugged_tokens or 0) + 1
                
                # Update reputation based on stats
                total = deployer.total_tokens_deployed
                if total > 0:
                    success_rate = (deployer.successful_tokens or 0) / total
                    rug_rate = (deployer.rugged_tokens or 0) / total
                    
                    if rug_rate > 0.5:
                        deployer.reputation = "rugger"
                        deployer.reputation_score = 0.1
                    elif success_rate > 0.6:
                        deployer.reputation = "trusted"
                        deployer.reputation_score = 0.8
                    elif rug_rate > 0.2:
                        deployer.reputation = "suspect"
                        deployer.reputation_score = 0.3
                    else:
                        deployer.reputation = "verified"
                        deployer.reputation_score = 0.6
                
                deployer.last_seen_at = datetime.utcnow()
                await session.commit()

    @staticmethod
    async def get_deployer(address: str) -> Optional[Deployer]:
        """Get deployer by address."""
        async with async_session() as session:
            result = await session.execute(
                select(Deployer).where(Deployer.address == address)
            )
            return result.scalar_one_or_none()

    @staticmethod
    async def get_all_deployers(
        reputation: str = None,
        min_score: float = None,
        limit: int = 100,
    ) -> List[Deployer]:
        """Get deployers with filtering."""
        async with async_session() as session:
            query = select(Deployer).order_by(desc(Deployer.reputation_score))
            
            if reputation:
                query = query.where(Deployer.reputation == reputation)
            if min_score is not None:
                query = query.where(Deployer.reputation_score >= min_score)
            
            query = query.limit(limit)
            result = await session.execute(query)
            return result.scalars().all()

    # --- Coin Watchlist ---

    @staticmethod
    async def add_coin(
        token_address: str,
        symbol: str,
        name: str,
        price_at_discovery: float,
        ai_score: float = 0.0,
        signal: str = "neutral",
        extra_data: dict = None,
        deployer_address: str = None,
        discovery_source: str = "unknown",
        chain: str = "base",
    ) -> CoinWatch:
        """Add a new coin to the watchlist."""
        async with async_session() as session:
            # Create or get deployer
            if deployer_address:
                deployer_result = await session.execute(
                    select(Deployer).where(Deployer.address == deployer_address)
                )
                deployer = deployer_result.scalar_one_or_none()
                if not deployer:
                    deployer = Deployer(address=deployer_address)
                    session.add(deployer)
                    await session.flush()
            
            coin = CoinWatch(
                token_address=token_address,
                chain=chain,
                symbol=symbol,
                name=name,
                first_price_usd=price_at_discovery,
                last_price_usd=price_at_discovery,
                highest_price_since_discovery=price_at_discovery,
                lowest_price_since_discovery=price_at_discovery,
                confidence=ai_score,
                signal=signal,
                ai_analysis=str(extra_data) if extra_data else None,
                deployer_address=deployer_address,
                discovery_source=discovery_source,
                extra_data=extra_data,
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
        is_rugged: bool = None,
        deployer_address: str = None,
        chain: str = None,
        limit: int = 100,
    ) -> List[CoinWatch]:
        """Get coins with optional filtering."""
        async with async_session() as session:
            query = select(CoinWatch).order_by(desc(CoinWatch.confidence))

            if signal:
                query = query.where(CoinWatch.signal == signal)
            if min_score is not None:
                query = query.where(CoinWatch.confidence >= min_score)
            if is_rugged is not None:
                query = query.where(CoinWatch.is_rugged == is_rugged)
            if deployer_address:
                query = query.where(CoinWatch.deployer_address == deployer_address)
            if chain:
                query = query.where(CoinWatch.chain == chain)

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
                coin.last_price_usd = current_price
                
                # Update high/low prices
                if coin.highest_price_since_discovery is None or current_price > float(coin.highest_price_since_discovery):
                    coin.highest_price_since_discovery = current_price
                if coin.lowest_price_since_discovery is None or current_price < float(coin.lowest_price_since_discovery):
                    coin.lowest_price_since_discovery = current_price
                
                # Calculate peak gain/loss
                if coin.first_price_usd and float(coin.first_price_usd) > 0:
                    first_price = float(coin.first_price_usd)
                    coin.price_change_pct = ((current_price - first_price) / first_price) * 100
                    coin.peak_gain_pct = ((float(coin.highest_price_since_discovery) - first_price) / first_price) * 100
                    coin.peak_loss_pct = ((float(coin.lowest_price_since_discovery) - first_price) / first_price) * 100
                
                coin.last_seen_at = datetime.utcnow()
                await session.commit()

    @staticmethod
    async def update_coin_signal(
        token_address: str, signal: str, ai_score: float = None, extra_data: dict = None
    ):
        """Update coin signal, score, and latest analysis details."""
        async with async_session() as session:
            result = await session.execute(
                select(CoinWatch).where(CoinWatch.token_address == token_address)
            )
            coin = result.scalar_one_or_none()
            if coin:
                coin.signal = signal
                coin.scan_count = (coin.scan_count or 0) + 1
                if ai_score is not None:
                    coin.confidence = ai_score
                if extra_data is not None:
                    coin.extra_data = extra_data
                    coin.ai_analysis = str(extra_data)
                coin.last_seen_at = datetime.utcnow()
                await session.commit()

    @staticmethod
    async def update_coin_market_data(
        token_address: str,
        price_usd: float = None,
        volume_24h: float = None,
        liquidity_usd: float = None,
        market_cap: float = None,
        holder_count: int = None,
    ):
        """Update latest market/holder data on the watchlist row."""
        async with async_session() as session:
            result = await session.execute(
                select(CoinWatch).where(CoinWatch.token_address == token_address)
            )
            coin = result.scalar_one_or_none()
            if coin:
                if price_usd is not None:
                    coin.last_price_usd = price_usd
                if volume_24h is not None:
                    coin.volume_24h = volume_24h
                if liquidity_usd is not None:
                    coin.liquidity_usd = liquidity_usd
                if market_cap is not None:
                    coin.market_cap = market_cap
                if holder_count is not None:
                    coin.holder_count = holder_count
                coin.last_seen_at = datetime.utcnow()
                await session.commit()

    @staticmethod
    async def mark_coin_rugged(token_address: str):
        """Mark a coin as rugged."""
        async with async_session() as session:
            result = await session.execute(
                select(CoinWatch).where(CoinWatch.token_address == token_address)
            )
            coin = result.scalar_one_or_none()
            if coin:
                coin.is_rugged = True
                coin.rugged_at = datetime.utcnow()
                coin.is_watching = False
                coin.signal = "avoid"
                await session.commit()
                
                # Update deployer stats
                if coin.deployer_address:
                    await DB.update_deployer_stats(coin.deployer_address, is_rug=True)

    @staticmethod
    async def get_coins_by_deployer(deployer_address: str) -> List[CoinWatch]:
        """Get all coins from a specific deployer."""
        async with async_session() as session:
            result = await session.execute(
                select(CoinWatch)
                .where(CoinWatch.deployer_address == deployer_address)
                .order_by(desc(CoinWatch.first_seen_at))
            )
            return result.scalars().all()

    @staticmethod
    async def get_successful_coins(min_gain_pct: float = 100.0, limit: int = 50) -> List[CoinWatch]:
        """Get coins that have gained significantly since discovery."""
        async with async_session() as session:
            result = await session.execute(
                select(CoinWatch)
                .where(CoinWatch.peak_gain_pct >= min_gain_pct)
                .where(CoinWatch.is_rugged == False)
                .order_by(desc(CoinWatch.peak_gain_pct))
                .limit(limit)
            )
            return result.scalars().all()

    # --- Price History ---

    @staticmethod
    async def record_price_history(
        token_address: str,
        symbol: str,
        price_usd: float,
        volume_24h: float = None,
        liquidity_usd: float = None,
        market_cap: float = None,
        holder_count: int = None,
        signal: str = None,
        confidence: float = None,
    ) -> PriceHistory:
        """Record a price snapshot for long-term tracking."""
        async with async_session() as session:
            history = PriceHistory(
                token_address=token_address,
                symbol=symbol,
                price_usd=price_usd,
                volume_24h=volume_24h,
                liquidity_usd=liquidity_usd,
                market_cap=market_cap,
                holder_count=holder_count,
                signal=signal,
                confidence=confidence,
            )
            session.add(history)
            await session.commit()
            await session.refresh(history)
            return history

    @staticmethod
    async def get_price_history(
        token_address: str,
        hours: int = 24,
        limit: int = 1000,
    ) -> List[PriceHistory]:
        """Get price history for a token."""
        async with async_session() as session:
            since = datetime.utcnow() - timedelta(hours=hours)
            result = await session.execute(
                select(PriceHistory)
                .where(PriceHistory.token_address == token_address)
                .where(PriceHistory.created_at >= since)
                .order_by(PriceHistory.created_at)
                .limit(limit)
            )
            return result.scalars().all()

    # --- Trades ---

    @staticmethod
    async def create_trade(
        trade_id: str,
        token_address: str,
        symbol: str,
        side: str,
        status: str,
        amount_usd: float,
        signal: str,
        confidence: float,
        is_paper: bool,
        chain: str = "base",
    ) -> Trade:
        """Create a new trade record."""
        async with async_session() as session:
            trade = Trade(
                trade_id=trade_id,
                token_address=token_address,
                chain=chain,
                symbol=symbol,
                side=side,
                status=status,
                amount_usd=amount_usd,
                signal=signal,
                confidence=confidence,
                is_paper=is_paper,
            )
            session.add(trade)
            await session.commit()
            await session.refresh(trade)
            return trade

    @staticmethod
    async def update_trade(
        trade_id: str,
        status: str = None,
        executed_at: datetime = None,
        entry_price: float = None,
        exit_price: float = None,
        tx_hash: str = None,
        closed_at: datetime = None,
        close_reason: str = None,
        pnl_usd: float = None,
        pnl_pct: float = None,
    ):
        """Update an existing trade."""
        async with async_session() as session:
            result = await session.execute(
                select(Trade).where(Trade.trade_id == trade_id)
            )
            trade = result.scalar_one_or_none()
            if trade:
                if status is not None:
                    trade.status = status
                if executed_at is not None:
                    trade.executed_at = executed_at
                if entry_price is not None:
                    trade.entry_price = entry_price
                if exit_price is not None:
                    trade.exit_price = exit_price
                if tx_hash is not None:
                    trade.tx_hash = tx_hash
                if closed_at is not None:
                    trade.closed_at = closed_at
                if close_reason is not None:
                    trade.close_reason = close_reason
                if pnl_usd is not None:
                    trade.pnl_usd = pnl_usd
                if pnl_pct is not None:
                    trade.pnl_pct = pnl_pct
                await session.commit()

    @staticmethod
    async def get_trades(
        token_address: str = None,
        side: str = None,
        status: str = None,
        chain: str = None,
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
            if chain:
                query = query.where(Trade.chain == chain)

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
                select(func.sum(Trade.amount_usd))
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
                address=settings.base_wallet_address,
                chain="base",
                total_usd=total_balance_usd,
                eth_balance=eth_balance,
                token_balances=str(token_balances) if token_balances else None,
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
                data=str(metadata) if metadata else None,
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
                period=metric_name,
                total_pnl_usd=metric_value,
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
            
            # Get deployer stats
            total_deployers = await session.scalar(select(func.count(Deployer.id)))
            trusted_deployers = await session.scalar(
                select(func.count(Deployer.id)).where(Deployer.reputation == "trusted")
            )
            rugger_deployers = await session.scalar(
                select(func.count(Deployer.id)).where(Deployer.reputation == "rugger")
            )

            return {
                "current_balance": float(latest.total_usd) if latest else 0.0,
                "eth_balance": float(latest.eth_balance) if latest else 0.0,
                "total_coins_scanned": total_coins,
                "bullish_signals": bullish_coins,
                "bearish_signals": bearish_coins,
                "total_deployers": total_deployers,
                "trusted_deployers": trusted_deployers,
                "rugger_deployers": rugger_deployers,
                **trade_stats,
            }

    # --- Agent Settings (Persistent State) ---

    @staticmethod
    async def get_setting(key: str, default: Any = None) -> Any:
        """Get a persistent setting."""
        async with async_session() as session:
            result = await session.execute(
                select(AgentSettings).where(AgentSettings.key == key)
            )
            setting = result.scalar_one_or_none()
            if setting:
                # Convert based on value_type
                if setting.value_type == "int":
                    return int(setting.value)
                elif setting.value_type == "float":
                    return float(setting.value)
                elif setting.value_type == "bool":
                    return setting.value.lower() in ("true", "1", "yes")
                elif setting.value_type == "json":
                    import json
                    return json.loads(setting.value)
                return setting.value
            return default

    @staticmethod
    async def set_setting(key: str, value: Any, value_type: str = "string", description: str = None):
        """Set a persistent setting."""
        async with async_session() as session:
            result = await session.execute(
                select(AgentSettings).where(AgentSettings.key == key)
            )
            setting = result.scalar_one_or_none()
            
            # Convert value to string
            if value_type == "json":
                import json
                str_value = json.dumps(value)
            else:
                str_value = str(value)
            
            if setting:
                setting.value = str_value
                setting.value_type = value_type
                if description:
                    setting.description = description
                setting.updated_at = datetime.utcnow()
            else:
                setting = AgentSettings(
                    key=key,
                    value=str_value,
                    value_type=value_type,
                    description=description,
                )
                session.add(setting)
            
            await session.commit()

    @staticmethod
    async def get_all_settings() -> List[AgentSettings]:
        """Get all persistent settings."""
        async with async_session() as session:
            result = await session.execute(select(AgentSettings).order_by(AgentSettings.key))
            return result.scalars().all()

    @staticmethod
    async def delete_setting(key: str):
        """Delete a persistent setting."""
        async with async_session() as session:
            result = await session.execute(
                select(AgentSettings).where(AgentSettings.key == key)
            )
            setting = result.scalar_one_or_none()
            if setting:
                await session.delete(setting)
                await session.commit()

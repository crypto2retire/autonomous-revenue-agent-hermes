"""Main survival loop for the autonomous revenue agent.

The agent's core mission: generate enough revenue to cover its own costs
and grow its capital. It does this through:
1. Trading crypto based on holder + volume signals
2. Offering services to other agents
3. Continuously monitoring its financial health

All data is persisted to PostgreSQL so it survives restarts.
"""

import asyncio
from decimal import Decimal
from datetime import datetime, timedelta
from typing import Optional

from src.config import settings
from src.venice import VeniceClient
from src.opportunity import OpportunityScanner
from src.wallet import WalletMonitor
from src.trade import TradeExecutor, RiskManager
from src.service import ServiceMarketplace, WSICClient
from src.db import AgentRepository
from src.utils.logger import get_logger

logger = get_logger(__name__)


class SurvivalLoop:
    """Main agent loop that keeps the agent alive and growing."""

    def __init__(self):
        self.venice = VeniceClient()
        self.wallet = WalletMonitor()
        self.risk = RiskManager()
        self.trade = TradeExecutor(self.risk)
        self.scanner = OpportunityScanner(self.venice)
        self.wsic = WSICClient()
        self.marketplace = ServiceMarketplace(self.venice, self.wsic)
        self.db = AgentRepository()

        self._running = False
        self._trading_enabled = True
        self._cycle_count = 0
        self._start_time: Optional[datetime] = None

        # Revenue tracking (in-memory + DB)
        self._total_trading_pnl = Decimal("0")
        self._total_service_revenue = Decimal("0")
        self._total_costs = Decimal("0")

    async def start(self):
        """Start the survival loop."""
        self._running = True
        self._start_time = datetime.utcnow()

        # Initialize database
        await self.db.initialize()

        logger.info(
            "agent_started",
            name=settings.agent_name,
            mode=settings.agent_mode,
            wallet=settings.base_wallet_address,
        )

        # Initialize services
        await self.marketplace.initialize_services()

        # Main loop
        while self._running:
            try:
                await self._run_cycle()
            except Exception as e:
                logger.error("cycle_failed", error=str(e))

            await asyncio.sleep(60)

    async def _run_cycle(self):
        """Run one survival cycle."""
        self._cycle_count += 1
        cycle_start = datetime.utcnow()

        logger.info("cycle_started", cycle=self._cycle_count)

        # 1. Check financial health + snapshot wallet
        health = await self.wallet.get_health_report()
        logger.info("health_check", **health)

        # Snapshot wallet to DB
        try:
            eth_balance = await self.wallet.get_balance()
            await self.db.create_wallet_snapshot(
                wallet_address=settings.base_wallet_address,
                chain="base",
                eth_balance=eth_balance,
                eth_price_usd=Decimal("3000"),
                total_balance_usd=eth_balance,
            )
        except Exception as e:
            logger.error("wallet_snapshot_failed", error=str(e))

        # Emergency shutdown check
        if health["emergency_shutdown"]:
            logger.critical("emergency_shutdown_triggered")
            await self._emergency_shutdown()
            return

        # 2. If survival threatened, prioritize revenue
        survival_threatened = health["survival_threatened"]

        if survival_threatened:
            logger.warning("survival_mode_activated")
            await self._survival_mode()
        else:
            await self._normal_operations()

        # 3. Log cycle summary + save performance metric
        cycle_duration = (datetime.utcnow() - cycle_start).total_seconds()
        logger.info(
            "cycle_complete",
            cycle=self._cycle_count,
            duration_seconds=cycle_duration,
            total_pnl=float(self._total_trading_pnl),
            total_revenue=float(self._total_service_revenue),
        )

        # Save performance metric
        try:
            await self.db.create_performance_metric(
                period_type="cycle",
                period_start=cycle_start,
                period_end=datetime.utcnow(),
                cycle_count=self._cycle_count,
                total_pnl_usd=self._total_trading_pnl,
                service_revenue_usd=self._total_service_revenue,
                trading_enabled=self._trading_enabled,
                survival_mode=survival_threatened,
            )
        except Exception as e:
            logger.error("performance_metric_save_failed", error=str(e))

    async def _normal_operations(self):
        """Normal operation mode - seek growth opportunities."""
        if self._trading_enabled:
            opportunities = await self.scanner.scan()

            for opp in opportunities:
                # Save opportunity to DB
                try:
                    await self._save_opportunity(opp)
                except Exception as e:
                    logger.error("opportunity_save_failed", error=str(e))

                if opp.ai_signal == "buy" and opp.ai_confidence and opp.ai_confidence > Decimal("0.7"):
                    success = await self.trade.execute_opportunity(opp, db=self.db)
                    if success and opp.pnl_usd:
                        self._total_trading_pnl += opp.pnl_usd
        else:
            logger.info("trading_disabled_skipping_opportunities")

        # Check service opportunities (always run)
        service_opps = await self.marketplace.find_service_opportunities()
        for opp in service_opps:
            logger.info("service_opportunity_found", **opp)

        # Monitor existing positions
        open_positions = await self.trade.get_open_positions(db=self.db)
        for pos in open_positions:
            # TODO: Check if position should be closed
            pass

    async def _survival_mode(self):
        """Survival mode - prioritize staying alive."""
        self.risk.max_position_pct = Decimal("1.0")

        revenue = await self.wsic.get_service_revenue(days=1)
        if revenue > 0:
            self._total_service_revenue += revenue

        if self._trading_enabled:
            opportunities = await self.scanner.scan()
            for opp in opportunities:
                if (
                    opp.ai_signal == "buy"
                    and opp.ai_confidence
                    and opp.ai_confidence > Decimal("0.85")
                    and opp.ai_risk_level == "low"
                ):
                    success = await self.trade.execute_opportunity(opp, db=self.db)
                    if success and opp.pnl_usd:
                        self._total_trading_pnl += opp.pnl_usd
        else:
            logger.warning("survival_mode_trading_disabled")

    async def _emergency_shutdown(self):
        """Emergency shutdown - preserve capital."""
        self._running = False

        open_positions = await self.trade.get_open_positions(db=self.db)
        for pos in open_positions:
            logger.info("emergency_closing_position", **pos)

        logger.critical(
            "agent_shutdown",
            cycles=self._cycle_count,
            uptime_hours=self._get_uptime_hours(),
            final_pnl=float(self._total_trading_pnl),
            final_revenue=float(self._total_service_revenue),
        )

    async def _save_opportunity(self, opp):
        """Persist an opportunity to the database."""
        await self.db.create_opportunity(
            token_address=opp.token_address,
            token_symbol=opp.token_symbol,
            token_name=opp.token_name,
            chain=opp.chain,
            price_usd=opp.current_price_usd,
            price_change_24h_pct=opp.price_change_24h_pct,
            price_change_7d_pct=opp.price_change_7d_pct,
            market_cap_usd=opp.market_cap_usd,
            fdv_usd=opp.fdv_usd,
            volume_24h_usd=opp.volume_metrics.volume_24h_usd if opp.volume_metrics else None,
            buy_sell_ratio=opp.volume_metrics.buy_sell_ratio if opp.volume_metrics else None,
            liquidity_usd=opp.volume_metrics.liquidity_usd if opp.volume_metrics else None,
            total_holders=opp.holder_metrics.total_holders if opp.holder_metrics else None,
            concentration_top_10=opp.holder_metrics.concentration_top_10 if opp.holder_metrics else None,
            concentration_top_50=opp.holder_metrics.concentration_top_50 if opp.holder_metrics else None,
            holder_growth_rate=opp.holder_metrics.holder_growth_rate if opp.holder_metrics else None,
            ai_signal=opp.ai_signal,
            ai_confidence=opp.ai_confidence,
            ai_risk_level=opp.ai_risk_level,
            ai_reasoning=opp.ai_reasoning,
            suggested_position_size_pct=opp.suggested_position_size_pct,
        )

    def _get_uptime_hours(self) -> float:
        if not self._start_time:
            return 0
        return (datetime.utcnow() - self._start_time).total_seconds() / 3600

    async def get_status_report(self) -> dict:
        """Get comprehensive agent status."""
        health = await self.wallet.get_health_report()
        risk = self.risk.get_risk_report()
        services = await self.marketplace.get_revenue_report()

        # Get DB stats
        try:
            trade_stats = await self.db.get_trade_stats()
            pos_summary = await self.db.get_position_summary()
        except Exception:
            trade_stats = {}
            pos_summary = {}

        return {
            "agent_name": settings.agent_name,
            "agent_mode": settings.agent_mode,
            "trading_enabled": self._trading_enabled,
            "cycle_count": self._cycle_count,
            "uptime_hours": self._get_uptime_hours(),
            "financial": health,
            "risk": risk,
            "services": services,
            "trading": {
                "total_pnl": float(self._total_trading_pnl),
                "open_positions": pos_summary.get("open_positions", 0),
                "unrealized_pnl": pos_summary.get("unrealized_pnl_usd", 0),
                **trade_stats,
            },
            "timestamp": datetime.utcnow().isoformat(),
        }

    def enable_trading(self):
        self._trading_enabled = True
        logger.critical("trading_enabled")

    def disable_trading(self):
        self._trading_enabled = False
        logger.critical("trading_disabled")

    @property
    def is_trading_enabled(self) -> bool:
        return self._trading_enabled

    def stop(self):
        self._running = False
        logger.info("agent_stop_requested")

    async def shutdown(self):
        """Graceful shutdown."""
        self.stop()
        await self.venice.close()
        await self.wsic.close()
        await self.db.close()
        logger.info("agent_shutdown_complete")

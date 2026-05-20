"""Main survival loop for the autonomous revenue agent.

The agent's core mission: generate enough revenue to cover its own costs
and grow its capital. It does this through:
1. Trading crypto based on holder + volume signals
2. Offering services to other agents
3. Continuously monitoring its financial health
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

        self._running = False
        self._trading_enabled = True  # Can be toggled via dashboard
        self._cycle_count = 0
        self._start_time: Optional[datetime] = None

        # Revenue tracking
        self._total_trading_pnl = Decimal("0")
        self._total_service_revenue = Decimal("0")
        self._total_costs = Decimal("0")

    async def start(self):
        """Start the survival loop."""
        self._running = True
        self._start_time = datetime.utcnow()

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

            await asyncio.sleep(60)  # 1 minute between cycles

    async def _run_cycle(self):
        """Run one survival cycle."""
        self._cycle_count += 1
        cycle_start = datetime.utcnow()

        logger.info("cycle_started", cycle=self._cycle_count)

        # 1. Check financial health
        health = await self.wallet.get_health_report()
        logger.info("health_check", **health)

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
            # Normal operations
            await self._normal_operations()

        # 3. Log cycle summary
        cycle_duration = (datetime.utcnow() - cycle_start).total_seconds()
        logger.info(
            "cycle_complete",
            cycle=self._cycle_count,
            duration_seconds=cycle_duration,
            total_pnl=float(self._total_trading_pnl),
            total_revenue=float(self._total_service_revenue),
        )

    async def _normal_operations(self):
        """Normal operation mode - seek growth opportunities."""
        # Scan for trading opportunities only if trading is enabled
        if self._trading_enabled:
            opportunities = await self.scanner.scan()

            for opp in opportunities:
                if opp.ai_signal == "buy" and opp.ai_confidence and opp.ai_confidence > Decimal("0.7"):
                    success = await self.trade.execute_opportunity(opp)
                    if success and opp.pnl_usd:
                        self._total_trading_pnl += opp.pnl_usd
        else:
            logger.info("trading_disabled_skipping_opportunities")

        # Check service opportunities (always run)
        service_opps = await self.marketplace.find_service_opportunities()
        for opp in service_opps:
            logger.info("service_opportunity_found", **opp)

        # Monitor existing positions
        open_positions = self.trade.get_open_positions()
        for pos in open_positions:
            # TODO: Check if position should be closed
            pass

    async def _survival_mode(self):
        """Survival mode - prioritize staying alive."""
        # Reduce risk
        self.risk.max_position_pct = Decimal("1.0")  # Very conservative

        # Focus on guaranteed revenue (services)
        revenue = await self.wsic.get_service_revenue(days=1)
        if revenue > 0:
            self._total_service_revenue += revenue

        # Only take very high confidence trades if trading enabled
        if self._trading_enabled:
            opportunities = await self.scanner.scan()
            for opp in opportunities:
                if (
                    opp.ai_signal == "buy"
                    and opp.ai_confidence
                    and opp.ai_confidence > Decimal("0.85")
                    and opp.ai_risk_level == "low"
                ):
                    success = await self.trade.execute_opportunity(opp)
                    if success and opp.pnl_usd:
                        self._total_trading_pnl += opp.pnl_usd
        else:
            logger.warning("survival_mode_trading_disabled")

    async def _emergency_shutdown(self):
        """Emergency shutdown - preserve capital."""
        self._running = False

        # Close all positions
        open_positions = self.trade.get_open_positions()
        for pos in open_positions:
            logger.info("emergency_closing_position", **pos)
            # TODO: Execute close

        logger.critical(
            "agent_shutdown",
            cycles=self._cycle_count,
            uptime_hours=self._get_uptime_hours(),
            final_pnl=float(self._total_trading_pnl),
            final_revenue=float(self._total_service_revenue),
        )

    def _get_uptime_hours(self) -> float:
        """Get agent uptime in hours."""
        if not self._start_time:
            return 0
        return (datetime.utcnow() - self._start_time).total_seconds() / 3600

    async def get_status_report(self) -> dict:
        """Get comprehensive agent status."""
        health = await self.wallet.get_health_report()
        risk = self.risk.get_risk_report()
        services = await self.marketplace.get_revenue_report()

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
                "open_positions": len(self.trade.get_open_positions()),
            },
            "timestamp": datetime.utcnow().isoformat(),
        }

    def enable_trading(self):
        """Enable trading."""
        self._trading_enabled = True
        logger.critical("trading_enabled")

    def disable_trading(self):
        """Disable trading (stop live/paper trades but keep agent running)."""
        self._trading_enabled = False
        logger.critical("trading_disabled")

    @property
    def is_trading_enabled(self) -> bool:
        """Check if trading is currently enabled."""
        return self._trading_enabled

    def stop(self):
        """Stop the survival loop."""
        self._running = False
        logger.info("agent_stop_requested")

    async def shutdown(self):
        """Graceful shutdown."""
        self.stop()
        await self.venice.close()
        await self.wsic.close()
        logger.info("agent_shutdown_complete")

"""Wallet balance and cost monitoring for survival."""

from decimal import Decimal
from datetime import datetime, timedelta
from typing import Optional

from web3 import Web3
from src.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


class WalletMonitor:
    """Monitors agent wallet and tracks survival metrics."""

    def __init__(self):
        self.w3 = Web3(Web3.HTTPProvider(settings.base_rpc_url))
        self.wallet_address = settings.base_wallet_address
        self._balance_history: list[dict] = []
        self._cost_history: list[dict] = []

    async def get_balance(self) -> Decimal:
        """Get current wallet balance in USD."""
        try:
            # Get ETH balance
            eth_balance_wei = self.w3.eth.get_balance(self.wallet_address)
            eth_balance = self.w3.from_wei(eth_balance_wei, "ether")

            # TODO: Get token balances (USDC, etc.)
            # For now, assume ETH price ~$3000
            eth_price_usd = Decimal("3000")
            balance_usd = Decimal(str(eth_balance)) * eth_price_usd

            self._balance_history.append({
                "timestamp": datetime.utcnow(),
                "balance_usd": balance_usd,
                "eth_balance": float(eth_balance),
            })

            return balance_usd

        except Exception as e:
            logger.error("balance_check_failed", error=str(e))
            return Decimal("0")

    async def get_runway_days(self) -> Decimal:
        """Calculate how many days the agent can survive at current burn rate."""
        balance = await self.get_balance()
        daily_cost = settings.hosting_cost_usd_per_day

        if daily_cost == 0:
            return Decimal("999")

        return balance / daily_cost

    async def is_survival_threatened(self) -> bool:
        """Check if agent is at risk of running out of funds."""
        balance = await self.get_balance()
        runway = await self.get_runway_days()

        threatened = (
            balance < settings.min_balance_usd
            or runway < Decimal("3")  # Less than 3 days runway
        )

        if threatened:
            logger.warning(
                "survival_threatened",
                balance_usd=float(balance),
                runway_days=float(runway),
                min_balance=float(settings.min_balance_usd),
            )

        return threatened

    async def should_emergency_shutdown(self) -> bool:
        """Check if emergency shutdown is needed."""
        balance = await self.get_balance()
        return balance < settings.emergency_shutdown_balance

    def record_cost(self, cost_usd: Decimal, category: str):
        """Record an expense."""
        self._cost_history.append({
            "timestamp": datetime.utcnow(),
            "cost_usd": cost_usd,
            "category": category,
        })

    def get_daily_cost_average(self, days: int = 7) -> Decimal:
        """Calculate average daily cost over last N days."""
        cutoff = datetime.utcnow() - timedelta(days=days)
        recent_costs = [
            c["cost_usd"] for c in self._cost_history
            if c["timestamp"] > cutoff
        ]

        if not recent_costs:
            return settings.hosting_cost_usd_per_day

        total = sum(recent_costs, Decimal("0"))
        return total / Decimal(str(days))

    async def get_health_report(self) -> dict:
        """Get comprehensive health report."""
        balance = await self.get_balance()
        runway = await self.get_runway_days()
        daily_cost = self.get_daily_cost_average()

        return {
            "balance_usd": float(balance),
            "runway_days": float(runway),
            "daily_cost_usd": float(daily_cost),
            "survival_threatened": await self.is_survival_threatened(),
            "emergency_shutdown": await self.should_emergency_shutdown(),
            "timestamp": datetime.utcnow().isoformat(),
        }

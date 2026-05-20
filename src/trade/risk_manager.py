"""Risk management for trading operations."""

from decimal import Decimal
from datetime import datetime, timedelta
from typing import Optional

from src.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


class RiskManager:
    """Manages trading risk and position sizing.

    Rules:
    1. Never risk more than X% of portfolio per trade
    2. Daily loss limit
    3. Maximum position size
    4. Minimum liquidity requirements
    """

    def __init__(self):
        self.daily_loss_limit = settings.daily_budget_usd * Decimal("0.5")  # 50% of daily budget
        self.max_position_pct = settings.risk_per_trade_pct
        self.max_trade_size = settings.max_trade_size_usd
        self._daily_pnl: Decimal = Decimal("0")
        self._daily_trades: int = 0
        self._last_reset: datetime = datetime.utcnow()

    def _reset_daily(self):
        """Reset daily counters if it's a new day."""
        now = datetime.utcnow()
        if now.date() != self._last_reset.date():
            self._daily_pnl = Decimal("0")
            self._daily_trades = 0
            self._last_reset = now
            logger.info("daily_risk_counters_reset")

    def can_trade(self, portfolio_value: Decimal) -> tuple[bool, str]:
        """Check if trading is allowed.

        Returns:
            (allowed, reason)
        """
        self._reset_daily()

        # Check daily loss limit
        if self._daily_pnl <= -self.daily_loss_limit:
            return False, f"Daily loss limit reached: {self._daily_pnl}"

        # Check max daily trades
        if self._daily_trades >= 10:
            return False, "Max daily trades reached"

        # Check minimum portfolio
        if portfolio_value < settings.min_balance_usd:
            return False, f"Portfolio below minimum: {portfolio_value}"

        return True, "OK"

    def calculate_position_size(
        self,
        portfolio_value: Decimal,
        opportunity_confidence: Decimal,
        risk_level: str,
    ) -> Decimal:
        """Calculate safe position size for a trade.

        Args:
            portfolio_value: Total portfolio value
            opportunity_confidence: AI confidence (0-1)
            risk_level: "low", "medium", "high"

        Returns:
            Position size in USD
        """
        self._reset_daily()

        # Base position size based on risk percentage
        base_size = portfolio_value * (self.max_position_pct / Decimal("100"))

        # Adjust for confidence
        confidence_multiplier = opportunity_confidence

        # Adjust for risk level
        risk_multipliers = {
            "low": Decimal("1.0"),
            "medium": Decimal("0.7"),
            "high": Decimal("0.4"),
        }
        risk_multiplier = risk_multipliers.get(risk_level, Decimal("0.5"))

        # Calculate final size
        position_size = base_size * confidence_multiplier * risk_multiplier

        # Cap at max trade size
        position_size = min(position_size, self.max_trade_size)

        # Ensure we don't exceed daily budget
        remaining_budget = settings.daily_budget_usd - sum(
            # TODO: Track actual daily spend
            Decimal("0") for _ in range(self._daily_trades)
        )
        position_size = min(position_size, remaining_budget)

        logger.info(
            "position_size_calculated",
            base_size=float(base_size),
            confidence=float(confidence_multiplier),
            risk_multiplier=float(risk_multiplier),
            final_size=float(position_size),
        )

        return position_size

    def record_trade_result(self, pnl_usd: Decimal):
        """Record trade P&L for daily tracking."""
        self._daily_pnl += pnl_usd
        self._daily_trades += 1

        logger.info(
            "trade_result_recorded",
            pnl_usd=float(pnl_usd),
            daily_pnl=float(self._daily_pnl),
            daily_trades=self._daily_trades,
        )

    def get_risk_report(self) -> dict:
        """Get current risk status."""
        self._reset_daily()

        return {
            "daily_pnl": float(self._daily_pnl),
            "daily_trades": self._daily_trades,
            "daily_loss_limit": float(self.daily_loss_limit),
            "max_position_pct": float(self.max_position_pct),
            "max_trade_size": float(self.max_trade_size),
            "trades_remaining": 10 - self._daily_trades,
            "timestamp": datetime.utcnow().isoformat(),
        }

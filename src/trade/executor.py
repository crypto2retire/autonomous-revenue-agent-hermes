"""Trade execution engine for crypto opportunities."""

from decimal import Decimal
from datetime import datetime
from typing import Optional

from web3 import Web3
from eth_account import Account

from src.config import settings
from src.opportunity.models import Opportunity, OpportunityStatus
from src.trade.risk_manager import RiskManager
from src.utils.logger import get_logger

logger = get_logger(__name__)


class TradeExecutor:
    """Executes trades based on approved opportunities.

    Supports both live trading and paper trading modes.
    """

    def __init__(self, risk_manager: RiskManager):
        self.w3 = Web3(Web3.HTTPProvider(settings.base_rpc_url))
        self.risk = risk_manager
        self.wallet_address = settings.base_wallet_address
        self._private_key = settings.base_wallet_private_key.get_secret_value()
        self._account = Account.from_key(self._private_key)
        self._paper_positions: dict[str, dict] = {}

    async def execute_opportunity(self, opportunity: Opportunity) -> bool:
        """Execute a trade for an approved opportunity.

        Returns True if successful, False otherwise.
        """
        opportunity.status = OpportunityStatus.EXECUTING

        try:
            # Check risk limits
            portfolio_value = await self._get_portfolio_value()
            can_trade, reason = self.risk.can_trade(portfolio_value)

            if not can_trade:
                logger.warning("trade_blocked_by_risk", reason=reason)
                opportunity.status = OpportunityStatus.REJECTED
                return False

            # Calculate position size
            position_size = self.risk.calculate_position_size(
                portfolio_value=portfolio_value,
                opportunity_confidence=opportunity.ai_confidence or Decimal("0"),
                risk_level=opportunity.ai_risk_level or "high",
            )

            if position_size <= 0:
                logger.warning("position_size_zero", opportunity=opportunity.token_symbol)
                opportunity.status = OpportunityStatus.REJECTED
                return False

            opportunity.position_size_usd = position_size
            opportunity.entry_price = opportunity.current_price_usd

            # Execute based on mode
            if settings.is_live:
                success = await self._execute_live_trade(opportunity)
            else:
                success = await self._execute_paper_trade(opportunity)

            if success:
                opportunity.status = OpportunityStatus.EXECUTED
                opportunity.executed_at = datetime.utcnow()
                logger.info(
                    "trade_executed",
                    token=opportunity.token_symbol,
                    size=float(position_size),
                    price=float(opportunity.entry_price),
                    mode="live" if settings.is_live else "paper",
                )
            else:
                opportunity.status = OpportunityStatus.FAILED

            return success

        except Exception as e:
            logger.error("trade_execution_failed", error=str(e))
            opportunity.status = OpportunityStatus.FAILED
            return False

    async def _execute_live_trade(self, opportunity: Opportunity) -> bool:
        """Execute a real trade on-chain.

        TODO: Implement actual DEX integration (Uniswap V3, Odos, etc.)
        """
        logger.warning("live_trading_not_implemented", token=opportunity.token_symbol)

        # Placeholder for actual swap execution
        # 1. Approve token spending
        # 2. Build swap transaction
        # 3. Sign and send
        # 4. Wait for confirmation
        # 5. Record position

        return False

    async def _execute_paper_trade(self, opportunity: Opportunity) -> bool:
        """Execute a paper/simulated trade."""
        self._paper_positions[opportunity.token_address] = {
            "entry_price": float(opportunity.entry_price),
            "position_size": float(opportunity.position_size_usd),
            "entry_time": datetime.utcnow().isoformat(),
            "token_symbol": opportunity.token_symbol,
        }

        logger.info(
            "paper_trade_executed",
            token=opportunity.token_symbol,
            size=float(opportunity.position_size_usd),
        )

        return True

    async def close_position(
        self,
        opportunity: Opportunity,
        current_price: Decimal,
    ) -> Decimal:
        """Close a position and calculate P&L.

        Returns P&L in USD.
        """
        if not opportunity.entry_price or not opportunity.position_size_usd:
            return Decimal("0")

        # Calculate P&L
        price_change_pct = (
            (current_price - opportunity.entry_price) / opportunity.entry_price
        ) * Decimal("100")

        pnl_usd = opportunity.position_size_usd * (price_change_pct / Decimal("100"))
        pnl_pct = price_change_pct

        opportunity.exit_price = current_price
        opportunity.pnl_usd = pnl_usd
        opportunity.pnl_pct = pnl_pct
        opportunity.status = OpportunityStatus.CLOSED
        opportunity.closed_at = datetime.utcnow()

        # Record for risk tracking
        self.risk.record_trade_result(pnl_usd)

        logger.info(
            "position_closed",
            token=opportunity.token_symbol,
            entry=float(opportunity.entry_price),
            exit=float(current_price),
            pnl_usd=float(pnl_usd),
            pnl_pct=float(pnl_pct),
        )

        return pnl_usd

    async def _get_portfolio_value(self) -> Decimal:
        """Get total portfolio value in USD."""
        # TODO: Calculate actual portfolio value
        # For now, return wallet balance
        try:
            eth_balance_wei = self.w3.eth.get_balance(self.wallet_address)
            eth_balance = self.w3.from_wei(eth_balance_wei, "ether")
            eth_price = Decimal("3000")  # TODO: Get real price
            return Decimal(str(eth_balance)) * eth_price
        except Exception:
            return Decimal("0")

    def get_open_positions(self) -> list[dict]:
        """Get list of open positions."""
        if settings.is_paper:
            return list(self._paper_positions.values())

        # TODO: Track live positions
        return []

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

    async def execute_opportunity(self, opportunity: Opportunity, db=None) -> bool:
        """Execute a trade for an approved opportunity.

        Args:
            opportunity: The opportunity to trade
            db: Optional AgentRepository for persistence

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

            # Create trade record in DB
            trade_id: Optional[str] = None
            if db:
                try:
                    trade = await db.create_trade(
                        token_address=opportunity.token_address,
                        token_symbol=opportunity.token_symbol,
                        token_name=opportunity.token_name,
                        chain=opportunity.chain,
                        trade_type="buy",
                        status="pending",
                        mode=settings.agent_mode,
                        entry_price=opportunity.entry_price,
                        position_size_usd=position_size,
                        ai_signal=opportunity.ai_signal,
                        ai_confidence=opportunity.ai_confidence,
                        ai_risk_level=opportunity.ai_risk_level,
                        ai_reasoning=opportunity.ai_reasoning,
                    )
                    trade_id = trade.trade_id
                except Exception as e:
                    logger.error("trade_db_create_failed", error=str(e))

            # Execute based on mode
            if settings.is_live:
                success = await self._execute_live_trade(opportunity)
            else:
                success = await self._execute_paper_trade(opportunity, trade_id=trade_id, db=db)

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
                # Update trade record
                if db and trade_id:
                    await db.update_trade(
                        trade_id=trade_id,
                        status="executed",
                        executed_at=datetime.utcnow(),
                    )
            else:
                opportunity.status = OpportunityStatus.FAILED
                if db and trade_id:
                    await db.update_trade(
                        trade_id=trade_id,
                        status="failed",
                    )

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
        return False

    async def _execute_paper_trade(self, opportunity: Opportunity, trade_id: Optional[str] = None, db=None) -> bool:
        """Execute a paper/simulated trade."""
        position_data = {
            "entry_price": float(opportunity.entry_price),
            "position_size": float(opportunity.position_size_usd),
            "entry_time": datetime.utcnow().isoformat(),
            "token_symbol": opportunity.token_symbol,
            "trade_id": trade_id,
        }
        self._paper_positions[opportunity.token_address] = position_data

        # Create open position in DB
        if db and trade_id:
            try:
                await db.create_open_position(
                    trade_id=trade_id,
                    token_address=opportunity.token_address,
                    token_symbol=opportunity.token_symbol,
                    chain=opportunity.chain,
                    entry_price=opportunity.entry_price,
                    position_size_usd=opportunity.position_size_usd or Decimal("0"),
                    mode="paper",
                )
            except Exception as e:
                logger.error("open_position_db_create_failed", error=str(e))

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
        db=None,
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

        # Update DB
        if db:
            try:
                # Find and update trade
                trades = await db.list_trades(
                    token_address=opportunity.token_address,
                    status="executed",
                    limit=1,
                )
                if trades:
                    await db.update_trade(
                        trade_id=trades[0].trade_id,
                        status="closed",
                        exit_price=current_price,
                        pnl_usd=pnl_usd,
                        pnl_pct=pnl_pct,
                        closed_at=datetime.utcnow(),
                    )
                    # Close open position
                    positions = await db.list_open_positions(status="open")
                    for pos in positions:
                        if pos.token_address == opportunity.token_address:
                            await db.close_open_position(
                                position_id=pos.position_id,
                                current_price=current_price,
                                unrealized_pnl_usd=pnl_usd,
                                unrealized_pnl_pct=pnl_pct,
                            )
            except Exception as e:
                logger.error("close_position_db_update_failed", error=str(e))

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
        try:
            eth_balance_wei = self.w3.eth.get_balance(self.wallet_address)
            eth_balance = self.w3.from_wei(eth_balance_wei, "ether")
            eth_price = Decimal("3000")  # TODO: Get real price
            return Decimal(str(eth_balance)) * eth_price
        except Exception:
            return Decimal("0")

    async def get_open_positions(self, db=None) -> list[dict]:
        """Get list of open positions."""
        if db:
            try:
                db_positions = await db.list_open_positions(status="open")
                return [
                    {
                        "position_id": p.position_id,
                        "trade_id": p.trade_id,
                        "token_address": p.token_address,
                        "token_symbol": p.token_symbol,
                        "entry_price": float(p.entry_price),
                        "current_price": float(p.current_price) if p.current_price else None,
                        "position_size_usd": float(p.position_size_usd),
                        "unrealized_pnl_usd": float(p.unrealized_pnl_usd),
                        "unrealized_pnl_pct": float(p.unrealized_pnl_pct),
                        "opened_at": p.opened_at.isoformat() if p.opened_at else None,
                    }
                    for p in db_positions
                ]
            except Exception as e:
                logger.error("db_open_positions_fetch_failed", error=str(e))

        if settings.is_paper:
            return list(self._paper_positions.values())

        # TODO: Track live positions
        return []

"""Position Manager — the Sell Agent.

Monitors all open positions, enforces stop-loss / take-profit / trailing stop,
and sells underperformers to recycle capital for the Buy Agent.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional

from config import get_settings
from database import DB
from executor import Executor
from models import TradeStatus, SellReason
from solana_price_client import get_solana_price_client

settings = get_settings()


class PositionManager:
    """Autonomous sell agent that manages open positions."""

    def __init__(self):
        self.executor = Executor()
        self.running = False
        self.sell_count_today = 0
        self.last_reset = datetime.now(timezone.utc).date()
        self._price_client = None

    async def _get_price_client(self):
        """Lazy init the Solana price client."""
        if self._price_client is None:
            self._price_client = await get_solana_price_client()
        return self._price_client

    async def close(self):
        await self.executor.close()
        if self._price_client:
            await self._price_client.close()

    # ── Price Fetching ───────────────────────────────────────────────

    async def _get_current_price(self, token_address: str, chain: str, force_refresh: bool = False) -> Optional[float]:
        """Get current token price using SolanaPriceClient with Birdeye priority.

        force_refresh=True bypasses the DB cache. The old behavior returned any
        cached positive price forever, so dashboard prices/PNL stayed frozen.
        """
        coin = await DB.get_coin(token_address)
        cached_price = None
        if coin and coin.last_price_usd is not None:
            cached_price = float(coin.last_price_usd)
            if cached_price <= 0:
                cached_price = None
            elif not force_refresh:
                return cached_price
        
        # Fallback: use SolanaPriceClient (Birdeye → Jupiter → DexScreener → CoinGecko)
        if chain.lower() == "solana":
            try:
                price_client = await self._get_price_client()
                price = await price_client.get_price(token_address, "USDC")
                if price and price > 0:
                    # Update cache for next time
                    await DB.update_coin_market_data(token_address, price_usd=price)
                    return price
            except Exception as e:
                await DB.log_event("warning", "price_fetch_failed", f"Failed to fetch price for {token_address}: {e}")
        
        return cached_price

    async def _refresh_all_position_prices(self):
        """Background task: refresh prices for all open positions."""
        try:
            positions = await DB.get_open_positions()
            refreshed = 0
            for pos in positions:
                token_address = pos.get("token_address")
                chain = pos.get("chain", "solana")
                if token_address:
                    try:
                        price = await self._get_current_price(token_address, chain, force_refresh=True)
                        if price is not None and price > 0:
                            await DB.update_coin_market_data(token_address, price_usd=price)
                            refreshed += 1
                    except Exception as e:
                        await DB.log_event("warning", "price_refresh_failed", 
                            f"Failed to refresh price for {pos.get('symbol', 'UNKNOWN')}: {e}")
            await DB.log_event("info", "position_price_refresh_completed", f"Refreshed {refreshed} open position prices")
        except Exception as e:
            await DB.log_event("error", "price_refresh_loop_failed", str(e))

    async def _refresh_watchlist_prices(self):
        """Background task: refresh prices for ALL watchlist coins (not just positions)."""
        try:
            coins = await DB.get_all_coins(limit=100)
            refreshed = 0
            for coin in coins:
                token_address = str(coin.token_address) if coin.token_address is not None else ""
                if token_address == "":
                    continue
                chain = str(coin.chain) if coin.chain is not None else "solana"
                symbol = str(coin.symbol) if coin.symbol is not None else "UNKNOWN"
                try:
                    price = await self._get_current_price(token_address, chain, force_refresh=True)
                    if price is not None and price > 0:
                        await DB.update_coin_market_data(token_address, price_usd=price)
                        # Also record price history for intraday calculations
                        await DB.record_price_history(
                            token_address=token_address,
                            symbol=symbol,
                            price_usd=price,
                        )
                        # Update intraday changes
                        await DB.update_coin_intraday_changes(token_address)
                        refreshed += 1
                except Exception as e:
                    await DB.log_event("warning", "watchlist_price_refresh_failed", 
                        f"Failed to refresh price for {symbol}: {e}")
            await DB.log_event("info", "watchlist_price_refresh_completed", f"Refreshed {refreshed} watchlist prices")
        except Exception as e:
            await DB.log_event("error", "watchlist_price_refresh_loop_failed", str(e))

    # ── Position Evaluation ──────────────────────────────────────────

    async def evaluate_position(self, trade) -> Dict[str, Any]:
        """Evaluate a single position and determine if it should be sold."""
        token_address = trade.token_address
        chain = trade.chain or "solana"
        symbol = trade.symbol or "UNKNOWN"
        entry_price = float(trade.entry_price) if trade.entry_price is not None else 0.0
        amount_usd = float(trade.amount_usd) if trade.amount_usd is not None else 0.0
        executed_at = trade.executed_at
        highest_price = float(trade.highest_price_seen) if trade.highest_price_seen is not None else entry_price
        amount_sold_pct = float(trade.amount_sold_pct) if trade.amount_sold_pct is not None else 0.0

        current_price = await self._get_current_price(token_address, chain, force_refresh=True)
        if current_price is None or current_price <= 0 or entry_price <= 0:
            return {"should_sell": False, "reason": None, "pnl_pct": 0}

        # Calculate PNL
        pnl_pct = ((current_price - entry_price) / entry_price) * 100
        amount_token = float(trade.amount_token) if trade.amount_token is not None else 0.0
        if amount_token > 0:
            pnl_usd = amount_token * (current_price - entry_price)
        else:
            pnl_usd = amount_usd * (pnl_pct / 100)

        # Update highest price seen
        if current_price > highest_price:
            highest_price = current_price
            await DB.update_trade_highest_price(trade.trade_id, highest_price)

        # Calculate trailing stop price
        trailing_stop_price = highest_price * (1 - settings.trailing_stop_distance_pct)

        # Calculate hold duration
        hold_hours = 0
        if executed_at:
            # Ensure both datetimes are timezone-aware before subtracting
            now = datetime.now(timezone.utc)
            if executed_at.tzinfo is None:
                executed_at = executed_at.replace(tzinfo=timezone.utc)
            hold_hours = (now - executed_at).total_seconds() / 3600

        result = {
            "trade_id": trade.trade_id,
            "symbol": symbol,
            "token_address": token_address,
            "chain": chain,
            "entry_price": entry_price,
            "current_price": current_price,
            "highest_price": highest_price,
            "trailing_stop_price": trailing_stop_price,
            "pnl_pct": pnl_pct,
            "pnl_usd": pnl_usd,
            "hold_hours": hold_hours,
            "amount_usd": amount_usd,
            "amount_sold_pct": amount_sold_pct,
            "should_sell": False,
            "reason": None,
            "sell_pct": 100.0,  # Default: sell entire position
        }

        # 1. Emergency stop loss (-30%)
        if pnl_pct <= -(settings.emergency_stop_loss_pct * 100):
            result["should_sell"] = True
            result["reason"] = SellReason.STOP_LOSS
            result["sell_pct"] = 100.0
            return result

        # 2. Standard stop loss (-15%)
        if pnl_pct <= -(settings.stop_loss_pct * 100):
            result["should_sell"] = True
            result["reason"] = SellReason.STOP_LOSS
            result["sell_pct"] = 100.0
            return result

        # 3. Profit target 2 (+50% → sell 80%)
        if pnl_pct >= (settings.profit_target_2_pct * 100) and not trade.profit_target_2_hit:
            result["should_sell"] = True
            result["reason"] = SellReason.TAKE_PROFIT
            result["sell_pct"] = settings.profit_target_2_sell_pct * 100
            return result

        # 4. Profit target 1 (+25% → sell 60%)
        if pnl_pct >= (settings.profit_target_1_pct * 100) and not trade.profit_target_1_hit:
            result["should_sell"] = True
            result["reason"] = SellReason.TAKE_PROFIT
            result["sell_pct"] = settings.profit_target_1_sell_pct * 100
            return result

        # 5. Trailing stop (if enabled and price has dropped from peak)
        if settings.trailing_stop_enabled and current_price is not None and current_price < trailing_stop_price and highest_price > entry_price * 1.05:
            result["should_sell"] = True
            result["reason"] = SellReason.TRAILING_STOP
            result["sell_pct"] = 100.0
            return result

        # 6. Max hold time (7 days)
        if hold_hours >= settings.max_hold_hours:
            result["should_sell"] = True
            result["reason"] = SellReason.MAX_HOLD_TIME
            result["sell_pct"] = 100.0
            return result

        # 7. Underperforming + capital recycle needed
        if pnl_pct <= (settings.underperform_sell_threshold_pct * 100) and settings.capital_recycle_enabled:
            # Only sell underperformers if we need capital
            allocation = await self._get_allocation()
            if allocation.get("should_recycle", False):
                result["should_sell"] = True
                result["reason"] = SellReason.CAPITAL_RECYCLE
                result["sell_pct"] = 100.0
                return result

        return result

    async def _get_allocation(self) -> Dict[str, Any]:
        """Get capital allocation from wallet monitor."""
        from wallet_monitor import WalletMonitor
        wm = WalletMonitor()
        try:
            return await wm.get_capital_allocation()
        except Exception:
            return {"should_recycle": False}

    # ── Sell Execution ───────────────────────────────────────────────

    async def _execute_sell(self, evaluation: Dict[str, Any]) -> bool:
        """Execute a sell based on evaluation."""
        trade_id = evaluation["trade_id"]
        token_address = evaluation["token_address"]
        symbol = evaluation["symbol"]
        chain = evaluation["chain"]
        sell_pct = evaluation["sell_pct"]
        reason = evaluation["reason"]
        pnl_pct = evaluation["pnl_pct"]
        pnl_usd = evaluation["pnl_usd"]

        # Get the trade to find amount
        trades = await DB.get_trades(token_address=token_address, status=TradeStatus.EXECUTED, limit=1)
        if not trades:
            return False
        trade = trades[0]
        amount_token = float(trade.amount_token) if trade.amount_token is not None else 0.0

        # Calculate sell amount
        sell_amount = amount_token * (sell_pct / 100.0)

        # Update profit target flags before selling
        if reason == SellReason.TAKE_PROFIT:
            if pnl_pct >= (settings.profit_target_2_pct * 100):
                await DB.update_trade_profit_target(trade_id, target_2=True)
            elif pnl_pct >= (settings.profit_target_1_pct * 100):
                await DB.update_trade_profit_target(trade_id, target_1=True)

        # Execute the sell
        success = await self.executor.execute_sell(
            token_address=token_address,
            symbol=symbol,
            amount_token=sell_amount,
            trade_id=trade_id,
            chain=chain,
            reason=reason,
        )

        if success:
            # Update trade with PNL
            current_sold = float(trade.amount_sold_pct) if trade.amount_sold_pct is not None else 0.0
            new_amount_sold = current_sold + sell_pct
            await DB.update_trade(
                trade_id=trade_id,
                exit_price=evaluation["current_price"],
                pnl_usd=pnl_usd,
                pnl_pct=pnl_pct,
                amount_sold_pct=new_amount_sold,
            )

            # If fully sold, mark as closed
            if new_amount_sold >= 99.0:
                await DB.update_trade(
                    trade_id=trade_id,
                    status=TradeStatus.CLOSED,
                    closed_at=datetime.now(timezone.utc),
                    close_reason=reason,
                )

            await DB.log_event(
                "info", "sell_executed",
                f"Sold {sell_pct:.0f}% of {symbol} ({chain}) at {pnl_pct:+.1f}% | Reason: {reason}",
                {
                    "trade_id": trade_id,
                    "symbol": symbol,
                    "chain": chain,
                    "sell_pct": sell_pct,
                    "pnl_pct": pnl_pct,
                    "pnl_usd": pnl_usd,
                    "reason": reason,
                    "current_price": evaluation["current_price"],
                },
            )
            self.sell_count_today += 1

        return success

    # ── Main Loop ────────────────────────────────────────────────────

    async def check_all_positions(self):
        """Check all open positions and sell if needed."""
        # Reset daily counter
        today = datetime.now(timezone.utc).date()
        if today != self.last_reset:
            self.sell_count_today = 0
            self.last_reset = today

        # Get open positions
        open_trades = await DB.get_trades(status=TradeStatus.EXECUTED, side="buy", limit=100)
        if not open_trades:
            return

        await DB.log_event(
            "info", "position_check_start",
            f"Checking {len(open_trades)} open positions",
        )

        sold_count = 0
        for trade in open_trades:
            try:
                evaluation = await self.evaluate_position(trade)
                if evaluation["should_sell"]:
                    success = await self._execute_sell(evaluation)
                    if success:
                        sold_count += 1
            except Exception as e:
                await DB.log_event(
                    "error", "position_eval_failed",
                    f"Failed to evaluate {trade.symbol}: {str(e)}",
                    {"trade_id": trade.trade_id, "symbol": trade.symbol},
                )

        if sold_count > 0:
            await DB.log_event(
                "info", "position_check_complete",
                f"Sold {sold_count} positions today (total: {self.sell_count_today})",
            )

    async def run(self):
        """Background sell agent loop with price refresh."""
        self.running = True
        await DB.log_event("info", "sell_agent_started", "Sell agent (position manager) started with price refresh")

        price_refresh_counter = 0
        while self.running:
            try:
                # Refresh prices every 5 cycles (every ~2.5 minutes with 30s interval)
                price_refresh_counter += 1
                if price_refresh_counter >= 5:
                    await self._refresh_all_position_prices()
                    price_refresh_counter = 0
                
                await self.check_all_positions()
                # Also refresh prices for ALL watchlist coins every cycle to keep data fresh
                await self._refresh_watchlist_prices()
            except Exception as e:
                await DB.log_event("error", "sell_agent_loop_failed", str(e))
            await asyncio.sleep(settings.sell_check_interval_seconds)

    def stop(self):
        self.running = False

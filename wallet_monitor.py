"""Wallet monitor — tracks balances for both Buy Agent and Sell Agent.

Provides real-time capital allocation data so the Buy Agent knows how much
it can invest, and the Sell Agent knows when to free up capital.
"""

import asyncio
import json
from decimal import Decimal
from typing import Dict, Any, Optional, List
from datetime import datetime

import httpx

from config import get_settings
from database import DB
from models import TradeStatus

settings = get_settings()

# Birdeye API for Solana token balances
BIRDEYE_API = "https://public-api.birdeye.so"


class WalletMonitor:
    """Monitors wallet balances across chains and computes capital allocation."""

    def __init__(self):
        self.http = httpx.AsyncClient(timeout=30.0)
        self.running = False
        self._cache: Dict[str, Any] = {}
        self._cache_time: Optional[datetime] = None
        self._cache_ttl_seconds = 15
        # Rate limiters to prevent 429 errors
        self._solana_rpc_last_call = 0
        self._solana_rpc_min_interval = 1.1  # 1.1s between Solana RPC calls
        self._jupiter_last_call = 0
        self._jupiter_min_interval = 2.0  # 2s between Jupiter API calls

    async def close(self):
        await self.http.aclose()

    async def _solana_rpc_rate_limit(self):
        """Enforce minimum interval between Solana RPC calls."""
        now = asyncio.get_event_loop().time()
        elapsed = now - self._solana_rpc_last_call
        if elapsed < self._solana_rpc_min_interval:
            await asyncio.sleep(self._solana_rpc_min_interval - elapsed)
        self._solana_rpc_last_call = asyncio.get_event_loop().time()

    async def _jupiter_rate_limit(self):
        """Enforce minimum interval between Jupiter API calls."""
        now = asyncio.get_event_loop().time()
        elapsed = now - self._jupiter_last_call
        if elapsed < self._jupiter_min_interval:
            await asyncio.sleep(self._jupiter_min_interval - elapsed)
        self._jupiter_last_call = asyncio.get_event_loop().time()

    # ── Solana Balance ───────────────────────────────────────────────

    async def get_solana_balance(self) -> Dict[str, Any]:
        """Get SOL balance and token holdings on Solana."""
        if not settings.solana_wallet_address:
            return {"sol_balance": 0.0, "sol_price_usd": 0.0, "token_balances": [], "total_usd": 0.0}

        try:
            # Get SOL balance via RPC
            await self._solana_rpc_rate_limit()
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getBalance",
                "params": [settings.solana_wallet_address],
            }
            resp = await self.http.post(settings.solana_rpc, json=payload)
            resp.raise_for_status()
            data = resp.json()
            sol_lamports = data.get("result", {}).get("value", 0)
            sol_balance = sol_lamports / 1e9

            # Get SOL price
            sol_price = await self._get_sol_price()
            sol_value_usd = sol_balance * sol_price

            # Get token accounts
            await self._solana_rpc_rate_limit()
            token_payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenAccountsByOwner",
                "params": [
                    settings.solana_wallet_address,
                    {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
                    {"encoding": "jsonParsed"},
                ],
            }
            token_resp = await self.http.post(settings.solana_rpc, json=token_payload)
            token_resp.raise_for_status()
            token_data = token_resp.json()

            token_balances = []
            for account in token_data.get("result", {}).get("value", []):
                info = account.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
                mint = info.get("mint", "")
                amount = float(info.get("tokenAmount", {}).get("uiAmount", 0) or 0)
                if amount > 0 and mint != "So11111111111111111111111111111111111111112":
                    token_balances.append({"mint": mint, "amount": amount})

            return {
                "sol_balance": sol_balance,
                "sol_price_usd": sol_price,
                "token_balances": token_balances,
                "total_usd": sol_value_usd,
            }
        except Exception as e:
            await DB.log_event("error", "solana_balance_failed", str(e))
            return {"sol_balance": 0.0, "sol_price_usd": 0.0, "token_balances": [], "total_usd": 0.0}

    async def _get_sol_price(self) -> float:
        """Get SOL price in USD."""
        try:
            await self._jupiter_rate_limit()
            url = "https://api.jup.ag/price/v2"
            params = {"ids": "So11111111111111111111111111111111111111112", "vsToken": "USDC"}
            resp = await self.http.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            return float(data.get("data", {}).get("So11111111111111111111111111111111111111112", {}).get("price", 0) or 0)
        except Exception:
            return 150.0  # Fallback

    # ── Base Balance ─────────────────────────────────────────────────

    async def get_base_balance(self) -> Dict[str, Any]:
        """Get ETH balance on Base."""
        try:
            # This is a placeholder — in production use web3 or BaseScan API
            return {"eth_balance": 0.0, "eth_price_usd": 0.0, "total_usd": 0.0}
        except Exception as e:
            await DB.log_event("error", "base_balance_failed", str(e))
            return {"eth_balance": 0.0, "eth_price_usd": 0.0, "total_usd": 0.0}

    # ── Position Values ──────────────────────────────────────────────

    async def get_open_position_values(self) -> Dict[str, Any]:
        """Get current value of all open positions from the database."""
        positions = await DB.get_open_positions()
        total_invested = sum(p.get("amount_usd", 0) for p in positions)
        total_current = sum(
            (p.get("amount_usd", 0) * (1 + p.get("pnl_pct", 0) / 100))
            for p in positions
        )
        return {
            "positions": positions,
            "position_count": len(positions),
            "total_invested": total_invested,
            "total_current_value": total_current,
            "total_pnl_usd": total_current - total_invested,
            "total_pnl_pct": ((total_current - total_invested) / total_invested * 100) if total_invested > 0 else 0,
        }

    # ── Capital Allocation ───────────────────────────────────────────

    async def get_capital_allocation(self) -> Dict[str, Any]:
        """Compute full capital allocation picture."""
        now = datetime.utcnow()
        if self._cache_time and (now - self._cache_time).total_seconds() < self._cache_ttl_seconds:
            return self._cache

        solana = await self.get_solana_balance()
        positions = await self.get_open_position_values()

        liquid_sol = solana["total_usd"]
        total_liquid = liquid_sol
        total_portfolio = total_liquid + positions["total_current_value"]
        deployed_pct = (positions["total_current_value"] / total_portfolio * 100) if total_portfolio > 0 else 0
        free_pct = 100 - deployed_pct
        can_buy = free_pct >= (settings.min_free_capital_pct * 100)
        should_recycle = free_pct < (settings.min_free_capital_pct * 100) and positions["position_count"] > 0

        allocation = {
            "timestamp": now.isoformat(),
            "total_portfolio_value": total_portfolio,
            "total_liquid": total_liquid,
            "solana": solana,
            "positions": positions,
            "deployed_pct": deployed_pct,
            "free_pct": free_pct,
            "can_buy": can_buy,
            "should_recycle": should_recycle,
            "max_new_position_size": min(
                settings.max_trade_size_usd,
                total_liquid * 0.25,
            ) if can_buy else 0,
        }

        self._cache = allocation
        self._cache_time = now

        await DB.record_wallet_snapshot(
            total_balance_usd=total_portfolio,
            sol_balance=solana.get("sol_balance", 0),
            token_balances={
                "sol_balance": solana.get("sol_balance", 0),
                "sol_price": solana.get("sol_price_usd", 0),
                "position_count": positions["position_count"],
                "position_value": positions["total_current_value"],
            },
        )

        return allocation

    # ── Background Loop ──────────────────────────────────────────────

    async def run(self):
        """Background wallet monitor loop."""
        self.running = True
        while self.running:
            try:
                allocation = await self.get_capital_allocation()
                await DB.log_event(
                    "info", "wallet_snapshot",
                    f"Portfolio: ${allocation['total_portfolio_value']:.2f} | "
                    f"Liquid: ${allocation['total_liquid']:.2f} | "
                    f"Positions: {allocation['positions']['position_count']} | "
                    f"Deployed: {allocation['deployed_pct']:.1f}%",
                    {"allocation": allocation},
                )
            except Exception as e:
                await DB.log_event("error", "wallet_monitor_failed", str(e))
            await asyncio.sleep(60)

    def stop(self):
        self.running = False

"""Trade executor — paper and live trading via Odos router."""

import asyncio
import json
import uuid
from decimal import Decimal
from typing import Optional

import httpx
from web3 import Web3

from config import get_settings
from database import DB
from models import TradeStatus

settings = get_settings()

# Base chain RPC
BASE_RPC = "https://mainnet.base.org"
ODOS_API = "https://api.odos.xyz"

# Odos router on Base
ODOS_ROUTER = "0x19cEeAdF6158dE9B5a5e68EED30Eab821b2E749e"

# WETH on Base
WETH = "0x4200000000000000000000000000000000000006"


class Executor:
    """Executes trades via Odos DEX aggregator."""

    def __init__(self):
        self.http = httpx.AsyncClient(timeout=60.0)
        self.w3 = Web3(Web3.HTTPProvider(BASE_RPC))
        self.running = False

    async def close(self):
        await self.http.aclose()

    # ── Odos Quote & Swap ────────────────────────────────────────────

    async def get_quote(
        self,
        token_in: str,
        token_out: str,
        amount_in: str,
        sender: str,
    ) -> dict:
        """Get Odos swap quote."""
        url = f"{ODOS_API}/sor/quote/v2"
        payload = {
            "chainId": 8453,
            "inputTokens": [{"tokenAddress": token_in, "amount": amount_in}],
            "outputTokens": [{"tokenAddress": token_out, "proportion": 1}],
            "userAddr": sender,
            "slippageLimitPercent": settings.max_slippage * 100,
            "sourceBlacklist": [],
            "sourceWhitelist": [],
            "simulate": settings.is_paper,
            "pathViz": False,
        }
        resp = await self.http.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()

    async def assemble_tx(self, path_id: str, sender: str) -> dict:
        """Assemble the transaction from Odos."""
        url = f"{ODOS_API}/sor/assemble"
        payload = {"userAddr": sender, "pathId": path_id, "simulate": settings.is_paper}
        resp = await self.http.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()

    # ── Trade Execution ──────────────────────────────────────────────

    async def execute_buy(
        self,
        token_address: str,
        symbol: str,
        amount_usd: float,
        signal: str,
        confidence: float,
    ) -> Optional[str]:
        """Execute a buy trade. Returns trade_id or None."""
        trade_id = f"T-{uuid.uuid4().hex[:12].upper()}"

        # Create pending trade record
        await DB.create_trade(
            trade_id=trade_id,
            token_address=token_address,
            symbol=symbol,
            side="buy",
            status=TradeStatus.PENDING,
            amount_usd=amount_usd,
            signal=signal,
            confidence=confidence,
            is_paper=settings.is_paper,
        )

        try:
            if settings.is_paper:
                # Paper trade: simulate without real execution
                await asyncio.sleep(0.5)
                await DB.update_trade(
                    trade_id=trade_id,
                    status=TradeStatus.EXECUTED,
                    executed_at=datetime.utcnow(),
                    entry_price=amount_usd,  # simplified
                    tx_hash=f"PAPER-{uuid.uuid4().hex[:16]}",
                )
                await DB.log_event(
                    "info", "paper_trade_executed",
                    f"Paper buy {symbol} for ${amount_usd}",
                    token_address=token_address,
                    symbol=symbol,
                    data=json.dumps({"trade_id": trade_id, "amount_usd": amount_usd}),
                )
            else:
                # Live trade via Odos
                amount_wei = str(int(amount_usd * 1e18))  # Simplified: assumes ETH input
                quote = await self.get_quote(WETH, token_address, amount_wei, settings.base_wallet_address)
                path_id = quote["pathId"]

                assembled = await self.assemble_tx(path_id, settings.base_wallet_address)
                tx = assembled["transaction"]

                # Sign and send
                private_key = settings.base_wallet_private_key.get_secret_value()
                signed = self.w3.eth.account.sign_transaction(tx, private_key)
                tx_hash = self.w3.eth.send_raw_transaction(signed.rawTransaction)

                await DB.update_trade(
                    trade_id=trade_id,
                    status=TradeStatus.EXECUTED,
                    executed_at=datetime.utcnow(),
                    tx_hash=tx_hash.hex(),
                )
                await DB.log_event(
                    "info", "live_trade_executed",
                    f"Live buy {symbol} for ${amount_usd}",
                    token_address=token_address,
                    symbol=symbol,
                    data=json.dumps({"trade_id": trade_id, "tx_hash": tx_hash.hex()}),
                )

            return trade_id

        except Exception as e:
            await DB.update_trade(trade_id=trade_id, status=TradeStatus.FAILED)
            await DB.log_event(
                "error", "trade_execution_failed", str(e),
                token_address=token_address,
                symbol=symbol,
                data=json.dumps({"trade_id": trade_id}),
            )
            return None

    async def execute_sell(
        self,
        token_address: str,
        symbol: str,
        amount_token: float,
        trade_id: str,
        reason: str = "signal",
    ) -> bool:
        """Execute a sell to close a position."""
        try:
            if settings.is_paper:
                await asyncio.sleep(0.3)
                await DB.update_trade(
                    trade_id=trade_id,
                    status=TradeStatus.CLOSED,
                    closed_at=datetime.utcnow(),
                    close_reason=reason,
                    exit_price=amount_token,  # simplified
                )
            else:
                # Live sell via Odos
                amount_wei = str(int(amount_token * 1e18))
                quote = await self.get_quote(token_address, WETH, amount_wei, settings.base_wallet_address)
                assembled = await self.assemble_tx(quote["pathId"], settings.base_wallet_address)
                tx = assembled["transaction"]

                private_key = settings.base_wallet_private_key.get_secret_value()
                signed = self.w3.eth.account.sign_transaction(tx, private_key)
                tx_hash = self.w3.eth.send_raw_transaction(signed.rawTransaction)

                await DB.update_trade(
                    trade_id=trade_id,
                    status=TradeStatus.CLOSED,
                    closed_at=datetime.utcnow(),
                    close_reason=reason,
                    tx_hash=tx_hash.hex(),
                )

            await DB.log_event(
                "info", "position_closed",
                f"Closed {symbol}: {reason}",
                token_address=token_address,
                symbol=symbol,
                data=json.dumps({"trade_id": trade_id, "reason": reason}),
            )
            return True

        except Exception as e:
            await DB.log_event(
                "error", "sell_execution_failed", str(e),
                token_address=token_address,
                symbol=symbol,
            )
            return False

    # ── Position Manager ─────────────────────────────────────────────

    async def check_positions(self):
        """Check open positions for stop-loss / take-profit."""
        open_trades = await DB.get_trades(status=TradeStatus.EXECUTED, limit=100)
        for trade in open_trades:
            # In a real implementation, fetch current price and compare to entry
            # For now, simplified check based on stored data
            pass

    async def run(self):
        """Background position manager loop."""
        self.running = True
        while self.running:
            try:
                await self.check_positions()
            except Exception as e:
                await DB.log_event("error", "position_check_failed", str(e))
            await asyncio.sleep(60)

    def stop(self):
        self.running = False


# Import datetime at module level for executor
from datetime import datetime

"""Trade executor — paper and live trading via Jupiter (Solana only)."""

import asyncio
import uuid
from datetime import datetime
from typing import Optional, Dict, Any

import httpx

from config import get_settings
from database import DB
from models import TradeStatus
from jupiter_client import get_jupiter
from solana_client import SolanaClient
from solana_price_client import get_solana_price_client

settings = get_settings()

# Solana config
SOLANA_RPC = "https://api.mainnet-beta.solana.com"
JUPITER_API = "https://quote-api.jup.ag/v6"
WSOL = "So11111111111111111111111111111111111111112"  # Wrapped SOL


class Executor:
    """Executes trades via Jupiter on Solana."""

    def __init__(self):
        self.http = httpx.AsyncClient(timeout=60.0)
        self.jupiter = get_jupiter()
        self.solana = SolanaClient(
            rpc_url=settings.solana_rpc,
            private_key=settings.solana_wallet_private_key.get_secret_value() if settings.solana_wallet_private_key else None,
        )
        self.running = False
        # Rate limit tracking for Jupiter
        self._jupiter_last_call = 0
        self._jupiter_min_interval = 2.0  # 2s between Jupiter API calls to avoid 429

    async def close(self):
        await self.http.aclose()
        await self.jupiter.close()
        await self.solana.close()
        price_client = await get_solana_price_client()
        await price_client.close()

    # ── Jupiter (Solana) ─────────────────────────────────────────────

    async def get_jupiter_quote(
        self,
        input_mint: str,
        output_mint: str,
        amount: int,
    ) -> dict:
        """Get Jupiter swap quote with rate limiting."""
        now = asyncio.get_event_loop().time()
        elapsed = now - self._jupiter_last_call
        if elapsed < self._jupiter_min_interval:
            await asyncio.sleep(self._jupiter_min_interval - elapsed)
        self._jupiter_last_call = asyncio.get_event_loop().time()
        
        return await self.jupiter.get_quote(input_mint, output_mint, amount)

    async def get_jupiter_swap_tx(
        self,
        quote_response: dict,
        user_public_key: str,
    ) -> dict:
        """Get serialized Jupiter swap transaction with rate limiting."""
        now = asyncio.get_event_loop().time()
        elapsed = now - self._jupiter_last_call
        if elapsed < self._jupiter_min_interval:
            await asyncio.sleep(self._jupiter_min_interval - elapsed)
        self._jupiter_last_call = asyncio.get_event_loop().time()
        
        return await self.jupiter.get_swap_transaction(quote_response, user_public_key)

    # ── Trade Execution ──────────────────────────────────────────────

    async def execute_buy(
        self,
        token_address: str,
        symbol: str,
        amount_usd: float,
        signal: str,
        confidence: float,
        chain: str = "solana",
    ) -> Optional[str]:
        """Execute a buy trade. Returns trade_id or None."""
        
        # ENFORCE LIVE MODE ONLY - No paper trades
        if not settings.is_live:
            await DB.log_event(
                "warning", "trade_rejected",
                f"Buy {symbol} rejected: AGENT_MODE is not 'live'. Set AGENT_MODE=live for real trading.",
                {"token_address": token_address, "symbol": symbol},
            )
            return None
        
        trade_id = f"T-{uuid.uuid4().hex[:12].upper()}"

        # Create pending trade record
        await DB.create_trade(
            trade_id=trade_id,
            token_address=token_address,
            chain="solana",
            symbol=symbol,
            side="buy",
            status=TradeStatus.PENDING,
            amount_usd=amount_usd,
            signal=signal,
            confidence=confidence,
            is_paper=False,  # ALWAYS live
        )

        try:
            # Get actual token price at time of purchase for proper PNL tracking
            price_client = await get_solana_price_client()
            actual_token_price = await price_client.get_price(token_address, vs_token="USDC")
            if actual_token_price is None or actual_token_price <= 0:
                # Fallback: try DexScreener directly
                actual_token_price = await self._fetch_dexscreener_price(token_address)
                if actual_token_price is None or actual_token_price <= 0:
                    await DB.update_trade(trade_id=trade_id, status=TradeStatus.FAILED)
                    await DB.log_event(
                        "error", "trade_price_fetch_failed",
                        f"Could not fetch price for {symbol} — trade aborted",
                        {"token_address": token_address, "symbol": symbol, "trade_id": trade_id},
                    )
                    return None

            # Calculate token quantity bought
            amount_token = amount_usd / actual_token_price if actual_token_price > 0 else 0

            # Update coin price in database so position manager can find it
            await DB.update_coin_market_data(
                token_address=token_address,
                price_usd=actual_token_price,
            )

            # LIVE TRADE ONLY - Execute on Solana via Jupiter
            await self._execute_solana_buy(trade_id, token_address, symbol, amount_usd, actual_token_price, amount_token)

            return trade_id

        except Exception as e:
            await DB.update_trade(trade_id=trade_id, status=TradeStatus.FAILED)
            await DB.log_event(
                "error", "trade_execution_failed", str(e),
                {"token_address": token_address, "symbol": symbol, "trade_id": trade_id},
            )
            return None

    async def _fetch_dexscreener_price(self, token_address: str) -> Optional[float]:
        """Fallback price fetch from DexScreener."""
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            resp = await self.http.get(url, timeout=10.0)
            resp.raise_for_status()
            data = resp.json()
            pairs = data.get("pairs", [])
            if pairs:
                best = max(pairs, key=lambda p: float(p.get("liquidity", {}).get("usd", 0) or 0))
                price = float(best.get("priceUsd", 0))
                return price if price > 0 else None
        except Exception:
            pass
        return None

    async def _execute_solana_buy(
        self, trade_id: str, token_address: str, symbol: str, amount_usd: float,
        actual_token_price: float, amount_token: float
    ):
        """Execute a live buy on Solana via Jupiter."""
        if not self.solana.is_loaded:
            raise RuntimeError("Solana wallet not configured — set SOLANA_WALLET_PRIVATE_KEY and SOLANA_WALLET_ADDRESS")

        if not settings.solana_wallet_address:
            raise RuntimeError("SOLANA_WALLET_ADDRESS not set")

        # Fetch real SOL price using multi-source client with fallback chain
        price_client = await get_solana_price_client()
        sol_price = await price_client.get_price(WSOL, vs_token="USDC")
        
        if sol_price is None or sol_price <= 0:
            raise RuntimeError("Could not fetch SOL price from any source for trade sizing")

        amount_lamports = int((amount_usd / sol_price) * 1e9)

        # Check wallet has enough SOL (with 0.005 SOL buffer for fees)
        balance = await self.solana.get_balance()
        if balance < amount_lamports + 5_000_000:
            try:
                fee_estimate = await self.solana.get_fee_estimate()
                required_lamports = amount_lamports + fee_estimate
            except Exception:
                required_lamports = amount_lamports + 5_000_000
            
            if balance < required_lamports:
                raise RuntimeError(
                    f"Insufficient SOL balance: {balance / 1e9:.6f} SOL "
                    f"(need {(amount_lamports / 1e9):.6f} + {(required_lamports - amount_lamports) / 1e9:.6f} fee). "
                    f"Fund wallet {settings.solana_wallet_address} with more SOL."
                )

        # Get Jupiter quote for the swap
        quote = await self.get_jupiter_quote(WSOL, token_address, amount_lamports)
        swap_tx_data = await self.get_jupiter_swap_tx(quote, settings.solana_wallet_address)

        swap_tx_b64 = swap_tx_data.get("swapTransaction")
        if not swap_tx_b64:
            raise RuntimeError("Jupiter did not return swap transaction")

        # Sign and send
        signed_tx = self.solana.sign_jupiter_swap(swap_tx_b64)
        signature = await self.solana.send_transaction(signed_tx)

        # Confirm
        await self.solana.confirm_transaction(signature, timeout_sec=60)

        await DB.update_trade(
            trade_id=trade_id,
            status=TradeStatus.EXECUTED,
            executed_at=datetime.utcnow(),
            entry_price=actual_token_price,
            amount_token=amount_token,
            tx_hash=signature,
        )
        await DB.log_event(
            "info", "live_trade_executed",
            f"Live buy {symbol} (Solana) for ${amount_usd} at ${actual_token_price:.8f}/token",
            {"token_address": token_address, "symbol": symbol, "chain": "solana",
             "trade_id": trade_id, "tx_hash": signature, "entry_price": actual_token_price},
        )

    async def execute_sell(
        self,
        token_address: str,
        symbol: str,
        amount_token: float,
        trade_id: str,
        chain: str = "solana",
        reason: str = "signal",
    ) -> bool:
        """Execute a sell to close a position. LIVE ONLY."""
        
        # ENFORCE LIVE MODE ONLY
        if not settings.is_live:
            await DB.log_event(
                "warning", "sell_rejected",
                f"Sell {symbol} rejected: AGENT_MODE is not 'live'.",
                {"token_address": token_address, "symbol": symbol, "trade_id": trade_id},
            )
            return False
        
        try:
            await self._execute_solana_sell(trade_id, token_address, symbol, amount_token)

            await DB.log_event(
                "info", "position_closed",
                f"Closed {symbol}: {reason}",
                {"token_address": token_address, "symbol": symbol,
                 "trade_id": trade_id, "reason": reason},
            )
            return True

        except Exception as e:
            await DB.log_event(
                "error", "sell_execution_failed", str(e),
                {"token_address": token_address, "symbol": symbol},
            )
            return False

    async def _execute_solana_sell(
        self, trade_id: str, token_address: str, symbol: str, amount_token: float
    ):
        """Execute a live sell on Solana via Jupiter."""
        if not self.solana.is_loaded:
            raise RuntimeError("Solana wallet not configured")

        if not settings.solana_wallet_address:
            raise RuntimeError("SOLANA_WALLET_ADDRESS not set")

        # Convert token amount to raw amount (assuming 6 decimals)
        amount_raw = int(amount_token * 1e6)

        quote = await self.get_jupiter_quote(token_address, WSOL, amount_raw)
        swap_tx_data = await self.get_jupiter_swap_tx(quote, settings.solana_wallet_address)

        swap_tx_b64 = swap_tx_data.get("swapTransaction")
        if not swap_tx_b64:
            raise RuntimeError("Jupiter did not return swap transaction")

        signed_tx = self.solana.sign_jupiter_swap(swap_tx_b64)
        signature = await self.solana.send_transaction(signed_tx)
        await self.solana.confirm_transaction(signature, timeout_sec=60)

        # Get exit price for PNL tracking
        price_client = await get_solana_price_client()
        exit_price = await price_client.get_price(token_address, vs_token="USDC")
        if exit_price is None or exit_price <= 0:
            exit_price = 0

        await DB.update_trade(
            trade_id=trade_id,
            status=TradeStatus.CLOSED,
            closed_at=datetime.utcnow(),
            close_reason="signal",
            exit_price=exit_price,
            tx_hash=signature,
        )

    async def run(self):
        """Background position manager loop (deprecated — use position_manager.py)."""
        self.running = True
        while self.running:
            try:
                await asyncio.sleep(60)
            except Exception as e:
                await DB.log_event("error", "executor_loop_failed", str(e))
                await asyncio.sleep(60)

    def stop(self):
        self.running = False

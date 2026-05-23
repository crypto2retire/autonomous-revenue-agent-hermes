"""Trade executor — paper and live trading via Odos V3 (Base) or Jupiter (Solana)."""

import asyncio
import json
import uuid
from decimal import Decimal
from typing import Optional, Dict, Any

import httpx
try:
    from web3 import Web3
except ModuleNotFoundError:  # Paper mode does not need web3 installed locally.
    Web3 = None

from config import get_settings
from database import DB
from models import TradeStatus
from jupiter_client import get_jupiter
from solana_client import SolanaClient
from solana_price_client import get_solana_price_client

settings = get_settings()

# Base chain config
BASE_RPC = "https://mainnet.base.org"
ODOS_API = "https://api.odos.xyz"
ODOS_ROUTER_V3 = "0x0D05a7D3448512B78fa8A9e46c4872C88C4a0D05"
WETH = "0x4200000000000000000000000000000000000006"

# Solana config
SOLANA_RPC = "https://api.mainnet-beta.solana.com"
JUPITER_API = "https://quote-api.jup.ag/v6"
WSOL = "So11111111111111111111111111111111111111112"  # Wrapped SOL


class Executor:
    """Executes trades via Odos V3 (Base) or Jupiter (Solana)."""

    def __init__(self):
        self.http = httpx.AsyncClient(timeout=60.0)
        self.w3 = Web3(Web3.HTTPProvider(BASE_RPC)) if Web3 is not None else None
        self.jupiter = get_jupiter()
        self.solana = SolanaClient(
            rpc_url=settings.solana_rpc,
            private_key=settings.solana_wallet_private_key.get_secret_value() if settings.solana_wallet_private_key else None,
        )
        self.running = False
        # Rate limit tracking for Odos
        self._odos_last_call = 0
        self._odos_min_interval = 1.1  # 1.1s — free tier is 1 RPS, stay slightly under

    def _odos_headers(self) -> Dict[str, str]:
        """Build Odos request headers. Include API key if configured."""
        headers = {"Content-Type": "application/json"}
        if settings.odos_api_key:
            headers["x-api-key"] = settings.odos_api_key.get_secret_value()
        return headers

    async def close(self):
        await self.http.aclose()
        await self.jupiter.close()
        await self.solana.close()
        price_client = await get_solana_price_client()
        await price_client.close()

    # ── Odos V3 (Base) ───────────────────────────────────────────────

    async def _odos_rate_limit(self):
        """Enforce minimum interval between Odos API calls."""
        now = asyncio.get_event_loop().time()
        elapsed = now - self._odos_last_call
        if elapsed < self._odos_min_interval:
            await asyncio.sleep(self._odos_min_interval - elapsed)
        self._odos_last_call = asyncio.get_event_loop().time()

    async def _odos_post(self, url: str, payload: dict) -> dict:
        """POST to Odos with rate limiting, retries, and auth."""
        await self._odos_rate_limit()
        headers = self._odos_headers()
        for attempt in range(3):
            try:
                resp = await self.http.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    wait = (attempt + 1) * 5  # Wait longer: 5s, 10s, 15s
                    await DB.log_event(
                        "warning", "odos_rate_limited",
                        f"Attempt {attempt + 1}/3, waiting {wait}s",
                        {"url": url},
                    )
                    await asyncio.sleep(wait)
                    continue
                elif e.response.status_code == 400:
                    # Log the error response for debugging
                    error_text = e.response.text
                    await DB.log_event(
                        "error", "odos_bad_request",
                        f"Odos 400: {error_text[:200]}",
                        {"url": url, "payload": str(payload)[:500]},
                    )
                    raise RuntimeError(f"Odos API bad request: {error_text[:200]}")
                raise
        raise RuntimeError(f"Odos API rate limited after 3 retries: {url}")

    async def get_odos_quote(
        self,
        token_in: str,
        token_out: str,
        amount_in: str,
        sender: str,
    ) -> dict:
        """Get Odos V3 swap quote."""
        url = f"{ODOS_API}/sor/quote/v3"
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
            "compact": True,
        }
        return await self._odos_post(url, payload)

    async def assemble_odos_tx(self, path_id: str, sender: str) -> dict:
        """Assemble the transaction from Odos V3 quote."""
        url = f"{ODOS_API}/sor/assemble"
        payload = {"userAddr": sender, "pathId": path_id, "simulate": settings.is_paper}
        return await self._odos_post(url, payload)

    # ── Jupiter (Solana) ─────────────────────────────────────────────

    async def get_jupiter_quote(
        self,
        input_mint: str,
        output_mint: str,
        amount: int,
    ) -> dict:
        """Get Jupiter swap quote."""
        return await self.jupiter.get_quote(input_mint, output_mint, amount)

    async def get_jupiter_swap_tx(
        self,
        quote_response: dict,
        user_public_key: str,
    ) -> dict:
        """Get serialized Jupiter swap transaction."""
        return await self.jupiter.get_swap_transaction(quote_response, user_public_key)

    # ── Trade Execution ──────────────────────────────────────────────

    async def execute_buy(
        self,
        token_address: str,
        symbol: str,
        amount_usd: float,
        signal: str,
        confidence: float,
        chain: str = "base",
    ) -> Optional[str]:
        """Execute a buy trade. Returns trade_id or None."""
        trade_id = f"T-{uuid.uuid4().hex[:12].upper()}"

        # Create pending trade record
        await DB.create_trade(
            trade_id=trade_id,
            token_address=token_address,
            chain=chain,
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
                    entry_price=amount_usd,
                    tx_hash=f"PAPER-{uuid.uuid4().hex[:16]}",
                )
                await DB.log_event(
                    "info", "paper_trade_executed",
                    f"Paper buy {symbol} ({chain}) for ${amount_usd}",
                    {"token_address": token_address, "symbol": symbol, "chain": chain,
                     "trade_id": trade_id, "amount_usd": amount_usd},
                )
            else:
                # Live trade
                if chain.lower() == "solana":
                    await self._execute_solana_buy(trade_id, token_address, symbol, amount_usd)
                else:
                    await self._execute_base_buy(trade_id, token_address, symbol, amount_usd)

            return trade_id

        except Exception as e:
            await DB.update_trade(trade_id=trade_id, status=TradeStatus.FAILED)
            await DB.log_event(
                "error", "trade_execution_failed", str(e),
                {"token_address": token_address, "symbol": symbol, "chain": chain, "trade_id": trade_id},
            )
            return None

    async def _execute_base_buy(
        self, trade_id: str, token_address: str, symbol: str, amount_usd: float
    ):
        """Execute a live buy on Base via Odos V3."""
        if self.w3 is None:
            raise RuntimeError("web3 is required for live Base trading")

        amount_wei = str(int(amount_usd * 1e18))
        quote = await self.get_odos_quote(WETH, token_address, amount_wei, settings.base_wallet_address)
        path_id = quote["pathId"]

        assembled = await self.assemble_odos_tx(path_id, settings.base_wallet_address)
        tx = assembled["transaction"]

        private_key = settings.base_wallet_private_key.get_secret_value()
        signed = self.w3.eth.account.sign_transaction(tx, private_key)
        raw_tx = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction")
        tx_hash = self.w3.eth.send_raw_transaction(raw_tx)

        await DB.update_trade(
            trade_id=trade_id,
            status=TradeStatus.EXECUTED,
            executed_at=datetime.utcnow(),
            tx_hash=tx_hash.hex(),
        )
        await DB.log_event(
            "info", "live_trade_executed",
            f"Live buy {symbol} (Base) for ${amount_usd}",
            {"token_address": token_address, "symbol": symbol, "chain": "base",
             "trade_id": trade_id, "tx_hash": tx_hash.hex()},
        )

    async def _execute_solana_buy(
        self, trade_id: str, token_address: str, symbol: str, amount_usd: float
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
            raise RuntimeError("Could not fetch SOL price from any source (Jupiter, DexScreener, CoinGecko) for trade sizing")

        amount_lamports = int((amount_usd / sol_price) * 1e9)

        # Check wallet has enough SOL (with 0.005 SOL buffer for fees)
        balance = await self.solana.get_balance()
        if balance < amount_lamports + 5_000_000:
            # Try to get exact fee estimate
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
            tx_hash=signature,
        )
        await DB.log_event(
            "info", "live_trade_executed",
            f"Live buy {symbol} (Solana) for ${amount_usd}",
            {"token_address": token_address, "symbol": symbol, "chain": "solana",
             "trade_id": trade_id, "tx_hash": signature},
        )

    async def execute_sell(
        self,
        token_address: str,
        symbol: str,
        amount_token: float,
        trade_id: str,
        chain: str = "base",
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
                    exit_price=amount_token,
                )
            else:
                if chain.lower() == "solana":
                    await self._execute_solana_sell(trade_id, token_address, symbol, amount_token)
                else:
                    await self._execute_base_sell(trade_id, token_address, symbol, amount_token)

            await DB.log_event(
                "info", "position_closed",
                f"Closed {symbol} ({chain}): {reason}",
                {"token_address": token_address, "symbol": symbol, "chain": chain,
                 "trade_id": trade_id, "reason": reason},
            )
            return True

        except Exception as e:
            await DB.log_event(
                "error", "sell_execution_failed", str(e),
                {"token_address": token_address, "symbol": symbol, "chain": chain},
            )
            return False

    async def _execute_base_sell(
        self, trade_id: str, token_address: str, symbol: str, amount_token: float
    ):
        """Execute a live sell on Base via Odos V3."""
        if self.w3 is None:
            raise RuntimeError("web3 is required for live Base trading")

        amount_wei = str(int(amount_token * 1e18))
        quote = await self.get_odos_quote(token_address, WETH, amount_wei, settings.base_wallet_address)
        assembled = await self.assemble_odos_tx(quote["pathId"], settings.base_wallet_address)
        tx = assembled["transaction"]

        private_key = settings.base_wallet_private_key.get_secret_value()
        signed = self.w3.eth.account.sign_transaction(tx, private_key)
        raw_tx = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction")
        tx_hash = self.w3.eth.send_raw_transaction(raw_tx)

        await DB.update_trade(
            trade_id=trade_id,
            status=TradeStatus.CLOSED,
            closed_at=datetime.utcnow(),
            close_reason="signal",
            tx_hash=tx_hash.hex(),
        )

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

        await DB.update_trade(
            trade_id=trade_id,
            status=TradeStatus.CLOSED,
            closed_at=datetime.utcnow(),
            close_reason="signal",
            tx_hash=signature,
        )

    # ── Position Manager ─────────────────────────────────────────────

    async def check_positions(self):
        """Check open positions for stop-loss / take-profit."""
        open_trades = await DB.get_trades(status=TradeStatus.EXECUTED, limit=100)
        for trade in open_trades:
            # In a real implementation, fetch current price and compare to entry
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

"""Jupiter API client for Solana swaps."""

import asyncio
import httpx
from typing import Optional, Dict, Any

JUPITER_API = "https://api.jup.ag"
JUPITER_V6 = "https://api.jup.ag/swap/v1"


class JupiterClient:
    """Client for Jupiter DEX aggregator on Solana."""

    def __init__(self):
        self.http = httpx.AsyncClient(timeout=60.0)

    async def close(self):
        await self.http.aclose()

    async def get_quote(
        self,
        input_mint: str,
        output_mint: str,
        amount: int,
        slippage_bps: int = 50,
    ) -> Dict[str, Any]:
        """Get swap quote from Jupiter with retry logic."""
        url = f"{JUPITER_V6}/quote"
        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(amount),
            "slippageBps": slippage_bps,
        }
        
        last_error = None
        for attempt in range(3):
            try:
                resp = await self.http.get(url, params=params, timeout=15.0)
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                last_error = e
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)  # 1s, 2s, 4s
                continue
        
        raise RuntimeError(f"Jupiter quote failed after 3 attempts: {last_error}")

    async def get_swap_transaction(
        self,
        quote_response: Dict[str, Any],
        user_public_key: str,
        wrap_unwrap_sol: bool = True,
    ) -> Dict[str, Any]:
        """Get serialized swap transaction from Jupiter with retry."""
        url = f"{JUPITER_V6}/swap"
        payload = {
            "quoteResponse": quote_response,
            "userPublicKey": user_public_key,
            "wrapAndUnwrapSol": wrap_unwrap_sol,
            "prioritizationFeeLamports": "auto",
            "dynamicComputeUnitLimit": True,
            "skipUserAccountsRpcCalls": False,
        }
        
        last_error = None
        for attempt in range(3):
            try:
                resp = await self.http.post(url, json=payload, timeout=15.0)
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                last_error = e
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                continue
        
        raise RuntimeError(f"Jupiter swap transaction failed after 3 attempts: {last_error}")

    async def get_price(self, mint: str, vs_token: str = "USDC") -> Optional[float]:
        """Get token price from Jupiter price API v3."""
        url = f"{JUPITER_API}/price/v3"
        params = {"ids": mint}
        try:
            resp = await self.http.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            price_data = data.get(mint, {})
            return float(price_data.get("usdPrice", 0))
        except Exception:
            return None


# Singleton
_jupiter: Optional[JupiterClient] = None


def get_jupiter() -> JupiterClient:
    global _jupiter
    if _jupiter is None:
        _jupiter = JupiterClient()
    return _jupiter

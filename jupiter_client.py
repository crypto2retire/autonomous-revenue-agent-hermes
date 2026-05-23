"""Jupiter API client for Solana swaps."""

import httpx
from typing import Optional, Dict, Any

JUPITER_API = "https://api.jup.ag"
JUPITER_V6 = "https://quote-api.jup.ag/v6"


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
        """Get swap quote from Jupiter."""
        url = f"{JUPITER_V6}/quote"
        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(amount),
            "slippageBps": slippage_bps,
        }
        resp = await self.http.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_swap_transaction(
        self,
        quote_response: Dict[str, Any],
        user_public_key: str,
        wrap_unwrap_sol: bool = True,
    ) -> Dict[str, Any]:
        """Get serialized swap transaction from Jupiter."""
        url = f"{JUPITER_V6}/swap"
        payload = {
            "quoteResponse": quote_response,
            "userPublicKey": user_public_key,
            "wrapAndUnwrapSol": wrap_unwrap_sol,
            "prioritizationFeeLamports": "auto",
        }
        resp = await self.http.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()

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

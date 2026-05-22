"""CoinGecko API client for crypto market data and on-chain DEX analytics."""

import asyncio
from typing import Any, Dict, List, Optional

import httpx

from config import get_settings

settings = get_settings()

# Base URLs
DEMO_BASE = "https://api.coingecko.com/api/v3"
PRO_BASE = "https://pro-api.coingecko.com/api/v3"

# Auth headers
DEMO_HEADER = "x-cg-demo-api-key"
PRO_HEADER = "x-cg-pro-api-key"


class CoinGeckoClient:
    """Async CoinGecko API client."""

    def __init__(self):
        self.plan = settings.coingecko_plan
        self.api_key = settings.coingecko_api_key
        self.base_url = PRO_BASE if self.plan == "pro" else DEMO_BASE
        self.header_name = PRO_HEADER if self.plan == "pro" else DEMO_HEADER
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    def _headers(self) -> Dict[str, str]:
        if self.api_key:
            return {self.header_name: self.api_key.get_secret_value()}
        return {}

    async def _get(self, endpoint: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Make a GET request to CoinGecko API."""
        client = await self._get_client()
        url = f"{self.base_url}{endpoint}"
        resp = await client.get(url, params=params, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    # ── Simple Price ───────────────────────────────────────────────────

    async def get_price(
        self,
        ids: List[str],
        vs_currencies: List[str] = None,
        include_market_cap: bool = False,
        include_24hr_vol: bool = False,
        include_24hr_change: bool = False,
        include_last_updated_at: bool = False,
    ) -> Dict[str, Any]:
        """Get current price for coins by CoinGecko ID."""
        vs_currencies = vs_currencies or ["usd"]
        params = {
            "ids": ",".join(ids),
            "vs_currencies": ",".join(vs_currencies),
            "include_market_cap": str(include_market_cap).lower(),
            "include_24hr_vol": str(include_24hr_vol).lower(),
            "include_24hr_change": str(include_24hr_change).lower(),
            "include_last_updated_at": str(include_last_updated_at).lower(),
        }
        return await self._get("/simple/price", params)

    async def get_token_price_by_contract(
        self,
        platform: str,
        contract_addresses: List[str],
        vs_currencies: List[str] = None,
    ) -> Dict[str, Any]:
        """Get price by contract address (e.g., ethereum, base)."""
        vs_currencies = vs_currencies or ["usd"]
        params = {
            "contract_addresses": ",".join(contract_addresses),
            "vs_currencies": ",".join(vs_currencies),
        }
        return await self._get(f"/simple/token_price/{platform}", params)

    # ── Coins / Markets ────────────────────────────────────────────────

    async def get_coins_markets(
        self,
        vs_currency: str = "usd",
        ids: Optional[List[str]] = None,
        category: Optional[str] = None,
        order: str = "market_cap_desc",
        per_page: int = 100,
        page: int = 1,
        sparkline: bool = False,
        price_change_percentage: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get market data for coins (ranking, prices, volume, etc.)."""
        params: Dict[str, Any] = {
            "vs_currency": vs_currency,
            "order": order,
            "per_page": per_page,
            "page": page,
            "sparkline": str(sparkline).lower(),
        }
        if ids:
            params["ids"] = ",".join(ids)
        if category:
            params["category"] = category
        if price_change_percentage:
            params["price_change_percentage"] = price_change_percentage
        return await self._get("/coins/markets", params)

    async def get_coin(self, coin_id: str) -> Dict[str, Any]:
        """Get detailed info for a coin."""
        params = {
            "localization": "false",
            "tickers": "false",
            "community_data": "false",
            "developer_data": "false",
        }
        return await self._get(f"/coins/{coin_id}", params)

    async def get_coin_market_chart(
        self,
        coin_id: str,
        vs_currency: str = "usd",
        days: str = "30",
    ) -> Dict[str, Any]:
        """Get historical market data (prices, market_caps, total_volumes)."""
        params = {"vs_currency": vs_currency, "days": days}
        return await self._get(f"/coins/{coin_id}/market_chart", params)

    async def get_coin_ohlc(
        self,
        coin_id: str,
        vs_currency: str = "usd",
        days: str = "30",
    ) -> List[List[float]]:
        """Get OHLC candlestick data."""
        params = {"vs_currency": vs_currency, "days": days}
        return await self._get(f"/coins/{coin_id}/ohlc", params)

    # ── Search & Discovery ─────────────────────────────────────────────

    async def search(self, query: str) -> Dict[str, Any]:
        """Search for coins, exchanges, categories by name/symbol."""
        return await self._get("/search", {"query": query})

    async def get_trending(self) -> Dict[str, Any]:
        """Get trending coins, NFTs, and categories."""
        return await self._get("/search/trending")

    async def get_top_gainers_losers(
        self,
        vs_currency: str = "usd",
        duration: str = "24h",
        top_coins: str = "1000",
    ) -> Dict[str, Any]:
        """Get top gainers and losers."""
        params = {
            "vs_currency": vs_currency,
            "duration": duration,
            "top_coins": top_coins,
        }
        return await self._get("/coins/top_gainers_losers", params)

    async def get_new_coins(self) -> List[Dict[str, Any]]:
        """Get newly listed coins."""
        return await self._get("/coins/list/new")

    async def get_coins_list(self) -> List[Dict[str, Any]]:
        """Get full list of supported coins with IDs."""
        return await self._get("/coins/list")

    # ── Categories ─────────────────────────────────────────────────────

    async def get_categories(self) -> List[Dict[str, Any]]:
        """Get coin categories with market data."""
        return await self._get("/coins/categories")

    # ── GeckoTerminal (On-Chain DEX) ───────────────────────────────────

    async def get_onchain_token_price(
        self,
        network: str,
        token_address: str,
    ) -> Dict[str, Any]:
        """Get token price by contract address on a network."""
        return await self._get(
            f"/onchain/simple/networks/{network}/token_price/{token_address}"
        )

    async def get_onchain_pool(
        self,
        network: str,
        pool_address: str,
    ) -> Dict[str, Any]:
        """Get DEX pool data."""
        return await self._get(f"/onchain/networks/{network}/pools/{pool_address}")

    async def get_onchain_trending_pools(self) -> Dict[str, Any]:
        """Get trending pools across all networks."""
        return await self._get("/onchain/networks/trending_pools")

    async def get_onchain_new_pools(self) -> Dict[str, Any]:
        """Get newly created pools."""
        return await self._get("/onchain/networks/new_pools")

    async def get_onchain_pools_megafilter(
        self,
        sort: str = "pool_created_at_desc",
        limit: int = 20,
    ) -> Dict[str, Any]:
        """Screen pools with filters."""
        params = {"sort": sort, "limit": limit}
        return await self._get("/onchain/pools/megafilter", params)

    async def get_onchain_token_info(
        self,
        network: str,
        token_address: str,
    ) -> Dict[str, Any]:
        """Get token security info (GT Score, holders, etc.)."""
        return await self._get(
            f"/onchain/networks/{network}/tokens/{token_address}/info"
        )

    async def get_onchain_token_top_holders(
        self,
        network: str,
        token_address: str,
    ) -> Dict[str, Any]:
        """Get top holders for a token."""
        return await self._get(
            f"/onchain/networks/{network}/tokens/{token_address}/top_holders"
        )

    # ── Health ─────────────────────────────────────────────────────────

    async def ping(self) -> Dict[str, Any]:
        """Check API status."""
        return await self._get("/ping")

    # ── Cleanup ────────────────────────────────────────────────────────

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# Singleton
_cg_client: Optional[CoinGeckoClient] = None


def get_coingecko() -> CoinGeckoClient:
    global _cg_client
    if _cg_client is None:
        _cg_client = CoinGeckoClient()
    return _cg_client

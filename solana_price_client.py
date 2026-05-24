"""Multi-source Solana price client with priority fallback chain."""

import asyncio
import logging
from typing import Optional, Dict, Any
import httpx

from config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# Price source priority (fastest/most reliable first)
PRICE_SOURCES = ["birdeye", "jupiter", "dexscreener", "coingecko"]


class SolanaPriceClient:
    """Fetches Solana token prices from multiple sources with automatic fallback."""

    def __init__(self):
        self.http = httpx.AsyncClient(timeout=15.0, follow_redirects=True)
        self._price_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl = 30  # Cache prices for 30 seconds
        self._last_update: Dict[str, float] = {}

    async def close(self):
        await self.http.aclose()

    def _is_cache_valid(self, token_address: str) -> bool:
        """Check if cached price is still valid."""
        if token_address not in self._last_update:
            return False
        elapsed = asyncio.get_event_loop().time() - self._last_update[token_address]
        return elapsed < self._cache_ttl

    async def get_price(self, token_address: str, vs_token: str = "USDC") -> Optional[float]:
        """Get token price with caching and fallback chain."""
        # Check cache first
        if self._is_cache_valid(token_address):
            cached = self._price_cache[token_address].get("price")
            logger.debug(f"Price cache hit for {token_address}: {cached}")
            return cached

        # Try each price source in priority order with retries
        last_error = None
        for source in PRICE_SOURCES:
            for attempt in range(2):  # 2 attempts per source
                try:
                    price = await self._fetch_from_source(source, token_address, vs_token)
                    if price and price > 0:
                        # Cache the result
                        self._price_cache[token_address] = {
                            "price": price,
                            "source": source,
                        }
                        self._last_update[token_address] = asyncio.get_event_loop().time()
                        logger.info(f"Fetched price for {token_address} from {source}: ${price:.6f}")
                        return price
                except Exception as e:
                    last_error = e
                    logger.warning(f"Price fetch attempt {attempt + 1}/2 from {source} failed for {token_address}: {e}")
                    if attempt == 0:
                        await asyncio.sleep(1)  # Brief retry delay
                    continue

        logger.error(f"All price sources failed for {token_address}. Last error: {last_error}")
        return None

    async def _fetch_from_source(self, source: str, token_address: str, vs_token: str) -> Optional[float]:
        """Fetch price from a specific source."""
        if source == "birdeye":
            return await self._fetch_birdeye(token_address)
        elif source == "jupiter":
            return await self._fetch_jupiter(token_address, vs_token)
        elif source == "dexscreener":
            return await self._fetch_dexscreener(token_address)
        elif source == "coingecko":
            return await self._fetch_coingecko(token_address)
        return None

    async def _fetch_birdeye(self, token_address: str) -> Optional[float]:
        """Fetch price from Birdeye API."""
        if not settings.birdeye_api_key:
            return None

        url = f"https://public-api.birdeye.so/defi/price?address={token_address}"
        headers = {
            "X-API-KEY": settings.birdeye_api_key.get_secret_value(),
            "x-chain": "solana",
        }

        resp = await self.http.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        if data.get("success") and "data" in data:
            return float(data["data"].get("value", 0))
        return None

    async def _fetch_jupiter(self, token_address: str, vs_token: str) -> Optional[float]:
        """Fetch price from Jupiter Price API v3."""
        url = "https://api.jup.ag/price/v3"
        params = {
            "ids": token_address,
            "vsToken": vs_token,
        }

        resp = await self.http.get(url, params=params, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()

        if "data" in data and token_address in data["data"]:
            price_data = data["data"][token_address]
            price = price_data.get("price")
            if price is not None:
                return float(price)
        return None

    async def _fetch_dexscreener(self, token_address: str) -> Optional[float]:
        """Fetch price from DexScreener API."""
        url = f"https://api.dexscreener.com/tokens/v1/solana/{token_address}"

        resp = await self.http.get(url, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()

        if isinstance(data, list) and len(data) > 0:
            # Get the pair with highest liquidity
            best_pair = max(data, key=lambda x: float(x.get("liquidity", {}).get("usd", 0) or 0))
            price = best_pair.get("priceUsd")
            if price is not None:
                return float(price)
        return None

    async def _fetch_coingecko(self, token_address: str) -> Optional[float]:
        """Fetch price from CoinGecko API."""
        url = "https://api.coingecko.com/api/v3/simple/token_price/solana"
        params = {
            "contract_addresses": token_address,
            "vs_currencies": "usd",
        }

        resp = await self.http.get(url, params=params, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()

        if token_address.lower() in data:
            return float(data[token_address.lower()].get("usd", 0))
        return None


# Singleton instance
_price_client: Optional[SolanaPriceClient] = None


async def get_solana_price_client() -> SolanaPriceClient:
    """Get or create the Solana price client."""
    global _price_client
    if _price_client is None:
        _price_client = SolanaPriceClient()
    return _price_client

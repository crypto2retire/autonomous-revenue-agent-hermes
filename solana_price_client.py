"""Multi-source Solana price client with priority fallback chain."""

import asyncio
from typing import Optional, Dict, Any
import httpx

from config import get_settings

settings = get_settings()

# Price source priority (fastest/most reliable first)
PRICE_SOURCES = ["birdeye", "jupiter", "dexscreener", "coingecko"]

class SolanaPriceClient:
    """Fetches Solana token prices from multiple sources with automatic fallback."""
    
    def __init__(self):
        self.http = httpx.AsyncClient(timeout=10.0)
        self._price_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl = 15  # Cache prices for 15 seconds
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
            return self._price_cache[token_address].get("price")
            
        # Try each price source in priority order
        for source in PRICE_SOURCES:
            try:
                price = await self._fetch_from_source(source, token_address, vs_token)
                if price and price > 0:
                    # Cache the result
                    self._price_cache[token_address] = {
                        "price": price,
                        "source": source,
                    }
                    self._last_update[token_address] = asyncio.get_event_loop().time()
                    return price
            except Exception as e:
                # Log and try next source
                continue
                
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
        
        resp = await self.http.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        
        if "data" in data and token_address in data["data"]:
            price_data = data["data"][token_address]
            return float(price_data.get("price", 0))
        return None
        
    async def _fetch_dexscreener(self, token_address: str) -> Optional[float]:
        """Fetch price from DexScreener API."""
        url = f"https://api.dexscreener.com/tokens/v1/solana/{token_address}"
        
        resp = await self.http.get(url)
        resp.raise_for_status()
        data = resp.json()
        
        if isinstance(data, list) and len(data) > 0:
            # Get the pair with highest liquidity
            best_pair = max(data, key=lambda x: float(x.get("liquidity", {}).get("usd", 0) or 0))
            return float(best_pair.get("priceUsd", 0))
        return None
        
    async def _fetch_coingecko(self, token_address: str) -> Optional[float]:
        """Fetch price from CoinGecko API."""
        # CoinGecko uses platform-specific IDs, not mint addresses directly
        # This is a simplified fallback - may not work for all tokens
        url = f"https://api.coingecko.com/api/v3/simple/token_price/solana"
        params = {
            "contract_addresses": token_address,
            "vs_currencies": "usd",
        }
        
        resp = await self.http.get(url, params=params)
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

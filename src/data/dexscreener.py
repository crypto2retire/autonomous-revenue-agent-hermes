"""DexScreener API client for token data."""

import httpx
from decimal import Decimal
from typing import Any
from datetime import datetime

from src.utils.logger import get_logger

logger = get_logger(__name__)


class DexScreenerClient:
    """Client for DexScreener API (free, no API key needed).

    Provides: price, volume, liquidity, pair data, token profiles.
    Rate limit: 60 req/min (profiles), 300 req/min (pairs/tokens).
    """

    BASE_URL = "https://api.dexscreener.com"

    def __init__(self):
        self.client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=30.0,
        )

    async def get_token_pairs(self, chain: str, token_address: str) -> dict[str, Any]:
        """Get all liquidity pools for a token.

        Args:
            chain: Chain ID (e.g., "base", "solana", "ethereum")
            token_address: Token contract address

        Returns:
            Pair data with price, volume, liquidity, transactions.
        """
        endpoint = f"/token-pairs/v1/{chain}/{token_address}"

        try:
            response = await self.client.get(endpoint)
            response.raise_for_status()
            data = response.json()

            # Handle list response (token-pairs returns list directly)
            if isinstance(data, list):
                data = {"pairs": data}

            logger.debug(
                "dexscreener_token_pairs_fetched",
                chain=chain,
                token=token_address,
                pairs_found=len(data.get("pairs", [])),
            )

            return data

        except httpx.HTTPStatusError as e:
            logger.error(
                "dexscreener_api_error",
                endpoint=endpoint,
                status=e.response.status_code,
                response=e.response.text,
            )
            raise
        except Exception as e:
            logger.error("dexscreener_request_failed", error=str(e))
            raise

    async def get_tokens(self, chain: str, token_addresses: list[str]) -> dict[str, Any]:
        """Get data for up to 30 tokens at once.

        Args:
            chain: Chain ID
            token_addresses: List of token addresses (max 30)

        Returns:
            Token data for all requested addresses.
        """
        if len(token_addresses) > 30:
            raise ValueError("Maximum 30 token addresses allowed per request")

        addresses = ",".join(token_addresses)
        endpoint = f"/tokens/v1/{chain}/{addresses}"

        try:
            response = await self.client.get(endpoint)
            response.raise_for_status()
            data = response.json()

            logger.debug(
                "dexscreener_tokens_fetched",
                chain=chain,
                count=len(token_addresses),
            )

            return data

        except Exception as e:
            logger.error("dexscreener_tokens_failed", error=str(e))
            raise

    async def search_pairs(self, query: str) -> dict[str, Any]:
        """Search for trading pairs.

        Args:
            query: Search query (e.g., "SOL/USDC", "PEPE")

        Returns:
            Matching pairs with full data.
        """
        try:
            response = await self.client.get(
                "/latest/dex/search",
                params={"q": query},
            )
            response.raise_for_status()
            return response.json()

        except Exception as e:
            logger.error("dexscreener_search_failed", error=str(e))
            raise

    async def get_latest_profiles(self) -> list[dict[str, Any]]:
        """Get latest token profiles.

        Useful for discovering new tokens.
        """
        try:
            response = await self.client.get("/token-profiles/latest/v1")
            response.raise_for_status()
            return response.json()

        except Exception as e:
            logger.error("dexscreener_profiles_failed", error=str(e))
            raise

    async def get_boosted_tokens(self) -> list[dict[str, Any]]:
        """Get latest boosted tokens.

        Boosted tokens often have marketing/activity behind them.
        """
        try:
            response = await self.client.get("/token-boosts/latest/v1")
            response.raise_for_status()
            return response.json()

        except Exception as e:
            logger.error("dexscreener_boosts_failed", error=str(e))
            raise

    def extract_metrics(self, pair_data: dict[str, Any]) -> dict[str, Any]:
        """Extract key metrics from DexScreener pair data.

        Returns normalized metrics for opportunity analysis.
        """
        pairs = pair_data.get("pairs", [])
        if not pairs:
            return {}

        # Use the pair with highest liquidity
        primary_pair = max(pairs, key=lambda p: p.get("liquidity", {}).get("usd", 0) or 0)

        # Extract time-series data
        txns = primary_pair.get("txns", {})
        volume = primary_pair.get("volume", {})
        price_change = primary_pair.get("priceChange", {})
        liquidity = primary_pair.get("liquidity", {})

        # Calculate buy/sell ratio from h24 data
        h24_txns = txns.get("h24", {})
        buys = h24_txns.get("buys", 0)
        sells = h24_txns.get("sells", 0)
        buy_sell_ratio = buys / sells if sells > 0 else float("inf")

        return {
            "token_address": primary_pair.get("baseToken", {}).get("address"),
            "token_symbol": primary_pair.get("baseToken", {}).get("symbol"),
            "token_name": primary_pair.get("baseToken", {}).get("name"),
            "chain": primary_pair.get("chainId"),
            "dex": primary_pair.get("dexId"),
            "price_usd": Decimal(str(primary_pair.get("priceUsd", 0))),
            "price_native": primary_pair.get("priceNative"),
            "liquidity_usd": Decimal(str(liquidity.get("usd", 0))),
            "liquidity_base": Decimal(str(liquidity.get("base", 0))),
            "liquidity_quote": Decimal(str(liquidity.get("quote", 0))),
            "volume_24h": Decimal(str(volume.get("h24", 0))),
            "volume_6h": Decimal(str(volume.get("h6", 0))),
            "volume_1h": Decimal(str(volume.get("h1", 0))),
            "volume_5m": Decimal(str(volume.get("m5", 0))),
            "buys_24h": buys,
            "sells_24h": sells,
            "buy_sell_ratio": Decimal(str(buy_sell_ratio)),
            "price_change_24h": Decimal(str(price_change.get("h24", 0))),
            "price_change_6h": Decimal(str(price_change.get("h6", 0))),
            "price_change_1h": Decimal(str(price_change.get("h1", 0))),
            "price_change_5m": Decimal(str(price_change.get("m5", 0))),
            "fdv": Decimal(str(primary_pair.get("fdv", 0))),
            "market_cap": Decimal(str(primary_pair.get("marketCap", 0))),
            "pair_created_at": primary_pair.get("pairCreatedAt"),
            "pair_address": primary_pair.get("pairAddress"),
        }

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()

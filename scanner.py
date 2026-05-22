"""Token scanner — discovers coins via DexScreener, CoinGecko, and analyzes with Venice AI."""

import asyncio
import json
from datetime import datetime
from typing import List, Dict, Any, Optional

import httpx

from config import get_settings
from database import DB
from coingecko_client import get_coingecko

settings = get_settings()

DEXSCREENER_BASE = "https://api.dexscreener.com"
VENICE_BASE = "https://api.venice.ai/api/v1"


class Scanner:
    """Scans for crypto opportunities and persists everything to the watchlist."""

    def __init__(self):
        self.http = httpx.AsyncClient(timeout=30.0)
        self.running = False
        self.cg = get_coingecko()

    async def close(self):
        await self.http.aclose()
        await self.cg.close()

    # ── DexScreener API ──────────────────────────────────────────────

    async def get_trending(self, chain: str = "base") -> List[Dict[str, Any]]:
        """Get trending token profiles on a chain."""
        url = f"{DEXSCREENER_BASE}/token-profiles/latest/v1"
        try:
            resp = await self.http.get(url)
            resp.raise_for_status()
            data = resp.json()
            # Filter by chain
            tokens = [
                t for t in data if t.get("chainId", "").lower() == chain.lower()
            ]
            return tokens[:50]
        except Exception as e:
            await DB.log_event("error", "dexscreener_trending_failed", str(e))
            return []

    async def get_token_pairs(self, token_address: str, chain: str = "base") -> List[Dict[str, Any]]:
        """Get pair data for a specific token — includes symbol, name, price, volume."""
        url = f"{DEXSCREENER_BASE}/token-pairs/v1/{chain}/{token_address}"
        try:
            resp = await self.http.get(url)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            await DB.log_event("error", "dexscreener_pairs_failed", str(e), {"token_address": token_address})
            return []

    # ── CoinGecko API ────────────────────────────────────────────────

    async def get_coingecko_trending(self) -> List[Dict[str, Any]]:
        """Get trending coins from CoinGecko."""
        try:
            data = await self.cg.get_trending()
            coins = []
            for item in data.get("coins", []):
                coin = item.get("item", {})
                coins.append({
                    "tokenAddress": coin.get("contract_address", ""),
                    "symbol": coin.get("symbol", "UNKNOWN"),
                    "name": coin.get("name", "Unknown"),
                    "priceUsd": coin.get("data", {}).get("price", 0),
                    "volume": {"h24": coin.get("data", {}).get("total_volume", 0)},
                    "liquidity": {"usd": coin.get("data", {}).get("market_cap", 0)},
                    "marketCap": coin.get("data", {}).get("market_cap", 0),
                    "priceChange": {"h24": coin.get("data", {}).get("price_change_percentage_24h", {}).get("usd", 0)},
                    "source": "coingecko_trending",
                })
            return coins
        except Exception as e:
            await DB.log_event("error", "coingecko_trending_failed", str(e))
            return []

    async def get_coingecko_gainers(self) -> List[Dict[str, Any]]:
        """Get top gainers from CoinGecko."""
        try:
            data = await self.cg.get_top_gainers_losers()
            coins = []
            for item in data.get("top_gainers", [])[:20]:
                coins.append({
                    "tokenAddress": item.get("contract_address", ""),
                    "symbol": item.get("symbol", "UNKNOWN"),
                    "name": item.get("name", "Unknown"),
                    "priceUsd": item.get("current_price", 0),
                    "volume": {"h24": item.get("total_volume", 0)},
                    "liquidity": {"usd": item.get("market_cap", 0)},
                    "marketCap": item.get("market_cap", 0),
                    "priceChange": {"h24": item.get("price_change_percentage_24h", 0)},
                    "source": "coingecko_gainers",
                })
            return coins
        except Exception as e:
            await DB.log_event("error", "coingecko_gainers_failed", str(e))
            return []

    async def get_coingecko_new_coins(self) -> List[Dict[str, Any]]:
        """Get newly listed coins from CoinGecko."""
        try:
            data = await self.cg.get_new_coins()
            coins = []
            for item in data[:20]:
                coins.append({
                    "tokenAddress": item.get("contract_address", ""),
                    "symbol": item.get("symbol", "UNKNOWN"),
                    "name": item.get("name", "Unknown"),
                    "priceUsd": 0,
                    "volume": {"h24": 0},
                    "liquidity": {"usd": 0},
                    "marketCap": 0,
                    "priceChange": {"h24": 0},
                    "source": "coingecko_new",
                })
            return coins
        except Exception as e:
            await DB.log_event("error", "coingecko_new_failed", str(e))
            return []

    async def get_coingecko_token_price(self, token_address: str, network: str = "base") -> Optional[float]:
        """Get token price by contract address from CoinGecko."""
        try:
            data = await self.cg.get_onchain_token_price(network, token_address)
            prices = data.get("data", {})
            if prices:
                # Return the first price found
                for addr, info in prices.items():
                    return float(info.get("usd", 0))
        except Exception as e:
            await DB.log_event("error", "coingecko_price_failed", str(e), {"token_address": token_address})
        return None

    async def get_coingecko_market_data(self, coin_id: str) -> Dict[str, Any]:
        """Get detailed market data for a coin by CoinGecko ID."""
        try:
            return await self.cg.get_coin(coin_id)
        except Exception as e:
            await DB.log_event("error", "coingecko_market_failed", str(e), {"coin_id": coin_id})
            return {}

    # ── Venice AI Analysis ───────────────────────────────────────────

    async def analyze_opportunity(self, token: Dict[str, Any]) -> Dict[str, Any]:
        """Use Venice AI to analyze a token."""
        symbol = token.get("symbol", "UNKNOWN")
        name = token.get("name", "Unknown")
        price = token.get("priceUsd", 0)
        volume = token.get("volume", {}).get("h24", 0)
        liquidity = token.get("liquidity", {}).get("usd", 0)
        market_cap = token.get("marketCap", 0)
        price_change = token.get("priceChange", {}).get("h24", 0)

        prompt = f"""Analyze this cryptocurrency token for short-term trading potential:

Token: {name} (${symbol})
Price: ${price}
24h Volume: ${volume}
Liquidity: ${liquidity}
Market Cap: ${market_cap}
24h Price Change: {price_change}%

Provide a JSON response with exactly these fields:
- signal: one of [buy, sell, hold, avoid]
- confidence: 0.0 to 1.0
- reasoning: brief explanation
- risk_level: low, medium, or high
- tags: comma-separated keywords like trending,gainer,new,momentum

Respond ONLY with valid JSON."""

        try:
            resp = await self.http.post(
                f"{VENICE_BASE}/chat/completions",
                headers={"Authorization": f"Bearer {settings.venice_api_key.get_secret_value()}"},
                json={
                    "model": settings.venice_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                    "max_tokens": 800,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]

            # Extract JSON from markdown if needed
            content = content.strip()
            if "```" in content:
                # Extract content between code fences
                parts = content.split("```")
                for part in parts:
                    part = part.strip()
                    if part.startswith("json"):
                        part = part[4:].strip()
                    if part and part.startswith("{"):
                        content = part
                        break

            # Try to find JSON object in the content
            try:
                analysis = json.loads(content.strip())
            except json.JSONDecodeError:
                # Try to extract JSON using regex
                import re
                json_match = re.search(r'\{[\s\S]*\}', content)
                if json_match:
                    analysis = json.loads(json_match.group())
                else:
                    raise

            return {
                "signal": analysis.get("signal", "avoid").lower(),
                "confidence": float(analysis.get("confidence", 0)),
                "reasoning": analysis.get("reasoning", ""),
                "risk_level": analysis.get("risk_level", "high"),
                "tags": analysis.get("tags", ""),
            }
        except Exception as e:
            await DB.log_event(
                "error", "ai_analysis_failed", str(e),
                {"token_address": token.get("tokenAddress", ""), "symbol": symbol},
            )
            return {
                "signal": "avoid",
                "confidence": 0,
                "reasoning": f"Analysis failed: {e}",
                "risk_level": "high",
                "tags": "",
            }

    # ── Main Scan Loop ───────────────────────────────────────────────

    async def scan_once(self, chain: str = "base"):
        """Run one scan cycle: discover → analyze → persist."""
        await DB.log_event("info", "scan_started", f"Scanning {chain} chain")

        all_tokens: List[Dict[str, Any]] = []

        # Source 1: DexScreener trending
        dex_tokens = await self.get_trending(chain)
        for t in dex_tokens:
            t["source"] = "dexscreener"
        all_tokens.extend(dex_tokens)

        # Source 2: CoinGecko trending
        cg_trending = await self.get_coingecko_trending()
        all_tokens.extend(cg_trending)

        # Source 3: CoinGecko gainers
        cg_gainers = await self.get_coingecko_gainers()
        all_tokens.extend(cg_gainers)

        # Source 4: CoinGecko new coins
        cg_new = await self.get_coingecko_new_coins()
        all_tokens.extend(cg_new)

        # Deduplicate by token address
        seen = set()
        unique_tokens = []
        for t in all_tokens:
            addr = t.get("tokenAddress", "")
            if addr and addr not in seen:
                seen.add(addr)
                unique_tokens.append(t)

        await DB.log_event("info", "tokens_discovered", f"Found {len(unique_tokens)} unique tokens", {"count": len(unique_tokens)})

        for token in unique_tokens:
            address = token.get("tokenAddress", "")
            if not address:
                continue

            # Try to get price from CoinGecko if missing
            if not token.get("priceUsd"):
                cg_price = await self.get_coingecko_token_price(address, chain)
                if cg_price:
                    token["priceUsd"] = cg_price

            # For DexScreener tokens, get detailed pair data
            if token.get("source") == "dexscreener":
                pairs = await self.get_token_pairs(address, chain)
                if pairs:
                    best_pair = max(pairs, key=lambda p: float(p.get("liquidity", {}).get("usd", 0) or 0))
                    base_token = best_pair.get("baseToken", {})
                    token["symbol"] = base_token.get("symbol", token.get("symbol", "UNKNOWN"))
                    token["name"] = base_token.get("name", token.get("name", "Unknown"))
                    token["priceUsd"] = float(best_pair.get("priceUsd", 0) or 0)
                    token["volume"] = {"h24": float(best_pair.get("volume", {}).get("h24", 0) or 0)}
                    token["liquidity"] = {"usd": float(best_pair.get("liquidity", {}).get("usd", 0) or 0)}
                    token["marketCap"] = float(best_pair.get("marketCap", 0) or 0)
                    token["priceChange"] = {"h24": float(best_pair.get("priceChange", {}).get("h24", 0) or 0)}

            # AI analysis
            analysis = await self.analyze_opportunity(token)

            # Persist to watchlist
            existing = await DB.get_coin(address)
            if existing:
                await DB.update_coin_signal(address, analysis["signal"], analysis["confidence"])
            else:
                await DB.add_coin(
                    token_address=address,
                    symbol=token.get("symbol", "UNKNOWN"),
                    name=token.get("name", "Unknown"),
                    price_at_discovery=token.get("priceUsd", 0),
                    ai_score=analysis["confidence"],
                    signal=analysis["signal"],
                    metadata={
                        "reasoning": analysis["reasoning"],
                        "risk_level": analysis["risk_level"],
                        "tags": analysis["tags"],
                        "source": token.get("source", "unknown"),
                    },
                )

            # Log significant signals
            if analysis["signal"] == "buy" and analysis["confidence"] > 0.7:
                await DB.log_event(
                    "info", "strong_buy_signal",
                    f"{token.get('symbol', 'UNKNOWN')}: {analysis['reasoning']}",
                    {"token_address": address, "symbol": token.get("symbol", ""), "confidence": analysis["confidence"], "price": token.get("priceUsd", 0)},
                )

            await asyncio.sleep(1)  # Rate limit between tokens

        await DB.log_event("info", "scan_completed", f"Scanned {len(unique_tokens)} tokens")

    async def run(self):
        """Continuous scan loop."""
        self.running = True
        while self.running:
            try:
                await self.scan_once()
            except Exception as e:
                await DB.log_event("error", "scan_cycle_failed", str(e))
            await asyncio.sleep(settings.scan_interval_seconds)

    def stop(self):
        self.running = False

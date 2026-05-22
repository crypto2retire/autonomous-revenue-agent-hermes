"""Token scanner — discovers coins via DexScreener, CoinGecko, and analyzes with Venice AI."""

import asyncio
import json
from datetime import datetime
from typing import List, Dict, Any, Optional

import httpx

from config import get_settings
from database import DB
from coingecko_client import get_coingecko
from dune_client import get_dune
from basescan_client import get_basescan

settings = get_settings()

DEXSCREENER_BASE = "https://api.dexscreener.com"
VENICE_BASE = "https://api.venice.ai/api/v1"


class Scanner:
    """Scans for crypto opportunities and persists everything to the watchlist."""

    def __init__(self):
        self.http = httpx.AsyncClient(timeout=30.0)
        self.running = False
        self.cg = get_coingecko()
        self.dune = get_dune()
        self.basescan = get_basescan()

    async def close(self):
        await self.http.aclose()
        await self.cg.close()
        await self.dune.close()
        await self.basescan.close()

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
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                await DB.log_event("warning", "coingecko_gainers_skipped", "Gainers endpoint requires paid plan")
            else:
                await DB.log_event("error", "coingecko_gainers_failed", str(e))
            return []
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
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                await DB.log_event("warning", "coingecko_new_skipped", "New coins endpoint requires paid plan")
            else:
                await DB.log_event("error", "coingecko_new_failed", str(e))
            return []
        except Exception as e:
            await DB.log_event("error", "coingecko_new_failed", str(e))
            return []

    async def get_coingecko_token_price(self, token_address: str, network: str = "base") -> Optional[float]:
        """Get token price by contract address from CoinGecko."""
        try:
            data = await self.cg.get_onchain_token_price(network, token_address)
            # Response format: {"data": {"0x...": {"usd": 123.45}}}
            price_data = data.get("data", {})
            if isinstance(price_data, dict):
                for addr, info in price_data.items():
                    if isinstance(info, dict):
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

    # ── Dune Analytics ───────────────────────────────────────────────

    async def get_dune_trending_tokens(self) -> List[Dict[str, Any]]:
        """Get trending tokens from Dune Analytics queries."""
        try:
            # Query: Trending tokens on Base by volume (example query ID)
            # You can replace this with your own Dune query IDs
            result = await self.dune.execute_and_wait(
                query_id=12345,  # Replace with actual query ID for trending tokens
            )
            tokens = []
            for row in result.get("result", {}).get("rows", []):
                tokens.append({
                    "tokenAddress": row.get("token_address", ""),
                    "symbol": row.get("symbol", "UNKNOWN"),
                    "name": row.get("name", "Unknown"),
                    "priceUsd": row.get("price", 0),
                    "volume": {"h24": row.get("volume_24h", 0)},
                    "liquidity": {"usd": row.get("liquidity", 0)},
                    "marketCap": row.get("market_cap", 0),
                    "priceChange": {"h24": row.get("price_change_24h", 0)},
                    "source": "dune",
                })
            return tokens
        except Exception as e:
            await DB.log_event("error", "dune_trending_failed", str(e))
            return []

    async def get_dune_wallet_stats(self, wallet_address: str) -> Dict[str, Any]:
        """Get on-chain stats for a wallet address from Dune."""
        try:
            result = await self.dune.execute_and_wait(
                query_id=12346,  # Replace with actual query ID for wallet stats
                parameters=[{"key": "wallet_address", "value": wallet_address}],
            )
            rows = result.get("result", {}).get("rows", [])
            return rows[0] if rows else {}
        except Exception as e:
            await DB.log_event("error", "dune_wallet_failed", str(e), {"wallet": wallet_address})
            return {}

    # ── BaseScan ──────────────────────────────────────────────────────

    async def get_basescan_token_info(self, token_address: str) -> Dict[str, Any]:
        """Get token info from BaseScan for a contract address."""
        try:
            info = await self.basescan.get_token_info(token_address)
            if info:
                return {
                    "name": info.get("tokenName", ""),
                    "symbol": info.get("tokenSymbol", ""),
                    "decimals": int(info.get("tokenDecimal", 18)),
                    "total_supply": info.get("totalSupply", "0"),
                    "contract": token_address,
                }
        except Exception as e:
            await DB.log_event("error", "basescan_token_info_failed", str(e), {"token_address": token_address})
        return {}

    async def get_basescan_contract_creation(self, token_address: str) -> Dict[str, Any]:
        """Get contract creation details from BaseScan."""
        try:
            result = await self.basescan.get_contract_creation([token_address])
            if result:
                return result[0]
        except Exception as e:
            await DB.log_event("error", "basescan_contract_failed", str(e), {"token_address": token_address})
        return {}

    async def get_basescan_token_holders(self, token_address: str, top_n: int = 10) -> List[Dict[str, Any]]:
        """Get top token holders from BaseScan."""
        try:
            holders = await self.basescan.get_token_holder_list(token_address, offset=top_n)
            return holders
        except Exception as e:
            await DB.log_event("error", "basescan_holders_failed", str(e), {"token_address": token_address})
            return []

    async def get_basescan_gas(self) -> Dict[str, Any]:
        """Get current gas prices from BaseScan."""
        try:
            return await self.basescan.get_gas_oracle()
        except Exception as e:
            await DB.log_event("error", "basescan_gas_failed", str(e))
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

        # Source 5: Dune Analytics trending
        dune_tokens = await self.get_dune_trending_tokens()
        all_tokens.extend(dune_tokens)

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

            # Enrich with BaseScan data
            basescan_info = await self.get_basescan_token_info(address)
            if basescan_info:
                token["name"] = basescan_info.get("name") or token.get("name", "Unknown")
                token["symbol"] = basescan_info.get("symbol") or token.get("symbol", "UNKNOWN")
                token["basescan"] = basescan_info

            # Get contract creation date
            contract_info = await self.get_basescan_contract_creation(address)
            if contract_info:
                token["contract_creation"] = contract_info

            # Get top holders
            holders = await self.get_basescan_token_holders(address, top_n=5)
            if holders:
                token["top_holders"] = holders

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

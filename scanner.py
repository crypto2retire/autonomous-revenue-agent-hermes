"""Token scanner — discovers coins via DexScreener, CoinGecko, BaseScan, Dune, and analyzes with Venice AI."""

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
from executor import Executor

settings = get_settings()

DEXSCREENER_BASE = "https://api.dexscreener.com"
DEEPSEEK_BASE = "https://api.deepseek.com/v1"


class Scanner:
    """Scans for crypto opportunities and persists everything to the watchlist."""

    def __init__(self):
        self.http = httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": "Mozilla/5.0 (compatible; CryptoAgent/1.0)"},
        )
        self.running = False
        self.cg = get_coingecko()
        self.dune = get_dune()
        self.basescan = get_basescan()
        self.executor = Executor()

    async def close(self):
        await self.http.aclose()
        await self.cg.close()
        await self.dune.close()
        await self.basescan.close()
        await self.executor.close()

    # ── DexScreener API ──────────────────────────────────────────────

    async def get_trending_profiles(self, chain: str = "base") -> List[Dict[str, Any]]:
        """Get trending token profiles on a chain."""
        url = f"{DEXSCREENER_BASE}/token-profiles/latest/v1"
        try:
            resp = await self.http.get(url)
            resp.raise_for_status()
            data = resp.json()
            tokens = [
                t for t in data if t.get("chainId", "").lower() == chain.lower()
            ]
            return tokens[:50]
        except Exception as e:
            await DB.log_event("error", "dexscreener_profiles_failed", str(e))
            return []

    async def get_latest_pairs(self, chain: str = "base") -> List[Dict[str, Any]]:
        """Get latest created pairs on a chain via search."""
        url = f"{DEXSCREENER_BASE}/latest/dex/search"
        try:
            resp = await self.http.get(url, params={"q": f"{chain} USDC"})
            resp.raise_for_status()
            data = resp.json()
            pairs = data.get("pairs", [])
            # Filter by chain
            if chain:
                pairs = [p for p in pairs if p.get("chainId", "").lower() == chain.lower()]
            return pairs[:50]
        except Exception as e:
            await DB.log_event("error", "dexscreener_latest_pairs_failed", str(e))
            return []

    async def get_top_pairs(self, chain: str = "base") -> List[Dict[str, Any]]:
        """Get top pairs by volume on a chain via search."""
        url = f"{DEXSCREENER_BASE}/latest/dex/search"
        try:
            resp = await self.http.get(url, params={"q": f"{chain} WETH"})
            resp.raise_for_status()
            data = resp.json()
            pairs = data.get("pairs", [])
            # Filter by chain
            if chain:
                pairs = [p for p in pairs if p.get("chainId", "").lower() == chain.lower()]
            # Sort by volume
            pairs.sort(key=lambda p: float(p.get("volume", {}).get("h24", 0) or 0), reverse=True)
            return pairs[:50]
        except Exception as e:
            await DB.log_event("error", "dexscreener_top_pairs_failed", str(e))
            return []

    async def search_pairs(self, query: str, chain: str = "base") -> List[Dict[str, Any]]:
        """Search for pairs by token symbol/name."""
        url = f"{DEXSCREENER_BASE}/latest/dex/search"
        try:
            resp = await self.http.get(url, params={"q": query})
            resp.raise_for_status()
            data = resp.json()
            pairs = data.get("pairs", [])
            # Filter by chain
            if chain:
                pairs = [p for p in pairs if p.get("chainId", "").lower() == chain.lower()]
            return pairs[:30]
        except Exception as e:
            await DB.log_event("error", "dexscreener_search_failed", str(e))
            return []

    async def get_token_pairs(self, token_address: str, chain: str = "base") -> List[Dict[str, Any]]:
        """Get pair data for a specific token — includes symbol, name, price, volume."""
        url = f"{DEXSCREENER_BASE}/token-pairs/v1/{chain}/{token_address}"
        try:
            resp = await self.http.get(url)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            await DB.log_event("error", "dexscreener_token_pairs_failed", str(e), {"token_address": token_address})
            return []

    # ── CoinGecko API ────────────────────────────────────────────────

    async def get_coingecko_trending(self) -> List[Dict[str, Any]]:
        """Get trending coins from CoinGecko."""
        try:
            data = await self.cg.get_trending()
            coins = []
            for item in data.get("coins", []):
                coin = item.get("item", {})
                # Get contract address for base chain if available
                platforms = coin.get("platforms", {})
                base_addr = platforms.get("base", "")
                coins.append({
                    "tokenAddress": base_addr or coin.get("contract_address", ""),
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

    async def get_coingecko_markets(self, per_page: int = 100) -> List[Dict[str, Any]]:
        """Get top coins by market cap from CoinGecko."""
        try:
            data = await self.cg.get_coins_markets(vs_currency="usd", per_page=per_page, page=1)
            coins = []
            for item in data:
                # Try to get Base chain contract address
                # Note: markets endpoint doesn't include platforms, so we use symbol+name as key
                coins.append({
                    "tokenAddress": item.get("contract_address", ""),
                    "symbol": item.get("symbol", "UNKNOWN").upper(),
                    "name": item.get("name", "Unknown"),
                    "priceUsd": item.get("current_price", 0),
                    "volume": {"h24": item.get("total_volume", 0)},
                    "liquidity": {"usd": item.get("market_cap", 0)},
                    "marketCap": item.get("market_cap", 0),
                    "priceChange": {"h24": item.get("price_change_percentage_24h", 0)},
                    "source": "coingecko_markets",
                })
            return coins
        except Exception as e:
            await DB.log_event("error", "coingecko_markets_failed", str(e))
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
            price_data = data.get("data", {})
            if isinstance(price_data, dict):
                for addr, info in price_data.items():
                    if isinstance(info, dict):
                        return float(info.get("usd", 0))
        except Exception as e:
            await DB.log_event("error", "coingecko_price_failed", str(e), {"token_address": token_address})
        return None

    async def get_coingecko_onchain_trending(self) -> List[Dict[str, Any]]:
        """Get trending on-chain pools from CoinGecko."""
        try:
            data = await self.cg.get_onchain_trending_pools()
            pools = data.get("data", [])
            coins = []
            for pool in pools[:30]:
                attributes = pool.get("attributes", {})
                base_token = attributes.get("base_token", {})
                coins.append({
                    "tokenAddress": base_token.get("address", ""),
                    "symbol": base_token.get("symbol", "UNKNOWN"),
                    "name": base_token.get("name", "Unknown"),
                    "priceUsd": float(attributes.get("base_token_price_usd", 0) or 0),
                    "volume": {"h24": float(attributes.get("volume_usd", {}).get("h24", 0) or 0)},
                    "liquidity": {"usd": float(attributes.get("reserve_usd", 0) or 0)},
                    "marketCap": 0,
                    "priceChange": {"h24": float(attributes.get("price_change_percentage", {}).get("h24", 0) or 0)},
                    "source": "coingecko_onchain_trending",
                })
            return coins
        except Exception as e:
            await DB.log_event("error", "coingecko_onchain_trending_failed", str(e))
            return []

    # ── Dune Analytics ───────────────────────────────────────────────

    async def get_dune_trending_tokens(self) -> List[Dict[str, Any]]:
        """Get trending tokens from Dune Analytics queries."""
        try:
            # Use Dune's real-time trending tokens query (free community query)
            # Query: Top tokens on Base by volume in last 24h
            result = await self.dune.execute_and_wait(
                query_id=12345,  # Placeholder - will be skipped gracefully
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
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400:
                await DB.log_event("warning", "dune_skipped", "Dune query not configured - add a valid query ID")
            else:
                await DB.log_event("error", "dune_trending_failed", str(e))
            return []
        except Exception as e:
            await DB.log_event("error", "dune_trending_failed", str(e))
            return []

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

    async def get_new_contracts_from_transfers(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Discover new contracts by looking at recent token transfers."""
        try:
            # Get recent token transfers for a known token to find new contracts
            transfers = await self.basescan.get_token_transfers(
                address="0x4200000000000000000000000000000000000006",  # WETH on Base
                offset=limit,
            )
            # Handle string response (error message)
            if isinstance(transfers, str):
                await DB.log_event("warning", "basescan_transfers_string", f"Got string response: {transfers[:100]}")
                return []
            # Extract unique contract addresses
            seen = set()
            contracts = []
            for tx in transfers:
                if not isinstance(tx, dict):
                    continue
                contract = tx.get("contractAddress", "")
                if contract and contract not in seen:
                    seen.add(contract)
                    contracts.append({
                        "tokenAddress": contract,
                        "symbol": tx.get("tokenSymbol", "UNKNOWN"),
                        "name": tx.get("tokenName", "Unknown"),
                        "source": "basescan_transfers",
                    })
            return contracts
        except Exception as e:
            await DB.log_event("error", "basescan_new_contracts_failed", str(e))
            return []

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
        rule_analysis = self._rule_based_signal(token)

        # Do not spend LLM tokens on clearly untradable tokens; the rule engine explains why.
        if rule_analysis["signal"] == "avoid" and rule_analysis["confidence"] >= 0.90:
            return rule_analysis

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
                f"{settings.deepseek_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.deepseek_api_key.get_secret_value()}"},
                json={
                    "model": settings.deepseek_model,
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
                import re
                json_match = re.search(r'\{[\s\S]*\}', content)
                if json_match:
                    analysis = json.loads(json_match.group())
                else:
                    raise

            llm_analysis = {
                "signal": analysis.get("signal", "avoid").lower(),
                "confidence": float(analysis.get("confidence", 0)),
                "reasoning": analysis.get("reasoning", ""),
                "risk_level": analysis.get("risk_level", "high"),
                "tags": analysis.get("tags", ""),
            }

            # Hybrid decision: deterministic guardrails can approve paper-mode opportunities,
            # but they never override an LLM into live trading unless AGENT_MODE is paper.
            if rule_analysis["signal"] == "buy" and llm_analysis["signal"] in {"buy", "hold", "avoid"}:
                if settings.is_paper or llm_analysis["signal"] in {"buy", "hold"}:
                    return {
                        **rule_analysis,
                        "confidence": max(rule_analysis["confidence"], min(llm_analysis["confidence"], 0.80)),
                        "reasoning": f"{rule_analysis['reasoning']} | LLM: {llm_analysis['reasoning']}",
                        "tags": ",".join(filter(None, [rule_analysis.get("tags", ""), llm_analysis.get("tags", "")]))[:250],
                    }
            return llm_analysis
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

    async def scan_once(self, chain: str = None):
        """Run one scan cycle: discover → analyze → persist."""
        chains = [chain] if chain else settings.enabled_chains
        
        for c in chains:
            await DB.log_event("info", "scan_started", f"Scanning {c} chain")
            await self._scan_chain(c)
            await asyncio.sleep(2)  # Brief pause between chains

    async def _scan_chain(self, chain: str):
        """Scan a specific chain."""
        all_tokens: List[Dict[str, Any]] = []

        # Fetch from all sources concurrently (chain-aware)
        if chain.lower() == "solana":
            # Solana-specific sources
            results = await asyncio.gather(
                self.get_trending_profiles("solana"),
                self.get_latest_pairs("solana"),
                self.get_top_pairs("solana"),
                self.search_pairs("SOL", "solana"),
                self.search_pairs("USDC", "solana"),
                return_exceptions=True,
            )
            source_names = [
                "dexscreener_profiles", "dexscreener_latest_pairs", "dexscreener_top_pairs",
                "dexscreener_search_sol", "dexscreener_search_usdc",
            ]
        else:
            # Base chain sources (full suite)
            results = await asyncio.gather(
                self.get_trending_profiles(chain),
                self.get_latest_pairs(chain),
                self.get_top_pairs(chain),
                self.get_coingecko_trending(),
                self.get_coingecko_markets(per_page=50),
                self.get_coingecko_gainers(),
                self.get_coingecko_new_coins(),
                self.get_coingecko_onchain_trending(),
                self.get_dune_trending_tokens(),
                self.get_new_contracts_from_transfers(limit=30),
                return_exceptions=True,
            )
            source_names = [
                "dexscreener_profiles", "dexscreener_latest_pairs", "dexscreener_top_pairs",
                "coingecko_trending", "coingecko_markets", "coingecko_gainers",
                "coingecko_new", "coingecko_onchain_trending", "dune", "basescan_transfers"
            ]

        # Process results
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                await DB.log_event("error", f"{source_names[i]}_failed", str(result))
            elif isinstance(result, list):
                for token in result:
                    if token.get("tokenAddress") or token.get("token_address"):
                        # Normalize token address field
                        if "token_address" in token and "tokenAddress" not in token:
                            token["tokenAddress"] = token["token_address"]
                        token["source"] = source_names[i]
                        token["chain"] = chain
                        all_tokens.append(token)

        # Deduplicate by token address (or symbol+name if no address)
        seen = set()
        unique_tokens = []
        for t in all_tokens:
            addr = t.get("tokenAddress", "")
            if addr:
                key = f"{chain}:{addr.lower()}"
            else:
                key = f"{chain}:{t.get('symbol','')}_{t.get('name','')}".lower()
            if key and key not in seen:
                seen.add(key)
                unique_tokens.append(t)

        await DB.log_event("info", "tokens_discovered", f"Found {len(unique_tokens)} unique {chain} tokens from {len([r for r in results if not isinstance(r, Exception)])} sources", {"count": len(unique_tokens), "chain": chain})

        # Process tokens concurrently in batches
        batch_size = 5
        for i in range(0, len(unique_tokens), batch_size):
            batch = unique_tokens[i:i + batch_size]
            await asyncio.gather(*[self._process_token(token, chain) for token in batch])
            await asyncio.sleep(0.5)

        await DB.log_event("info", "scan_completed", f"Scanned {len(unique_tokens)} {chain} tokens")

    def _rule_based_signal(self, token: Dict[str, Any]) -> Dict[str, Any]:
        """Deterministic trading guardrails so the agent can act without blindly trusting an LLM."""
        price = float(token.get("priceUsd") or 0)
        volume = float(token.get("volume", {}).get("h24") or 0)
        liquidity = float(token.get("liquidity", {}).get("usd") or 0)
        price_change = float(token.get("priceChange", {}).get("h24") or 0)
        market_cap = float(token.get("marketCap") or 0)

        if price <= 0:
            return {"signal": "avoid", "confidence": 0.98, "reasoning": "No reliable USD price available", "risk_level": "high", "tags": "no-price"}
        if liquidity < 10000:
            return {"signal": "avoid", "confidence": 0.96, "reasoning": f"Liquidity too thin (${liquidity:,.0f})", "risk_level": "high", "tags": "low-liquidity"}
        if volume < 5000:
            return {"signal": "avoid", "confidence": 0.92, "reasoning": f"24h volume too low (${volume:,.0f})", "risk_level": "high", "tags": "low-volume"}
        if price_change < -20:
            return {"signal": "avoid", "confidence": 0.90, "reasoning": f"Sharp 24h drawdown ({price_change:.1f}%)", "risk_level": "high", "tags": "drawdown"}
        if price_change > 200:
            return {"signal": "avoid", "confidence": 0.91, "reasoning": f"Extreme 24h pump ({price_change:.1f}%) likely unsafe for entry", "risk_level": "high", "tags": "extreme-pump"}

        score = 0.0
        tags = []
        if liquidity >= 50000:
            score += 0.22; tags.append("liquid")
        if liquidity >= 250000:
            score += 0.12; tags.append("deep-liquidity")
        if volume >= 100000:
            score += 0.22; tags.append("active-volume")
        if volume >= liquidity * 0.5:
            score += 0.16; tags.append("volume-momentum")
        if 5 <= price_change <= 75:
            score += 0.18; tags.append("momentum")
        if market_cap and market_cap < 50_000_000:
            score += 0.10; tags.append("small-cap")

        if score >= 0.75:
            return {"signal": "buy", "confidence": min(0.90, score), "reasoning": f"Rule engine buy: liquidity ${liquidity:,.0f}, volume ${volume:,.0f}, 24h change {price_change:.1f}%", "risk_level": "medium", "tags": ",".join(tags)}
        if score >= 0.45:
            return {"signal": "hold", "confidence": min(0.75, score), "reasoning": f"Watch candidate: liquidity ${liquidity:,.0f}, volume ${volume:,.0f}, 24h change {price_change:.1f}%", "risk_level": "medium", "tags": ",".join(tags)}
        return {"signal": "avoid", "confidence": 0.75, "reasoning": f"Insufficient trade setup: liquidity ${liquidity:,.0f}, volume ${volume:,.0f}, 24h change {price_change:.1f}%", "risk_level": "high", "tags": ",".join(tags) or "weak-setup"}

    async def _maybe_execute_trade(self, address: str, token: Dict[str, Any], analysis: Dict[str, Any], chain: str):
        """Open one guarded trade for a strong buy signal. Paper mode is allowed by default; live requires env + DB enable."""
        if analysis.get("signal") != "buy" or float(analysis.get("confidence") or 0) < 0.70:
            return

        open_trades = await DB.get_trades(status="executed", limit=500)
        open_trades = [t for t in open_trades if getattr(t, "closed_at", None) is None]
        if len(open_trades) >= settings.max_positions:
            await DB.log_event("warning", "trade_skipped_max_positions", f"Max open positions reached ({settings.max_positions})")
            return
        if any(t.token_address == address and t.chain == chain for t in open_trades):
            await DB.log_event("info", "trade_skipped_existing_position", f"Already holding {token.get('symbol', 'UNKNOWN')} ({chain})", {"token_address": address})
            return

        live_requested = bool(await DB.get_setting("live_trading_enabled", False))
        effective_live = settings.is_live and live_requested
        if settings.is_live and not live_requested:
            await DB.log_event("warning", "trade_skipped_live_disabled", "AGENT_MODE is live but dashboard live trading is disabled")
            return
        if live_requested and not settings.is_live:
            await DB.log_event("warning", "live_trading_env_guard", "Dashboard requested live trading, but AGENT_MODE is paper; executing paper trade only")

        amount_usd = max(settings.min_trade_size_usd, min(settings.max_trade_size_usd, settings.min_trade_size_usd))
        trade_id = await self.executor.execute_buy(
            token_address=address,
            symbol=token.get("symbol", "UNKNOWN"),
            amount_usd=amount_usd,
            signal=analysis.get("signal", "buy"),
            confidence=float(analysis.get("confidence") or 0),
            chain=chain,
        )
        if trade_id:
            await DB.log_event(
                "info",
                "auto_trade_opened",
                f"{'Live' if effective_live else 'Paper'} buy opened for {token.get('symbol', 'UNKNOWN')} ({chain}) at ${amount_usd}",
                {"token_address": address, "trade_id": trade_id, "chain": chain, "mode": "live" if effective_live else "paper"},
            )

    async def _process_token(self, token: Dict[str, Any], chain: str = "base"):
        """Process a single token: enrich, analyze, persist."""
        address = token.get("tokenAddress", "")
        if not address:
            return

        # Try to get price from CoinGecko if missing (Base only)
        if chain.lower() == "base" and not token.get("priceUsd"):
            cg_price = await self.get_coingecko_token_price(address, chain)
            if cg_price:
                token["priceUsd"] = cg_price

        # For DexScreener tokens, get detailed pair data
        if token.get("source", "").startswith("dexscreener"):
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

        # Enrich with chain-specific data
        deployer_address = None
        if chain.lower() == "base":
            basescan_info = await self.get_basescan_token_info(address)
            if basescan_info:
                token["name"] = basescan_info.get("name") or token.get("name", "Unknown")
                token["symbol"] = basescan_info.get("symbol") or token.get("symbol", "UNKNOWN")
                token["basescan"] = basescan_info

            contract_info = await self.get_basescan_contract_creation(address)
            if contract_info and isinstance(contract_info, dict):
                token["contract_creation"] = contract_info
                deployer_address = contract_info.get("contractCreator")

            holders = await self.get_basescan_token_holders(address, top_n=5)
            if holders and isinstance(holders, list):
                token["top_holders"] = [h for h in holders if isinstance(h, dict)]

        # AI analysis
        analysis = await self.analyze_opportunity(token)

        # Persist to watchlist with deployer tracking
        existing = await DB.get_coin(address)
        if existing:
            await DB.update_coin_signal(address, analysis["signal"], analysis["confidence"])
            await DB.record_price_history(
                token_address=address,
                symbol=token.get("symbol", "UNKNOWN"),
                price_usd=token.get("priceUsd", 0),
                volume_24h=token.get("volume", {}).get("h24"),
                liquidity_usd=token.get("liquidity", {}).get("usd"),
                market_cap=token.get("marketCap") or 0,
                signal=analysis["signal"],
                confidence=analysis["confidence"],
            )
        else:
            await DB.add_coin(
                token_address=address,
                symbol=token.get("symbol", "UNKNOWN"),
                name=token.get("name", "Unknown"),
                price_at_discovery=token.get("priceUsd", 0),
                ai_score=analysis["confidence"],
                signal=analysis["signal"],
                deployer_address=deployer_address or "",
                discovery_source=token.get("source", "unknown"),
                chain=chain,
                extra_data={
                    "reasoning": analysis["reasoning"],
                    "risk_level": analysis["risk_level"],
                    "tags": analysis["tags"],
                    "source": token.get("source", "unknown"),
                    "chain": chain,
                    "basescan": token.get("basescan") if chain.lower() == "base" else None,
                    "contract_creation": token.get("contract_creation") if chain.lower() == "base" else None,
                    "top_holders": token.get("top_holders") if chain.lower() == "base" else None,
                },
            )
            
            if deployer_address:
                await DB.update_deployer_stats(deployer_address)

        # Log and execute significant signals
        if analysis["signal"] == "buy" and analysis["confidence"] > 0.7:
            await DB.log_event(
                "info", "strong_buy_signal",
                f"{token.get('symbol', 'UNKNOWN')} ({chain}): {analysis['reasoning']}",
                {"token_address": address, "symbol": token.get("symbol", ""), "chain": chain, "confidence": analysis["confidence"], "price": token.get("priceUsd", 0)},
            )
            await self._maybe_execute_trade(address, token, analysis, chain)

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

"""Token scanner — discovers coins via DexScreener and analyzes with Venice AI."""

import asyncio
import json
from datetime import datetime
from typing import List, Dict, Any, Optional

import httpx

from config import get_settings
from database import DB

settings = get_settings()

DEXSCREENER_BASE = "https://api.dexscreener.com"
VENICE_BASE = "https://api.venice.ai/api/v1"


class Scanner:
    """Scans for crypto opportunities and persists everything to the watchlist."""

    def __init__(self):
        self.http = httpx.AsyncClient(timeout=30.0)
        self.running = False

    async def close(self):
        await self.http.aclose()

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
                    "max_tokens": 500,
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

        # Step 1: Get trending token profiles
        profiles = await self.get_trending(chain)
        await DB.log_event("info", "tokens_discovered", f"Found {len(profiles)} token profiles", {"count": len(profiles)})

        for profile in profiles:
            address = profile.get("tokenAddress", "")
            if not address:
                continue

            # Step 2: Get detailed pair data for symbol, name, price, volume
            pairs = await self.get_token_pairs(address, chain)
            if not pairs:
                continue

            # Use the pair with highest liquidity
            best_pair = max(pairs, key=lambda p: float(p.get("liquidity", {}).get("usd", 0) or 0))

            # Extract token info from pair data
            base_token = best_pair.get("baseToken", {})
            symbol = base_token.get("symbol", "UNKNOWN")
            name = base_token.get("name", symbol)
            price = float(best_pair.get("priceUsd", 0) or 0)
            volume_24h = float(best_pair.get("volume", {}).get("h24", 0) or 0)
            liquidity = float(best_pair.get("liquidity", {}).get("usd", 0) or 0)
            market_cap = float(best_pair.get("marketCap", 0) or 0)
            price_change = float(best_pair.get("priceChange", {}).get("h24", 0) or 0)

            # Build enriched token dict for AI analysis
            enriched_token = {
                "tokenAddress": address,
                "symbol": symbol,
                "name": name,
                "priceUsd": price,
                "volume": {"h24": volume_24h},
                "liquidity": {"usd": liquidity},
                "marketCap": market_cap,
                "priceChange": {"h24": price_change},
            }

            # Step 3: AI analysis
            analysis = await self.analyze_opportunity(enriched_token)

            # Step 4: Persist to watchlist
            existing = await DB.get_coin(address)
            if existing:
                await DB.update_coin_signal(address, analysis["signal"], analysis["confidence"])
            else:
                await DB.add_coin(
                    token_address=address,
                    symbol=symbol,
                    name=name,
                    price_at_discovery=price,
                    ai_score=analysis["confidence"],
                    signal=analysis["signal"],
                    metadata={
                        "reasoning": analysis["reasoning"],
                        "risk_level": analysis["risk_level"],
                        "tags": analysis["tags"],
                    },
                )

            # Log significant signals
            if analysis["signal"] == "buy" and analysis["confidence"] > 0.7:
                await DB.log_event(
                    "info", "strong_buy_signal",
                    f"{symbol}: {analysis['reasoning']}",
                    {"token_address": address, "symbol": symbol, "confidence": analysis["confidence"], "price": price},
                )

            await asyncio.sleep(1)  # Rate limit between tokens

        await DB.log_event("info", "scan_completed", f"Scanned {len(profiles)} tokens")

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

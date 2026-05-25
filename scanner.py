"""Token scanner — discovers Solana coins via DexScreener and analyzes with rule-based scoring."""

import asyncio
import json
from datetime import datetime
from typing import List, Dict, Any, Optional

import httpx

from config import get_settings
from database import DB
from executor import Executor

settings = get_settings()

DEXSCREENER_BASE = "https://api.dexscreener.com"


class Scanner:
    """Scans for Solana pump.fun opportunities and persists to watchlist."""

    def __init__(self):
        self.http = httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": "Mozilla/5.0 (compatible; CryptoAgent/1.0)"},
        )
        self.running = False
        self.executor = Executor()
        # Rate limiters
        self._dexscreener_last_call = 0
        self._dexscreener_min_interval = 1.1

    async def close(self):
        await self.http.aclose()
        await self.executor.close()

    async def _dexscreener_rate_limit(self):
        """Enforce minimum interval between DexScreener API calls."""
        now = asyncio.get_event_loop().time()
        elapsed = now - self._dexscreener_last_call
        if elapsed < self._dexscreener_min_interval:
            await asyncio.sleep(self._dexscreener_min_interval - elapsed)
        self._dexscreener_last_call = asyncio.get_event_loop().time()

    # ── DexScreener API ──────────────────────────────────────────────

    async def get_trending_profiles(self, chain: str = "solana") -> List[Dict[str, Any]]:
        """Get trending token profiles on Solana."""
        url = f"{DEXSCREENER_BASE}/token-profiles/latest/v1"
        try:
            await self._dexscreener_rate_limit()
            resp = await self.http.get(url)
            resp.raise_for_status()
            data = resp.json()
            tokens = [
                t for t in data if t.get("chainId", "").lower() == "solana"
            ]
            return tokens[:50]
        except Exception as e:
            await DB.log_event("error", "dexscreener_profiles_failed", str(e))
            return []

    async def get_latest_pairs(self, chain: str = "solana") -> List[Dict[str, Any]]:
        """Get latest created pairs on Solana."""
        url = f"{DEXSCREENER_BASE}/latest/dex/search"
        try:
            await self._dexscreener_rate_limit()
            resp = await self.http.get(url, params={"q": "solana USDC"})
            resp.raise_for_status()
            data = resp.json()
            pairs = data.get("pairs", [])
            pairs = [p for p in pairs if p.get("chainId", "").lower() == "solana"]
            return pairs[:50]
        except Exception as e:
            await DB.log_event("error", "dexscreener_latest_pairs_failed", str(e))
            return []

    async def get_top_pairs(self, chain: str = "solana") -> List[Dict[str, Any]]:
        """Get top pairs by volume on Solana."""
        url = f"{DEXSCREENER_BASE}/latest/dex/search"
        try:
            await self._dexscreener_rate_limit()
            resp = await self.http.get(url, params={"q": "solana SOL"})
            resp.raise_for_status()
            data = resp.json()
            pairs = data.get("pairs", [])
            pairs = [p for p in pairs if p.get("chainId", "").lower() == "solana"]
            pairs.sort(key=lambda p: float(p.get("volume", {}).get("h24", 0) or 0), reverse=True)
            return pairs[:50]
        except Exception as e:
            await DB.log_event("error", "dexscreener_top_pairs_failed", str(e))
            return []

    async def search_pairs(self, query: str, chain: str = "solana") -> List[Dict[str, Any]]:
        """Search for pairs by token symbol/name."""
        url = f"{DEXSCREENER_BASE}/latest/dex/search"
        try:
            await self._dexscreener_rate_limit()
            resp = await self.http.get(url, params={"q": query})
            resp.raise_for_status()
            data = resp.json()
            pairs = data.get("pairs", [])
            pairs = [p for p in pairs if p.get("chainId", "").lower() == "solana"]
            return pairs[:30]
        except Exception as e:
            await DB.log_event("error", "dexscreener_search_failed", str(e))
            return []

    async def get_token_pairs(self, token_address: str, chain: str = "solana") -> List[Dict[str, Any]]:
        """Get pair data for a specific token."""
        url = f"{DEXSCREENER_BASE}/token-pairs/v1/solana/{token_address}"
        try:
            await self._dexscreener_rate_limit()
            resp = await self.http.get(url)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            await DB.log_event("error", "dexscreener_token_pairs_failed", str(e), {"token_address": token_address})
            return []

    async def get_pumpfun_pairs(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get pump.fun specific pairs on Solana."""
        url = f"{DEXSCREENER_BASE}/latest/dex/search"
        try:
            await self._dexscreener_rate_limit()
            resp = await self.http.get(url, params={"q": "pump.fun solana"})
            resp.raise_for_status()
            data = resp.json()
            pairs = data.get("pairs", [])
            # Filter for pump.fun pairs
            pump_pairs = [
                p for p in pairs
                if p.get("chainId", "").lower() == "solana"
                and "pump" in (p.get("dexId", "") + p.get("url", "")).lower()
            ]
            pump_pairs.sort(
                key=lambda p: float(p.get("volume", {}).get("h24", 0) or 0),
                reverse=True
            )
            return pump_pairs[:limit]
        except Exception as e:
            await DB.log_event("error", "dexscreener_pumpfun_failed", str(e))
            return []

    # ── Rule-based Analysis ──────────────────────────────────────────

    def _rule_based_signal(self, token: Dict[str, Any]) -> Dict[str, Any]:
        """Deterministic trading guardrails for pump.fun tokens."""
        price = float(token.get("priceUsd") or 0)
        volume = float(token.get("volume", {}).get("h24") or 0)
        liquidity = float(token.get("liquidity", {}).get("usd") or 0)
        price_change = float(token.get("priceChange", {}).get("h24") or 0)
        market_cap = float(token.get("marketCap") or 0)
        pair_age = float(token.get("pairCreatedAt", 0))
        # Calculate age in hours if timestamp available
        age_hours = 999
        if pair_age:
            age_hours = (datetime.utcnow().timestamp() * 1000 - pair_age) / (1000 * 3600)

        # Hard filters
        if price <= 0:
            return {"signal": "avoid", "confidence": 0.98, "reasoning": "No reliable USD price", "risk_level": "high", "tags": "no-price"}
        if liquidity < settings.pumpfun_min_liquidity_usd:
            return {"signal": "avoid", "confidence": 0.96, "reasoning": f"Liquidity too thin (${liquidity:,.0f})", "risk_level": "high", "tags": "low-liquidity"}
        if volume < 5000:
            return {"signal": "avoid", "confidence": 0.92, "reasoning": f"24h volume too low (${volume:,.0f})", "risk_level": "high", "tags": "low-volume"}
        if age_hours > settings.pumpfun_max_age_hours:
            return {"signal": "avoid", "confidence": 0.90, "reasoning": f"Token too old ({age_hours:.0f}h)", "risk_level": "high", "tags": "old-token"}
        if price_change < -20:
            return {"signal": "avoid", "confidence": 0.90, "reasoning": f"Sharp 24h drawdown ({price_change:.1f}%)", "risk_level": "high", "tags": "drawdown"}

        # Scoring
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
        if age_hours < 2:
            score += 0.15; tags.append("fresh-launch")

        if score >= 0.75:
            return {"signal": "buy", "confidence": min(0.90, score), "reasoning": f"Buy: liquidity ${liquidity:,.0f}, volume ${volume:,.0f}, 24h {price_change:.1f}%, age {age_hours:.1f}h", "risk_level": "medium", "tags": ",".join(tags)}
        if score >= 0.45:
            return {"signal": "hold", "confidence": min(0.75, score), "reasoning": f"Watch: liquidity ${liquidity:,.0f}, volume ${volume:,.0f}, 24h {price_change:.1f}%", "risk_level": "medium", "tags": ",".join(tags)}
        return {"signal": "avoid", "confidence": 0.75, "reasoning": f"Weak setup: liquidity ${liquidity:,.0f}, volume ${volume:,.0f}", "risk_level": "high", "tags": ",".join(tags) or "weak-setup"}

    # ── Main Scan Loop ───────────────────────────────────────────────

    async def scan_once(self, chain: str = None):
        """Run one scan cycle."""
        chains = ["solana"]
        for c in chains:
            await self._scan_chain(c)

    async def _scan_chain(self, chain: str):
        """Scan Solana for opportunities."""
        if chain.lower() != "solana":
            return

        tokens = []
        # Get pump.fun pairs
        pump_pairs = await self.get_pumpfun_pairs(limit=30)
        for pair in pump_pairs:
            base = pair.get("baseToken", {})
            tokens.append({
                "tokenAddress": base.get("address", ""),
                "symbol": base.get("symbol", "UNKNOWN"),
                "name": base.get("name", "Unknown"),
                "priceUsd": float(pair.get("priceUsd", 0) or 0),
                "volume": {"h24": float(pair.get("volume", {}).get("h24", 0) or 0)},
                "liquidity": {"usd": float(pair.get("liquidity", {}).get("usd", 0) or 0)},
                "marketCap": float(pair.get("marketCap", 0) or 0),
                "priceChange": {"h24": float(pair.get("priceChange", {}).get("h24", 0) or 0)},
                "pairCreatedAt": pair.get("pairCreatedAt", 0),
                "source": "pumpfun_dexscreener",
            })

        # Get trending profiles
        trending = await self.get_trending_profiles("solana")
        for t in trending:
            tokens.append({
                "tokenAddress": t.get("tokenAddress", ""),
                "symbol": t.get("symbol", "UNKNOWN"),
                "name": t.get("name", "Unknown"),
                "priceUsd": 0,
                "volume": {"h24": 0},
                "liquidity": {"usd": 0},
                "marketCap": 0,
                "priceChange": {"h24": 0},
                "source": "trending_profile",
            })

        # Get latest pairs
        latest = await self.get_latest_pairs("solana")
        for pair in latest:
            base = pair.get("baseToken", {})
            tokens.append({
                "tokenAddress": base.get("address", ""),
                "symbol": base.get("symbol", "UNKNOWN"),
                "name": base.get("name", "Unknown"),
                "priceUsd": float(pair.get("priceUsd", 0) or 0),
                "volume": {"h24": float(pair.get("volume", {}).get("h24", 0) or 0)},
                "liquidity": {"usd": float(pair.get("liquidity", {}).get("usd", 0) or 0)},
                "marketCap": float(pair.get("marketCap", 0) or 0),
                "priceChange": {"h24": float(pair.get("priceChange", {}).get("h24", 0) or 0)},
                "pairCreatedAt": pair.get("pairCreatedAt", 0),
                "source": "latest_pairs",
            })

        # Deduplicate by address
        seen = set()
        unique_tokens = []
        for t in tokens:
            addr = t.get("tokenAddress", "")
            if addr and addr not in seen:
                seen.add(addr)
                unique_tokens.append(t)

        # Process in batches
        batch_size = 5
        for i in range(0, len(unique_tokens), batch_size):
            batch = unique_tokens[i:i + batch_size]
            await asyncio.gather(*[self._process_token(token) for token in batch])

        await DB.log_event("info", "scan_completed", f"Scanned {len(unique_tokens)} Solana tokens, found {len([t for t in unique_tokens if t.get('signal') == 'buy'])} buy signals")

    async def _process_token(self, token: Dict[str, Any]):
        """Process a single token: enrich, analyze, persist."""
        address = token.get("tokenAddress", "")
        if not address:
            return

        # Get detailed pair data
        pairs = await self.get_token_pairs(address)
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
            token["pairCreatedAt"] = best_pair.get("pairCreatedAt", 0)

        # Rule-based analysis only (no LLM)
        analysis = self._rule_based_signal(token)

        # Persist to watchlist
        existing = await DB.get_coin(address)
        if existing:
            await DB.update_coin_signal(address, analysis["signal"], analysis["confidence"], {
                "reasoning": analysis["reasoning"],
                "risk_level": analysis["risk_level"],
                "tags": analysis["tags"],
                "source": token.get("source", "unknown"),
                "chain": "solana",
            })
            await DB.update_coin_market_data(
                token_address=address,
                price_usd=token.get("priceUsd", 0),
                volume_24h=token.get("volume", {}).get("h24"),
                liquidity_usd=token.get("liquidity", {}).get("usd"),
                market_cap=token.get("marketCap") or 0,
            )
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
                deployer_address=None,
                discovery_source=token.get("source", "unknown"),
                chain="solana",
                extra_data={
                    "reasoning": analysis["reasoning"],
                    "risk_level": analysis["risk_level"],
                    "tags": analysis["tags"],
                    "source": token.get("source", "unknown"),
                    "chain": "solana",
                },
            )
            await DB.update_coin_market_data(
                token_address=address,
                price_usd=token.get("priceUsd", 0),
                volume_24h=token.get("volume", {}).get("h24"),
                liquidity_usd=token.get("liquidity", {}).get("usd"),
                market_cap=token.get("marketCap") or 0,
            )
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

        # Execute strong buy signals
        if analysis["signal"] == "buy" and analysis["confidence"] > 0.7:
            await DB.log_event(
                "info", "strong_buy_signal",
                f"{token.get('symbol', 'UNKNOWN')}: {analysis['reasoning']}",
                {"token_address": address, "symbol": token.get("symbol", ""), "confidence": analysis["confidence"], "price": token.get("priceUsd", 0)},
            )
            await self._maybe_execute_trade(address, token, analysis)

    async def _maybe_execute_trade(self, address: str, token: Dict[str, Any], analysis: Dict[str, Any]):
        """Open one guarded trade for a strong buy signal."""
        if analysis.get("signal") != "buy" or float(analysis.get("confidence") or 0) < 0.70:
            return

        open_trades = await DB.get_trades(status="executed", limit=500)
        open_trades = [t for t in open_trades if getattr(t, "closed_at", None) is None]
        if len(open_trades) >= settings.max_positions:
            await DB.log_event("warning", "trade_skipped_max_positions", f"Max open positions reached ({settings.max_positions})")
            return
        if any(t.token_address == address for t in open_trades):
            await DB.log_event("info", "trade_skipped_existing_position", f"Already holding {token.get('symbol', 'UNKNOWN')}", {"token_address": address})
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
            chain="solana",
        )
        if trade_id:
            await DB.log_event(
                "info",
                "auto_trade_opened",
                f"{'Live' if effective_live else 'Paper'} buy opened for {token.get('symbol', 'UNKNOWN')} at ${amount_usd}",
                {"token_address": address, "trade_id": trade_id, "mode": "live" if effective_live else "paper"},
            )

    async def run(self):
        """Main scanner loop."""
        self.running = True
        await DB.log_event("info", "scanner_started", "Solana pump.fun scanner started")
        while self.running:
            try:
                await self.scan_once()
                await asyncio.sleep(settings.scan_interval_seconds)
            except Exception as e:
                await DB.log_event("error", "scanner_loop_failed", str(e))
                await asyncio.sleep(60)

    def stop(self):
        self.running = False

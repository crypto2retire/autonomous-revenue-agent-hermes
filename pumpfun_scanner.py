"""Pump.fun launch scanner — watches Solana token launches for short-term momentum plays.

Strategy: Get in early on pump.fun launches, target 25-50% gains, leave a moon bag.
Uses DexScreener for price data and Helius RPC for on-chain verification.
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

import httpx

from config import get_settings
from database import DB
from scanner import Scanner  # Reuse existing enrichment/analysis

settings = get_settings()

HELIUS_API = "https://mainnet.helius-rpc.com"
PUMPFUN_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"  # pump.fun program ID
DEXSCREENER_BASE = "https://api.dexscreener.com"


class PumpFunScanner:
    """Scans pump.fun for new token launches and momentum opportunities."""

    def __init__(self):
        self.http = httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": "Mozilla/5.0 (compatible; CryptoAgent/1.0)"},
        )
        self.running = False
        self._seen_mints: set = set()  # In-memory dedup; DB handles persistence
        self.scanner = Scanner()  # Reuse for analysis + trade execution

    async def close(self):
        await self.http.aclose()
        await self.scanner.close()

    # ── Helius RPC ────────────────────────────────────────────────────

    async def _helius_rpc(self, method: str, params: list) -> dict:
        """Call Helius RPC with the user's API key."""
        key = settings.helius_api_key.get_secret_value() if settings.helius_api_key else ""
        url = f"{HELIUS_API}/?api-key={key}"
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        resp = await self.http.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"Helius RPC error: {data['error']}")
        return data.get("result", {})

    async def is_pumpfun_token(self, token_address: str) -> bool:
        """Check if a token was created by the pump.fun program."""
        try:
            # Use getAsset to check creator / ownership
            result = await self._helius_rpc(
                "getAsset",
                [token_address],
            )
            # Check if the token's authority or creator matches pump.fun
            ownership = result.get("ownership", {})
            owner = ownership.get("owner", "")
            if owner == PUMPFUN_PROGRAM:
                return True
            # Also check creators list
            creators = result.get("creators", [])
            for creator in creators:
                if creator.get("address") == PUMPFUN_PROGRAM:
                    return True
            return False
        except Exception:
            return False

    # ── DexScreener: Discover pump.fun tokens ─────────────────────────

    async def get_latest_pumpswap_pairs(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get latest PumpSwap pairs from DexScreener (pump.fun's DEX)."""
        url = f"{DEXSCREENER_BASE}/latest/dex/search"
        try:
            resp = await self.http.get(url, params={"q": "pumpswap"})
            resp.raise_for_status()
            data = resp.json()
            pairs = data.get("pairs", [])
            # Filter to Solana only and pump-related DEXes
            pairs = [
                p for p in pairs
                if p.get("chainId", "").lower() == "solana"
                and "pump" in str(p.get("dexId", "")).lower()
            ]
            return pairs[:limit]
        except Exception as e:
            await DB.log_event("error", "dexscreener_pumpswap_failed", str(e))
            return []

    async def get_solana_token_pairs(self, token_address: str) -> List[Dict[str, Any]]:
        """Get pair data for a Solana token from DexScreener."""
        url = f"{DEXSCREENER_BASE}/token-pairs/v1/solana/{token_address}"
        try:
            resp = await self.http.get(url)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            await DB.log_event("error", "dexscreener_sol_pairs_failed", str(e), {"token": token_address})
            return []

    async def get_solana_token_price(self, token_address: str) -> Optional[float]:
        """Get current USD price for a Solana token."""
        pairs = await self.get_solana_token_pairs(token_address)
        if not pairs:
            return None
        best = max(pairs, key=lambda p: float(p.get("liquidity", {}).get("usd", 0) or 0))
        return float(best.get("priceUsd", 0) or 0)

    # ── Launch detection ──────────────────────────────────────────────

    async def detect_new_launches(self, limit: int = 30) -> List[Dict[str, Any]]:
        """Detect new pump.fun token launches via DexScreener PumpSwap pairs."""
        # Get latest PumpSwap pairs
        pairs = await self.get_latest_pumpswap_pairs(limit=limit)
        launches = []

        for pair in pairs:
            base_token = pair.get("baseToken", {})
            token_address = base_token.get("address", "")
            if not token_address:
                continue

            # Skip if already seen
            if token_address in self._seen_mints:
                continue

            # Quick filter: micro-cap tokens are more likely fresh launches
            mcap = float(pair.get("marketCap", 0) or 0)
            liquidity = float(pair.get("liquidity", {}).get("usd", 0) or 0)
            volume = float(pair.get("volume", {}).get("h24", 0) or 0)

            # Skip if too large (not a fresh launch)
            if mcap > 5_000_000:
                continue
            if liquidity < 1000:
                continue

            self._seen_mints.add(token_address)

            launch = {
                "tokenAddress": token_address,
                "symbol": base_token.get("symbol", "UNKNOWN"),
                "name": base_token.get("name", "Unknown"),
                "chain": "solana",
                "priceUsd": float(pair.get("priceUsd", 0) or 0),
                "volume": {"h24": volume},
                "liquidity": {"usd": liquidity},
                "marketCap": mcap,
                "priceChange": {"h24": float(pair.get("priceChange", {}).get("h24", 0) or 0)},
                "source": "pumpfun_launch",
                "launch_time": datetime.utcnow().isoformat(),
            }
            launches.append(launch)

        return launches

    # ── Momentum analysis for pump.fun tokens ─────────────────────────

    async def analyze_pumpfun_opportunity(self, token: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze a pump.fun token for short-term momentum play."""
        price = float(token.get("priceUsd") or 0)
        volume = float(token.get("volume", {}).get("h24") or 0)
        liquidity = float(token.get("liquidity", {}).get("usd") or 0)
        mcap = float(token.get("marketCap") or 0)
        price_change = float(token.get("priceChange", {}).get("h24") or 0)

        # Pump.fun specific filters
        if price <= 0:
            return {"signal": "avoid", "confidence": 0.98, "reasoning": "No price data", "risk_level": "high", "tags": "no-price"}
        if liquidity < 5000:
            return {"signal": "avoid", "confidence": 0.95, "reasoning": f"Liquidity too thin (${liquidity:,.0f})", "risk_level": "high", "tags": "low-liquidity"}
        if mcap > 10_000_000:
            return {"signal": "avoid", "confidence": 0.85, "reasoning": f"Market cap too high for pump play (${mcap:,.0f})", "risk_level": "medium", "tags": "too-big"}

        score = 0.0
        tags = []

        # Early launch bonus (under 1 hour old)
        score += 0.20
        tags.append("fresh-launch")

        if liquidity >= 10000:
            score += 0.15; tags.append("liquid")
        if volume >= liquidity * 0.3:
            score += 0.20; tags.append("volume-momentum")
        if 10 <= price_change <= 200:
            score += 0.20; tags.append("momentum")
        if mcap < 1_000_000:
            score += 0.15; tags.append("micro-cap")
        elif mcap < 5_000_000:
            score += 0.10; tags.append("small-cap")

        if score >= 0.70:
            return {
                "signal": "buy",
                "confidence": min(0.88, score),
                "reasoning": f"Pump.fun momentum: liq ${liquidity:,.0f}, vol ${volume:,.0f}, mcap ${mcap:,.0f}, +{price_change:.1f}%",
                "risk_level": "high",
                "tags": ",".join(tags),
            }
        if score >= 0.45:
            return {
                "signal": "hold",
                "confidence": min(0.70, score),
                "reasoning": f"Monitoring pump.fun: liq ${liquidity:,.0f}, vol ${volume:,.0f}, mcap ${mcap:,.0f}",
                "risk_level": "high",
                "tags": ",".join(tags),
            }
        return {
            "signal": "avoid",
            "confidence": 0.70,
            "reasoning": f"Weak pump.fun setup: liq ${liquidity:,.0f}, vol ${volume:,.0f}, mcap ${mcap:,.0f}",
            "risk_level": "high",
            "tags": ",".join(tags) or "weak-setup",
        }

    # ── Position management: 25-50% profit target + moon bag ──────────

    async def check_pumpfun_positions(self):
        """Check open pump.fun positions for profit targets."""
        open_trades = await DB.get_trades(status="executed", chain="solana", limit=100)
        open_trades = [t for t in open_trades if getattr(t, "closed_at", None) is None]

        for trade in open_trades:
            # Only manage trades tagged as pump.fun
            coin = await DB.get_coin(str(trade.token_address))
            if not coin or "pumpfun" not in (str(coin.tags or "")):
                continue

            current_price = await self.get_solana_token_price(str(trade.token_address))
            if not current_price or not trade.entry_price:
                continue

            entry = float(trade.entry_price)
            gain_pct = ((current_price - entry) / entry) * 100

            # Profit targets
            if gain_pct >= 50:
                # Sell 80%, keep 20% moon bag
                await self._partial_sell(trade, current_price, sell_pct=0.80, reason=f"50% profit target hit ({gain_pct:.1f}%)")
            elif gain_pct >= 25:
                # Sell 60%, keep 40% moon bag
                await self._partial_sell(trade, current_price, sell_pct=0.60, reason=f"25% profit target hit ({gain_pct:.1f}%)")
            elif gain_pct <= -15:
                # Cut losses
                await self.scanner.executor.execute_sell(
                    token_address=str(trade.token_address),
                    symbol=str(trade.symbol),
                    amount_token=0,  # Sell all
                    trade_id=str(trade.trade_id),
                    chain="solana",
                    reason=f"Stop loss: {gain_pct:.1f}%",
                )

    async def _partial_sell(self, trade, current_price: float, sell_pct: float, reason: str):
        """Execute a partial sell to take profits, leaving a moon bag."""
        from executor import Executor
        executor = Executor()
        try:
            # Calculate token amount to sell
            # We don't track token balances directly; use amount_usd approximation
            total_usd = float(trade.amount_usd or 0)
            sell_usd = total_usd * sell_pct

            await executor.execute_sell(
                token_address=str(trade.token_address),
                symbol=str(trade.symbol),
                amount_token=sell_usd / current_price if current_price > 0 else 0,
                trade_id=str(trade.trade_id),
                chain="solana",
                reason=reason,
            )
            await DB.log_event(
                "info", "pumpfun_partial_sell",
                f"Sold {sell_pct*100:.0f}% of {trade.symbol} — {reason}",
                {"token": str(trade.token_address), "sell_pct": sell_pct, "reason": reason},
            )
        finally:
            await executor.close()

    # ── Main scan loop ────────────────────────────────────────────────

    async def scan_once(self):
        """One scan cycle: detect launches → analyze → maybe buy."""
        await DB.log_event("info", "pumpfun_scan_started", "Scanning pump.fun for new launches")

        launches = await self.detect_new_launches(limit=30)
        await DB.log_event("info", "pumpfun_launches_found", f"Found {len(launches)} new launches", {"count": len(launches)})

        for launch in launches:
            analysis = await self.analyze_pumpfun_opportunity(launch)

            # Persist to watchlist
            existing = await DB.get_coin(launch["tokenAddress"])
            if existing:
                await DB.update_coin_signal(
                    launch["tokenAddress"],
                    analysis["signal"],
                    analysis["confidence"],
                    extra_data={
                        "reasoning": analysis["reasoning"],
                        "risk_level": analysis["risk_level"],
                        "tags": f"pumpfun,{analysis['tags']}",
                        "source": "pumpfun_launch",
                        "chain": "solana",
                        "launch_time": launch.get("launch_time"),
                    },
                )
                await DB.update_coin_market_data(
                    token_address=launch["tokenAddress"],
                    price_usd=launch.get("priceUsd", 0),
                    volume_24h=launch.get("volume", {}).get("h24"),
                    liquidity_usd=launch.get("liquidity", {}).get("usd"),
                    market_cap=launch.get("marketCap") or 0,
                )
            else:
                await DB.add_coin(
                    token_address=launch["tokenAddress"],
                    symbol=launch.get("symbol", "UNKNOWN"),
                    name=launch.get("name", "Unknown"),
                    price_at_discovery=launch.get("priceUsd", 0),
                    ai_score=analysis["confidence"],
                    signal=analysis["signal"],
                    deployer_address="",
                    discovery_source="pumpfun_launch",
                    chain="solana",
                    extra_data={
                        "reasoning": analysis["reasoning"],
                        "risk_level": analysis["risk_level"],
                        "tags": f"pumpfun,{analysis['tags']}",
                        "source": "pumpfun_launch",
                        "chain": "solana",
                        "launch_time": launch.get("launch_time"),
                    },
                )
                await DB.update_coin_market_data(
                    token_address=launch["tokenAddress"],
                    price_usd=launch.get("priceUsd", 0),
                    volume_24h=launch.get("volume", {}).get("h24"),
                    liquidity_usd=launch.get("liquidity", {}).get("usd"),
                    market_cap=launch.get("marketCap") or 0,
                )

            # Execute buy on strong signals
            if analysis["signal"] == "buy" and analysis["confidence"] >= 0.75:
                await DB.log_event(
                    "info", "pumpfun_buy_signal",
                    f"{launch.get('symbol', 'UNKNOWN')}: {analysis['reasoning']}",
                    {"token": launch["tokenAddress"], "confidence": analysis["confidence"]},
                )
                await self.scanner._maybe_execute_trade(
                    launch["tokenAddress"], launch, analysis, "solana"
                )

        # Check existing positions for profit targets
        await self.check_pumpfun_positions()

        await DB.log_event("info", "pumpfun_scan_completed", f"Processed {len(launches)} launches")

    async def run(self):
        """Continuous pump.fun scan loop."""
        self.running = True
        while self.running:
            try:
                await self.scan_once()
            except Exception as e:
                await DB.log_event("error", "pumpfun_scan_cycle_failed", str(e))
            await asyncio.sleep(60)  # Check every minute for new launches

    def stop(self):
        self.running = False

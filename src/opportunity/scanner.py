"""Opportunity scanner focused on holder behavior and volume as leading indicators."""

import asyncio
from decimal import Decimal
from typing import AsyncGenerator
from datetime import datetime, timedelta

from src.opportunity.models import (
    Opportunity,
    OpportunityStatus,
    HolderMetrics,
    VolumeMetrics,
    OpportunityFilter,
)
from src.data.dexscreener import DexScreenerClient
from src.data.basescan import BaseScanClient
from src.venice import VeniceClient
from src.utils.logger import get_logger

logger = get_logger(__name__)


class OpportunityScanner:
    """Scans for trading opportunities using holder + volume signals."""

    def __init__(
        self,
        venice_client: VeniceClient,
        dexscreener=None,
        basescan=None,
        filter_criteria=None,
    ):
        self.venice = venice_client
        self.dexscreener = dexscreener or DexScreenerClient()
        self.basescan = basescan or BaseScanClient()
        self.filter = filter_criteria or OpportunityFilter()
        self._running = False

    async def scan(self) -> list[Opportunity]:
        """Run a full scan for opportunities.

        Focuses on:
        1. Holder growth (new wallets = early interest)
        2. Volume spikes (activity before price moves)
        3. Smart money flows (whale movements)
        4. Concentration changes (distribution vs accumulation)
        """
        logger.info("starting_opportunity_scan")

        opportunities = []

        # Discover tokens from DexScreener
        discovered_tokens = await self._discover_tokens()
        logger.info("tokens_discovered", count=len(discovered_tokens))

        for token_info in discovered_tokens:
            try:
                opportunity = await self._analyze_token(token_info)
                if opportunity and self._passes_filter(opportunity):
                    opportunities.append(opportunity)
                    logger.info(
                        "opportunity_discovered",
                        token=opportunity.token_symbol,
                        signal=opportunity.ai_signal,
                        confidence=opportunity.ai_confidence,
                    )
            except Exception as e:
                logger.error(
                    "token_analysis_failed",
                    token=token_info.get("symbol", "unknown"),
                    error=str(e),
                )

        logger.info(
            "scan_complete",
            opportunities_found=len(opportunities),
        )
        return opportunities

    async def _discover_tokens(self) -> list[dict]:
        """Discover tokens from multiple sources."""
        tokens = []

        # Method 1: Latest boosted tokens (marketing activity)
        try:
            boosted = await self.dexscreener.get_boosted_tokens()
            for token in boosted:
                tokens.append({
                    "address": token.get("tokenAddress"),
                    "chain": token.get("chainId"),
                    "symbol": None,  # Will be fetched
                    "source": "boosted",
                })
        except Exception as e:
            logger.error("boosted_tokens_fetch_failed", error=str(e))

        # Method 2: Latest profiles (new listings)
        try:
            profiles = await self.dexscreener.get_latest_profiles()
            for profile in profiles:
                tokens.append({
                    "address": profile.get("tokenAddress"),
                    "chain": profile.get("chainId"),
                    "symbol": None,
                    "source": "profile",
                })
        except Exception as e:
            logger.error("profiles_fetch_failed", error=str(e))

        # Deduplicate by address
        seen = set()
        unique_tokens = []
        for t in tokens:
            addr = t.get("address")
            if addr and addr not in seen:
                seen.add(addr)
                unique_tokens.append(t)

        return unique_tokens

    async def _analyze_token(self, token_info):
        """Analyze a single token for opportunity signals."""
        token_address = token_info.get("address")
        chain = token_info.get("chain", "base")

        if not token_address:
            return None

        # Fetch DexScreener data
        try:
            pair_data = await self.dexscreener.get_token_pairs(chain, token_address)
            metrics = self.dexscreener.extract_metrics(pair_data)
        except Exception as e:
            logger.error("dexscreener_fetch_failed", token=token_address, error=str(e))
            return None

        if not metrics:
            return None

        # Fetch BaseScan holder data
        holder_metrics = await self._fetch_holder_metrics(token_address)

        # Build volume metrics from DexScreener
        volume_metrics = VolumeMetrics(
            volume_24h_usd=metrics.get("volume_24h", Decimal("0")),
            volume_7d_usd=metrics.get("volume_24h", Decimal("0")) * Decimal("7"),  # Estimate
            volume_change_24h_pct=Decimal("0"),  # Would need historical data
            buy_volume_24h_usd=metrics.get("volume_24h", Decimal("0")) * (metrics.get("buy_sell_ratio", Decimal("1")) / (metrics.get("buy_sell_ratio", Decimal("1")) + Decimal("1"))),
            sell_volume_24h_usd=metrics.get("volume_24h", Decimal("0")) / (metrics.get("buy_sell_ratio", Decimal("1")) + Decimal("1")),
            buy_sell_ratio=metrics.get("buy_sell_ratio", Decimal("1")),
            liquidity_usd=metrics.get("liquidity_usd", Decimal("0")),
            liquidity_change_24h_pct=Decimal("0"),
            unique_traders_24h=metrics.get("buys_24h", 0) + metrics.get("sells_24h", 0),
            avg_trade_size_usd=metrics.get("volume_24h", Decimal("0")) / max(metrics.get("buys_24h", 0) + metrics.get("sells_24h", 0), 1),
        )

        # Create opportunity
        opportunity = Opportunity(
            token_address=token_address,
            token_symbol=metrics.get("token_symbol", "UNKNOWN"),
            token_name=metrics.get("token_name", "Unknown"),
            chain=chain,
            current_price_usd=metrics.get("price_usd", Decimal("0")),
            price_change_24h_pct=metrics.get("price_change_24h", Decimal("0")),
            price_change_7d_pct=metrics.get("price_change_24h", Decimal("0")) * Decimal("7"),  # Rough estimate
            market_cap_usd=metrics.get("market_cap"),
            fdv_usd=metrics.get("fdv"),
            holder_metrics=holder_metrics,
            volume_metrics=volume_metrics,
        )

        # Get AI analysis
        try:
            analysis = await self.venice.analyze_opportunity(
                token_data={
                    "symbol": opportunity.token_symbol,
                    "price_usd": float(opportunity.current_price_usd),
                    "price_change_24h": float(opportunity.price_change_24h_pct),
                    "market_cap": float(opportunity.market_cap_usd) if opportunity.market_cap_usd else None,
                    "fdv": float(opportunity.fdv_usd) if opportunity.fdv_usd else None,
                    "liquidity_usd": float(metrics.get("liquidity_usd", 0)),
                    "volume_24h": float(metrics.get("volume_24h", 0)),
                    "buy_sell_ratio": float(metrics.get("buy_sell_ratio", 1)),
                    "pair_created_at": metrics.get("pair_created_at"),
                },
                holder_data=holder_metrics.model_dump(),
                volume_data=volume_metrics.model_dump(),
            )

            opportunity.ai_signal = analysis.get("signal")
            opportunity.ai_confidence = Decimal(str(analysis.get("confidence", 0)))
            opportunity.ai_reasoning = analysis.get("reasoning")
            opportunity.ai_risk_level = analysis.get("risk_level")
            opportunity.suggested_position_size_pct = Decimal(str(analysis.get("suggested_position_size_pct", 0)))
        except Exception as e:
            logger.error("ai_analysis_failed", token=token_address, error=str(e))
            opportunity.ai_signal = "avoid"
            opportunity.ai_confidence = Decimal("0")
            opportunity.ai_reasoning = f"Analysis failed: {str(e)}"
            opportunity.ai_risk_level = "high"
            opportunity.suggested_position_size_pct = Decimal("0")

        return opportunity

    async def _fetch_holder_metrics(self, token_address: str) -> HolderMetrics:
        """Fetch holder metrics from BaseScan."""
        try:
            # Get holder count
            total_holders = await self.basescan.get_holder_count(token_address)

            # Get top holders for concentration analysis
            top_holders = await self.basescan.get_token_holders(token_address, page=1, offset=100)

            # Get total supply for concentration calc
            total_supply = await self.basescan.get_token_supply(token_address)

            # Extract concentration metrics
            concentration = self.basescan.extract_holder_metrics(top_holders, total_supply)

            return HolderMetrics(
                total_holders=total_holders,
                new_holders_24h=0,  # Would need historical tracking
                new_holders_7d=0,
                active_holders_24h=0,
                concentration_top_10=Decimal(str(concentration.get("top_10_pct", 0))),
                concentration_top_50=Decimal(str(concentration.get("top_50_pct", 0))),
                smart_money_inflows_24h=Decimal("0"),  # Would need smart money labels
                smart_money_outflows_24h=Decimal("0"),
                avg_hold_time_days=Decimal("0"),
                holder_growth_rate=Decimal("0"),  # Would need historical data
            )

        except Exception as e:
            logger.error("holder_metrics_fetch_failed", token=token_address, error=str(e))
            return HolderMetrics(
                total_holders=0,
                new_holders_24h=0,
                new_holders_7d=0,
                active_holders_24h=0,
                concentration_top_10=Decimal("0"),
                concentration_top_50=Decimal("0"),
                smart_money_inflows_24h=Decimal("0"),
                smart_money_outflows_24h=Decimal("0"),
                avg_hold_time_days=Decimal("0"),
                holder_growth_rate=Decimal("0"),
            )

    def _passes_filter(self, opportunity: Opportunity) -> bool:
        """Check if opportunity meets minimum criteria."""
        hm = opportunity.holder_metrics
        vm = opportunity.volume_metrics

        checks = [
            hm.total_holders >= self.filter.min_holders,
            vm.volume_24h_usd >= self.filter.min_volume_24h_usd,
            vm.liquidity_usd >= self.filter.min_liquidity_usd,
            hm.concentration_top_10 <= self.filter.max_concentration_top_10,
            hm.holder_growth_rate >= self.filter.min_holder_growth_rate,
            vm.buy_sell_ratio >= self.filter.min_buy_sell_ratio,
            opportunity.chain in self.filter.chains,
            opportunity.token_address not in self.filter.exclude_tokens,
        ]

        return all(checks)

    async def continuous_scan(
        self,
        interval_seconds: int = 300,
    ) -> AsyncGenerator[list[Opportunity], None]:
        """Continuously scan for opportunities.

        Args:
            interval_seconds: Time between scans (default: 5 minutes)
        """
        self._running = True
        logger.info("continuous_scan_started", interval_seconds=interval_seconds)

        while self._running:
            try:
                opportunities = await self.scan()
                yield opportunities
            except Exception as e:
                logger.error("scan_cycle_failed", error=str(e))

            await asyncio.sleep(interval_seconds)

    def stop(self):
        """Stop continuous scanning."""
        self._running = False
        logger.info("continuous_scan_stopped")

    async def close(self):
        """Close all data clients."""
        await self.dexscreener.close()
        await self.basescan.close()

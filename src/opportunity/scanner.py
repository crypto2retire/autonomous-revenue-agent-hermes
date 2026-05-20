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
from src.venice import VeniceClient
from src.utils.logger import get_logger

logger = get_logger(__name__)


class OpportunityScanner:
    """Scans for trading opportunities using holder + volume signals."""

    def __init__(
        self,
        venice_client: VeniceClient,
        filter_criteria: OpportunityFilter | None = None,
    ):
        self.venice = venice_client
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

        # TODO: Integrate with actual data sources
        # For now, we'll structure the scanner to accept data from:
        # - DexScreener API (volume, price, liquidity)
        # - BaseScan API (holder data, transfers)
        # - Dune Analytics (smart money labels)
        # - Alchemy/Infura (raw on-chain data)

        # Example data structure for a token
        raw_tokens = await self._fetch_token_data()

        for token_data in raw_tokens:
            try:
                opportunity = await self._analyze_token(token_data)
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
                    token=token_data.get("symbol", "unknown"),
                    error=str(e),
                )

        logger.info(
            "scan_complete",
            opportunities_found=len(opportunities),
        )
        return opportunities

    async def _fetch_token_data(self) -> list[dict]:
        """Fetch raw token data from data sources.

        TODO: Implement actual API integrations:
        - DexScreener: /token-pairs/v1/base/{tokenAddress}
        - BaseScan: /api?module=stats&action=tokensupply
        - Dune: Custom queries for smart money
        """
        # Placeholder - return empty list for now
        # In production, this would fetch from APIs
        logger.warning("using_placeholder_token_data")
        return []

    async def _analyze_token(self, token_data: dict) -> Opportunity | None:
        """Analyze a single token for opportunity signals."""
        
        # Build holder metrics
        holder_metrics = HolderMetrics(
            total_holders=token_data.get("holder_count", 0),
            new_holders_24h=token_data.get("new_holders_24h", 0),
            new_holders_7d=token_data.get("new_holders_7d", 0),
            active_holders_24h=token_data.get("active_holders_24h", 0),
            concentration_top_10=Decimal(str(token_data.get("top_10_pct", 0))),
            concentration_top_50=Decimal(str(token_data.get("top_50_pct", 0))),
            smart_money_inflows_24h=Decimal(str(token_data.get("smart_inflow", 0))),
            smart_money_outflows_24h=Decimal(str(token_data.get("smart_outflow", 0))),
            avg_hold_time_days=Decimal(str(token_data.get("avg_hold_time", 0))),
            holder_growth_rate=Decimal(str(token_data.get("holder_growth", 0))),
        )

        # Build volume metrics
        volume_metrics = VolumeMetrics(
            volume_24h_usd=Decimal(str(token_data.get("volume_24h", 0))),
            volume_7d_usd=Decimal(str(token_data.get("volume_7d", 0))),
            volume_change_24h_pct=Decimal(str(token_data.get("volume_change_24h", 0))),
            buy_volume_24h_usd=Decimal(str(token_data.get("buy_volume_24h", 0))),
            sell_volume_24h_usd=Decimal(str(token_data.get("sell_volume_24h", 0))),
            buy_sell_ratio=Decimal(str(token_data.get("buy_sell_ratio", 1.0))),
            liquidity_usd=Decimal(str(token_data.get("liquidity_usd", 0))),
            liquidity_change_24h_pct=Decimal(str(token_data.get("liquidity_change_24h", 0))),
            unique_traders_24h=token_data.get("unique_traders_24h", 0),
            avg_trade_size_usd=Decimal(str(token_data.get("avg_trade_size", 0))),
        )

        # Create opportunity
        opportunity = Opportunity(
            token_address=token_data.get("address", ""),
            token_symbol=token_data.get("symbol", ""),
            token_name=token_data.get("name", ""),
            chain=token_data.get("chain", "base"),
            current_price_usd=Decimal(str(token_data.get("price_usd", 0))),
            price_change_24h_pct=Decimal(str(token_data.get("price_change_24h", 0))),
            price_change_7d_pct=Decimal(str(token_data.get("price_change_7d", 0))),
            market_cap_usd=Decimal(str(token_data.get("market_cap", 0))) if token_data.get("market_cap") else None,
            fdv_usd=Decimal(str(token_data.get("fdv", 0))) if token_data.get("fdv") else None,
            holder_metrics=holder_metrics,
            volume_metrics=volume_metrics,
        )

        # Get AI analysis
        analysis = await self.venice.analyze_opportunity(
            token_data={
                "symbol": opportunity.token_symbol,
                "price_usd": float(opportunity.current_price_usd),
                "price_change_24h": float(opportunity.price_change_24h_pct),
                "market_cap": float(opportunity.market_cap_usd) if opportunity.market_cap_usd else None,
            },
            holder_data=holder_metrics.model_dump(),
            volume_data=volume_metrics.model_dump(),
        )

        opportunity.ai_signal = analysis.get("signal")
        opportunity.ai_confidence = Decimal(str(analysis.get("confidence", 0)))
        opportunity.ai_reasoning = analysis.get("reasoning")
        opportunity.ai_risk_level = analysis.get("risk_level")
        opportunity.suggested_position_size_pct = Decimal(str(analysis.get("suggested_position_size_pct", 0)))

        return opportunity

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

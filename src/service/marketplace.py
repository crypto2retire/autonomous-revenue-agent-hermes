"""Service marketplace for agent-to-agent commerce."""

from decimal import Decimal
from datetime import datetime
from typing import Any

from src.venice import VeniceClient
from src.service.wsic_client import WSICClient
from src.utils.logger import get_logger

logger = get_logger(__name__)


class ServiceMarketplace:
    """Manages service offerings and seeks service opportunities.

    The agent can:
    1. Offer its own services (WhatShouldICharge estimates, etc.)
    2. Purchase services from other agents
    3. Find arbitrage opportunities between service providers
    """

    def __init__(
        self,
        venice_client: VeniceClient,
        wsic_client: WSICClient,
    ):
        self.venice = venice_client
        self.wsic = wsic_client
        self._service_catalog: list[dict[str, Any]] = []

    async def initialize_services(self):
        """Set up initial service offerings."""
        # Create WhatShouldICharge service offering
        await self._create_wsic_offering()

        # TODO: Add other services as they become available
        # - CTC Business Hub (Phase 2)
        # - BMM-POS (Phase 2)
        # - DoneLocal (Phase 2)

        logger.info(
            "services_initialized",
            service_count=len(self._service_catalog),
        )

    async def _create_wsic_offering(self):
        """Create WhatShouldICharge service offering."""
        try:
            offering = await self.wsic.create_service_offering(
                name="AI Pricing Estimates",
                description="Get accurate pricing estimates for junk removal and service businesses using AI",
                base_price=Decimal("5.00"),
                features=[
                    "Instant price estimate",
                    "Location-based pricing",
                    "Market rate comparison",
                    "Profit margin analysis",
                ],
            )

            self._service_catalog.append(offering)
            logger.info("wsic_offering_created", offering_id=offering.get("id"))

        except Exception as e:
            logger.error("wsic_offering_failed", error=str(e))

    async def find_service_opportunities(self) -> list[dict[str, Any]]:
        """Find opportunities to sell services.

        Looks for:
        - Agents requesting pricing services
        - Underserved markets
        - Price arbitrage between providers
        """
        opportunities = []

        # Check for service requests
        # TODO: Monitor agent marketplaces, forums, APIs

        # Check our own service performance
        revenue = await self.wsic.get_service_revenue(days=7)
        if revenue > 0:
            logger.info("service_revenue_detected", revenue=float(revenue))

        return opportunities

    async def generate_marketing_content(
        self,
        service_name: str,
        target: str,
    ) -> str:
        """Generate marketing content for a service."""
        features = []
        for svc in self._service_catalog:
            if svc.get("name") == service_name:
                features = svc.get("features", [])
                break

        pitch = await self.venice.generate_service_pitch(
            service_name=service_name,
            target_audience=target,
            features=features,
        )

        return pitch

    async def get_revenue_report(self) -> dict[str, Any]:
        """Get comprehensive service revenue report."""
        daily_revenue = await self.wsic.get_service_revenue(days=1)
        weekly_revenue = await self.wsic.get_service_revenue(days=7)
        monthly_revenue = await self.wsic.get_service_revenue(days=30)

        return {
            "daily_revenue": float(daily_revenue),
            "weekly_revenue": float(weekly_revenue),
            "monthly_revenue": float(monthly_revenue),
            "active_services": len(self._service_catalog),
            "services": [
                {
                    "name": s.get("name"),
                    "price": s.get("base_price"),
                    "id": s.get("id"),
                }
                for s in self._service_catalog
            ],
            "timestamp": datetime.utcnow().isoformat(),
        }

"""WhatShouldICharge API client for service offerings."""

import httpx
from decimal import Decimal
from typing import Any

from src.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


class WSICClient:
    """Client for WhatShouldICharge API.

    Allows the agent to:
    - Generate pricing estimates
    - Create service offerings
    - Track service revenue
    """

    def __init__(self):
        self.base_url = settings.wsic_base_url
        self.api_key = settings.wsic_api_key.get_secret_value()
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=self.headers,
            timeout=30.0,
        )

    async def generate_estimate(
        self,
        service_type: str,
        location: str,
        details: dict[str, Any],
    ) -> dict[str, Any]:
        """Generate a pricing estimate for a service.

        Args:
            service_type: Type of service (e.g., "junk_removal")
            location: Customer location
            details: Service-specific details

        Returns:
            Estimate with price range and factors
        """
        payload = {
            "service_type": service_type,
            "location": location,
            "details": details,
        }

        try:
            response = await self.client.post(
                "/api/v1/estimates",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

            logger.info(
                "estimate_generated",
                service_type=service_type,
                location=location,
                estimate=data.get("estimated_price"),
            )

            return data

        except httpx.HTTPStatusError as e:
            logger.error(
                "wsic_api_error",
                status_code=e.response.status_code,
                response=e.response.text,
            )
            raise
        except Exception as e:
            logger.error("wsic_request_failed", error=str(e))
            raise

    async def create_service_offering(
        self,
        name: str,
        description: str,
        base_price: Decimal,
        features: list[str],
    ) -> dict[str, Any]:
        """Create a service offering that other agents can purchase.

        Args:
            name: Service name
            description: Service description
            base_price: Starting price in USD
            features: List of included features

        Returns:
            Created service offering
        """
        payload = {
            "name": name,
            "description": description,
            "base_price": float(base_price),
            "features": features,
            "provider": "autonomous_agent",
        }

        try:
            response = await self.client.post(
                "/api/v1/services",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

            logger.info(
                "service_offering_created",
                service_id=data.get("id"),
                name=name,
                price=float(base_price),
            )

            return data

        except Exception as e:
            logger.error("service_creation_failed", error=str(e))
            raise

    async def get_service_revenue(self, days: int = 30) -> Decimal:
        """Get total revenue from services over time period.

        Args:
            days: Number of days to look back

        Returns:
            Total revenue in USD
        """
        try:
            response = await self.client.get(
                "/api/v1/revenue",
                params={"days": days},
            )
            response.raise_for_status()
            data = response.json()

            revenue = Decimal(str(data.get("total_revenue", 0)))
            logger.info(
                "service_revenue_fetched",
                revenue=float(revenue),
                days=days,
            )

            return revenue

        except Exception as e:
            logger.error("revenue_fetch_failed", error=str(e))
            return Decimal("0")

    async def list_available_services(self) -> list[dict[str, Any]]:
        """List services available for purchase.

        Returns:
            List of service offerings
        """
        try:
            response = await self.client.get("/api/v1/services")
            response.raise_for_status()
            data = response.json()

            return data.get("services", [])

        except Exception as e:
            logger.error("services_list_failed", error=str(e))
            return []

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()

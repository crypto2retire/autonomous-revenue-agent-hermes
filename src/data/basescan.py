"""BaseScan API client for on-chain data."""

import httpx
from decimal import Decimal
from typing import Any

from src.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


class BaseScanClient:
    """Client for BaseScan API (free API key required).

    Provides: holder counts, transfers, token supply, contract data.
    Rate limit: 5 calls/sec with valid API key.
    """

    BASE_URL = "https://api.basescan.org/api"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or getattr(settings, 'basescan_api_key', None)
        if not self.api_key:
            logger.warning("basescan_api_key_not_set")
        self.client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=30.0,
        )

    async def _make_request(self, params: dict[str, Any]) -> dict[str, Any]:
        """Make authenticated request to BaseScan API."""
        params["apikey"] = self.api_key

        try:
            response = await self.client.get("", params=params)
            response.raise_for_status()
            data = response.json()

            if data.get("status") == "0" and data.get("message") == "NOTOK":
                logger.error("basescan_api_error", result=data.get("result"))
                raise Exception(f"BaseScan API error: {data.get('result')}")

            return data

        except httpx.HTTPStatusError as e:
            logger.error(
                "basescan_http_error",
                status=e.response.status_code,
                response=e.response.text,
            )
            raise
        except Exception as e:
            logger.error("basescan_request_failed", error=str(e))
            raise

    async def get_token_supply(self, contract_address: str) -> Decimal:
        """Get total token supply.

        Args:
            contract_address: Token contract address

        Returns:
            Token supply as Decimal
        """
        params = {
            "module": "stats",
            "action": "tokensupply",
            "contractaddress": contract_address,
        }

        data = await self._make_request(params)
        result = data.get("result", "0")

        # Result is in wei (without decimals), need to adjust
        return Decimal(str(result))

    async def get_token_holders(
        self,
        contract_address: str,
        page: int = 1,
        offset: int = 100,
    ) -> list[dict[str, Any]]:
        """Get list of token holders.

        Args:
            contract_address: Token contract address
            page: Page number
            offset: Results per page (max 100)

        Returns:
            List of holder addresses and balances.
        """
        params = {
            "module": "token",
            "action": "tokenholderlist",
            "contractaddress": contract_address,
            "page": page,
            "offset": offset,
        }

        data = await self._make_request(params)
        return data.get("result", [])

    async def get_holder_count(self, contract_address: str) -> int:
        """Get total number of token holders.

        Note: BaseScan doesn't have a direct endpoint for this.
        We estimate by fetching holders and checking if we hit the end.
        """
        total = 0
        page = 1

        while True:
            holders = await self.get_token_holders(contract_address, page=page, offset=100)
            if not holders:
                break

            total += len(holders)

            # Stop if we got less than max (no more pages)
            if len(holders) < 100:
                break

            page += 1

            # Safety limit - don't paginate forever
            if page > 50:
                logger.warning("holder_count_pagination_limit_reached", token=contract_address)
                break

        return total

    async def get_token_transfers(
        self,
        contract_address: str,
        start_block: int | None = None,
        end_block: int | None = None,
        page: int = 1,
        offset: int = 100,
    ) -> list[dict[str, Any]]:
        """Get token transfer events.

        Args:
            contract_address: Token contract address
            start_block: Starting block number
            end_block: Ending block number
            page: Page number
            offset: Results per page

        Returns:
            List of transfer events.
        """
        params = {
            "module": "logs",
            "action": "getLogs",
            "fromBlock": start_block or "0",
            "toBlock": end_block or "latest",
            "address": contract_address,
            "page": page,
            "offset": offset,
        }

        data = await self._make_request(params)
        return data.get("result", [])

    async def get_address_transactions(
        self,
        address: str,
        start_block: int | None = None,
        end_block: int | None = None,
        page: int = 1,
        offset: int = 100,
    ) -> list[dict[str, Any]]:
        """Get transactions for an address.

        Args:
            address: Wallet address
            start_block: Starting block number
            end_block: Ending block number
            page: Page number
            offset: Results per page

        Returns:
            List of transactions.
        """
        params = {
            "module": "account",
            "action": "txlist",
            "address": address,
            "startblock": start_block or 0,
            "endblock": end_block or 99999999,
            "page": page,
            "offset": offset,
            "sort": "desc",
        }

        data = await self._make_request(params)
        return data.get("result", [])

    async def get_token_balance(
        self,
        contract_address: str,
        wallet_address: str,
    ) -> Decimal:
        """Get token balance for a specific wallet.

        Args:
            contract_address: Token contract address
            wallet_address: Wallet to check

        Returns:
            Token balance.
        """
        params = {
            "module": "account",
            "action": "tokenbalance",
            "contractaddress": contract_address,
            "address": wallet_address,
            "tag": "latest",
        }

        data = await self._make_request(params)
        result = data.get("result", "0")
        return Decimal(str(result))

    async def get_contract_abi(self, contract_address: str) -> str | None:
        """Get contract ABI if verified.

        Args:
            contract_address: Contract address

        Returns:
            ABI JSON string or None if not verified.
        """
        params = {
            "module": "contract",
            "action": "getabi",
            "address": contract_address,
        }

        try:
            data = await self._make_request(params)
            return data.get("result")
        except Exception:
            return None

    async def get_contract_source(self, contract_address: str) -> dict[str, Any]:
        """Get contract source code if verified.

        Args:
            contract_address: Contract address

        Returns:
            Contract source data.
        """
        params = {
            "module": "contract",
            "action": "getsourcecode",
            "address": contract_address,
        }

        data = await self._make_request(params)
        return data.get("result", [{}])[0]

    async def get_latest_block(self) -> int:
        """Get latest block number."""
        params = {
            "module": "proxy",
            "action": "eth_blockNumber",
        }

        data = await self._make_request(params)
        result = data.get("result", "0x0")
        return int(result, 16)

    def extract_holder_metrics(
        self,
        holders: list[dict[str, Any]],
        total_supply: Decimal,
    ) -> dict[str, Any]:
        """Extract holder concentration metrics.

        Args:
            holders: List of holder data from get_token_holders
            total_supply: Total token supply

        Returns:
            Concentration metrics.
        """
        if not holders or total_supply == 0:
            return {}

        # Sort by balance descending
        sorted_holders = sorted(
            holders,
            key=lambda h: Decimal(str(h.get("TokenHolderQuantity", 0))),
            reverse=True,
        )

        # Calculate top holder percentages
        top_10_balance = sum(
            Decimal(str(h.get("TokenHolderQuantity", 0)))
            for h in sorted_holders[:10]
        )
        top_50_balance = sum(
            Decimal(str(h.get("TokenHolderQuantity", 0)))
            for h in sorted_holders[:50]
        )

        top_10_pct = (top_10_balance / total_supply) * 100
        top_50_pct = (top_50_balance / total_supply) * 100

        return {
            "total_holders": len(holders),
            "top_10_balance": float(top_10_balance),
            "top_10_pct": float(top_10_pct),
            "top_50_balance": float(top_50_balance),
            "top_50_pct": float(top_50_pct),
            "largest_holder_balance": float(
                Decimal(str(sorted_holders[0].get("TokenHolderQuantity", 0)))
                if sorted_holders else 0
            ),
            "largest_holder_pct": float(
                (Decimal(str(sorted_holders[0].get("TokenHolderQuantity", 0))) / total_supply * 100)
                if sorted_holders and total_supply > 0 else 0
            ),
        }

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()

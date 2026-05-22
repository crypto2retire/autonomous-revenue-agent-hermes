"""BaseScan API client for Base chain on-chain data."""

from typing import Any, Dict, List, Optional

import httpx

from config import get_settings

settings = get_settings()

BASESCAN_BASE = "https://api.basescan.org/api"


class BaseScanClient:
    """Async BaseScan API client."""

    def __init__(self):
        self.api_key = settings.basescan_api_key
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def _get(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Make a GET request to BaseScan API."""
        client = await self._get_client()
        req_params = dict(params)
        if self.api_key:
            req_params["apikey"] = self.api_key.get_secret_value()
        resp = await client.get(BASESCAN_BASE, params=req_params)
        resp.raise_for_status()
        return resp.json()

    # ── Account ────────────────────────────────────────────────────────

    async def get_balance(self, address: str, tag: str = "latest") -> str:
        """Get ETH balance for a single address."""
        data = await self._get({
            "module": "account",
            "action": "balance",
            "address": address,
            "tag": tag,
        })
        return data.get("result", "0")

    async def get_balances(self, addresses: List[str]) -> List[Dict[str, Any]]:
        """Get ETH balance for multiple addresses (max 20)."""
        data = await self._get({
            "module": "account",
            "action": "balancemulti",
            "address": ",".join(addresses),
            "tag": "latest",
        })
        return data.get("result", [])

    async def get_tx_list(
        self,
        address: str,
        start_block: int = 0,
        end_block: int = 99999999,
        page: int = 1,
        offset: int = 10,
        sort: str = "desc",
    ) -> List[Dict[str, Any]]:
        """Get normal transactions for an address."""
        data = await self._get({
            "module": "account",
            "action": "txlist",
            "address": address,
            "startblock": start_block,
            "endblock": end_block,
            "page": page,
            "offset": offset,
            "sort": sort,
        })
        return data.get("result", [])

    async def get_internal_tx_list(
        self,
        address: str,
        start_block: int = 0,
        end_block: int = 99999999,
        page: int = 1,
        offset: int = 10,
        sort: str = "desc",
    ) -> List[Dict[str, Any]]:
        """Get internal transactions for an address."""
        data = await self._get({
            "module": "account",
            "action": "txlistinternal",
            "address": address,
            "startblock": start_block,
            "endblock": end_block,
            "page": page,
            "offset": offset,
            "sort": sort,
        })
        return data.get("result", [])

    async def get_token_transfers(
        self,
        address: str,
        contract_address: Optional[str] = None,
        start_block: int = 0,
        end_block: int = 99999999,
        page: int = 1,
        offset: int = 10,
        sort: str = "desc",
    ) -> List[Dict[str, Any]]:
        """Get ERC-20 token transfers for an address."""
        params = {
            "module": "account",
            "action": "tokentx",
            "address": address,
            "startblock": start_block,
            "endblock": end_block,
            "page": page,
            "offset": offset,
            "sort": sort,
        }
        if contract_address:
            params["contractaddress"] = contract_address
        data = await self._get(params)
        result = data.get("result", [])
        # Handle string error responses (e.g., deprecated endpoint warnings)
        if isinstance(result, str):
            return []
        if isinstance(result, list):
            return [r for r in result if isinstance(r, dict)]
        return []

    async def get_nft_transfers(
        self,
        address: str,
        contract_address: Optional[str] = None,
        start_block: int = 0,
        end_block: int = 99999999,
        page: int = 1,
        offset: int = 10,
        sort: str = "desc",
    ) -> List[Dict[str, Any]]:
        """Get ERC-721/ERC-1155 token transfers for an address."""
        params = {
            "module": "account",
            "action": "tokennfttx",
            "address": address,
            "startblock": start_block,
            "endblock": end_block,
            "page": page,
            "offset": offset,
            "sort": sort,
        }
        if contract_address:
            params["contractaddress"] = contract_address
        data = await self._get(params)
        return data.get("result", [])

    # ── Contract ───────────────────────────────────────────────────────

    async def get_contract_abi(self, address: str) -> str:
        """Get contract ABI for a verified contract."""
        data = await self._get({
            "module": "contract",
            "action": "getabi",
            "address": address,
        })
        return data.get("result", "")

    async def get_contract_source(self, address: str) -> Dict[str, Any]:
        """Get contract source code for a verified contract."""
        data = await self._get({
            "module": "contract",
            "action": "getsourcecode",
            "address": address,
        })
        result = data.get("result", [])
        if isinstance(result, list) and len(result) > 0:
            return result[0]
        elif isinstance(result, dict):
            return result
        return {}

    async def get_contract_creation(self, addresses: List[str]) -> List[Dict[str, Any]]:
        """Get contract creation details."""
        data = await self._get({
            "module": "contract",
            "action": "getcontractcreation",
            "contractaddresses": ",".join(addresses),
        })
        result = data.get("result", [])
        # Handle string error responses
        if isinstance(result, str):
            return []
        if isinstance(result, list):
            return [r for r in result if isinstance(r, dict)]
        return []

    # ── Transaction ────────────────────────────────────────────────────

    async def get_tx_receipt_status(self, txhash: str) -> str:
        """Get transaction receipt status."""
        data = await self._get({
            "module": "transaction",
            "action": "gettxreceiptstatus",
            "txhash": txhash,
        })
        return data.get("result", {}).get("status", "")

    async def get_tx_status(self, txhash: str) -> Dict[str, Any]:
        """Get transaction execution status."""
        data = await self._get({
            "module": "transaction",
            "action": "getstatus",
            "txhash": txhash,
        })
        return data.get("result", {})

    # ── Block ──────────────────────────────────────────────────────────

    async def get_block_reward(self, block_no: int) -> Dict[str, Any]:
        """Get block reward by block number."""
        data = await self._get({
            "module": "block",
            "action": "getblockreward",
            "blockno": block_no,
        })
        return data.get("result", {})

    async def get_block_countdown(self, block_no: int) -> Dict[str, Any]:
        """Get estimated time until a block is mined."""
        data = await self._get({
            "module": "block",
            "action": "getblockcountdown",
            "blockno": block_no,
        })
        return data.get("result", {})

    # ── Stats ──────────────────────────────────────────────────────────

    async def get_eth_supply(self) -> str:
        """Get total ETH supply."""
        data = await self._get({
            "module": "stats",
            "action": "ethsupply",
        })
        return data.get("result", "0")

    async def get_eth_price(self) -> Dict[str, Any]:
        """Get current ETH price in USD and BTC."""
        data = await self._get({
            "module": "stats",
            "action": "ethprice",
        })
        return data.get("result", {})

    # ── Gas Tracker ────────────────────────────────────────────────────

    async def get_gas_oracle(self) -> Dict[str, Any]:
        """Get estimated gas prices (Safe, Proposed, Fast)."""
        data = await self._get({
            "module": "gastracker",
            "action": "gasoracle",
        })
        return data.get("result", {})

    async def get_gas_estimate(self, gas_price: int) -> str:
        """Get estimated confirmation time for a gas price."""
        data = await self._get({
            "module": "gastracker",
            "action": "gasestimate",
            "gasprice": gas_price,
        })
        return data.get("result", "")

    # ── Token ──────────────────────────────────────────────────────────

    async def get_token_info(self, contract_address: str) -> Dict[str, Any]:
        """Get token info (name, symbol, decimals, totalSupply) for an ERC-20."""
        data = await self._get({
            "module": "token",
            "action": "tokeninfo",
            "contractaddress": contract_address,
        })
        result = data.get("result", [])
        if isinstance(result, list) and len(result) > 0:
            return result[0]
        elif isinstance(result, dict):
            return result
        return {}

    async def get_token_holder_list(
        self,
        contract_address: str,
        page: int = 1,
        offset: int = 10,
    ) -> List[Dict[str, Any]]:
        """Get top token holders."""
        data = await self._get({
            "module": "token",
            "action": "tokenholderlist",
            "contractaddress": contract_address,
            "page": page,
            "offset": offset,
        })
        return data.get("result", [])

    # ── Cleanup ────────────────────────────────────────────────────────

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# Singleton
_basescan_client: Optional[BaseScanClient] = None


def get_basescan() -> BaseScanClient:
    global _basescan_client
    if _basescan_client is None:
        _basescan_client = BaseScanClient()
    return _basescan_client

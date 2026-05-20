"""DEX execution engine using Odos Protocol for optimal routing."""

import httpx
from decimal import Decimal
from typing import Optional, Any
from datetime import datetime

from web3 import Web3
from eth_account import Account

from src.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Token addresses on Base
USDC_ADDRESS = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
WETH_ADDRESS = "0x4200000000000000000000000000000000000006"


class OdosExecutor:
    """Execute trades via Odos Protocol DEX aggregator.

    Flow:
    1. Get quote from /sor/quote/v3
    2. Assemble transaction from /sor/assemble
    3. Sign and broadcast transaction
    4. Monitor for confirmation

    Requires Odos API key from enterprise.odos.xyz
    """

    def __init__(
        self,
        web3: Web3 = None,
        wallet_private_key: str = None,
        odos_api_key: str = None,
        chain_id: int = 8453,  # Base
    ):
        self.web3 = web3 or Web3(Web3.HTTPProvider(settings.base_rpc_url))
        self.wallet = Account.from_key(
            wallet_private_key or settings.base_wallet_private_key.get_secret_value()
        )
        self.odos_api_key = odos_api_key or getattr(settings, 'odos_api_key', '')
        self.chain_id = chain_id

        self.client = httpx.AsyncClient(
            base_url="https://enterprise-api.odos.xyz",
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.odos_api_key,
            },
            timeout=30.0,
        )

        self._nonce_cache: Optional[int] = None
        self._nonce_lock = None  # Would need asyncio.Lock in async context

    async def get_quote(
        self,
        input_token: str,
        output_token: str,
        amount_in: Decimal,
        input_decimals: int = 18,
        slippage: float = 0.5,
    ) -> dict[str, Any]:
        """Get optimal swap quote from Odos.

        Args:
            input_token: Token address to sell
            output_token: Token address to buy
            amount_in: Amount of input token (human readable)
            input_decimals: Decimals of input token
            slippage: Max slippage tolerance (0.5 = 0.5%)

        Returns:
            Quote response with pathId for assembly
        """
        # Convert to raw amount
        raw_amount = str(int(amount_in * (10 ** input_decimals)))

        request_body = {
            "chainId": self.chain_id,
            "inputTokens": [
                {
                    "tokenAddress": Web3.to_checksum_address(input_token),
                    "amount": raw_amount,
                }
            ],
            "outputTokens": [
                {
                    "tokenAddress": Web3.to_checksum_address(output_token),
                    "proportion": 1,
                }
            ],
            "userAddr": self.wallet.address,
            "slippageLimitPercent": slippage,
            "compact": True,
        }

        try:
            response = await self.client.post(
                "/sor/quote/v3",
                json=request_body,
            )
            response.raise_for_status()

            quote = response.json()

            logger.info(
                "odos_quote_received",
                input_token=input_token,
                output_token=output_token,
                amount_in=float(amount_in),
                path_id=quote.get("pathId"),
                gas_estimate=quote.get("gasEstimate"),
                price_impact=quote.get("priceImpact"),
            )

            return quote

        except httpx.HTTPStatusError as e:
            logger.error(
                "odos_quote_failed",
                status=e.response.status_code,
                error=e.response.text,
            )
            raise
        except Exception as e:
            logger.error("odos_quote_error", error=str(e))
            raise

    async def assemble_transaction(
        self,
        path_id: str,
        simulate: bool = True,
    ) -> dict[str, Any]:
        """Assemble executable transaction from quote pathId.

        Args:
            path_id: pathId from get_quote response
            simulate: Whether to simulate before returning

        Returns:
            Transaction object ready to sign and broadcast
        """
        request_body = {
            "userAddr": self.wallet.address,
            "pathId": path_id,
            "simulate": simulate,
        }

        try:
            response = await self.client.post(
                "/sor/assemble",
                json=request_body,
            )
            response.raise_for_status()

            assembled = response.json()
            tx = assembled.get("transaction", {})

            logger.info(
                "odos_assemble_complete",
                path_id=path_id,
                to=tx.get("to"),
                gas=tx.get("gas"),
                simulated=simulate,
                sim_success=assembled.get("simulation", {}).get("isSuccess") if simulate else None,
            )

            return assembled

        except httpx.HTTPStatusError as e:
            logger.error(
                "odos_assemble_failed",
                status=e.response.status_code,
                error=e.response.text,
            )
            raise
        except Exception as e:
            logger.error("odos_assemble_error", error=str(e))
            raise

    async def execute_swap(
        self,
        input_token: str,
        output_token: str,
        amount_in: Decimal,
        input_decimals: int = 18,
        slippage: float = 0.5,
        simulate: bool = True,
    ) -> dict[str, Any]:
        """Execute a complete swap: quote → assemble → sign → broadcast.

        Args:
            input_token: Token to sell
            output_token: Token to buy
            amount_in: Human-readable amount
            input_decimals: Token decimals
            slippage: Slippage tolerance
            simulate: Run simulation before execution

        Returns:
            Transaction receipt with hash, gas used, status
        """
        # Step 1: Get quote
        quote = await self.get_quote(
            input_token=input_token,
            output_token=output_token,
            amount_in=amount_in,
            input_decimals=input_decimals,
            slippage=slippage,
        )

        path_id = quote.get("pathId")
        if not path_id:
            raise ValueError("No pathId in quote response")

        # Step 2: Assemble transaction
        assembled = await self.assemble_transaction(path_id, simulate=simulate)
        tx_data = assembled.get("transaction", {})

        if not tx_data:
            raise ValueError("No transaction data in assembly response")

        # Step 3: Build and sign transaction
        nonce = await self._get_nonce()

        transaction = {
            "to": tx_data["to"],
            "from": self.wallet.address,
            "data": tx_data["data"],
            "chainId": self.chain_id,
            "gas": int(tx_data.get("gas", 500000)),
            "gasPrice": int(tx_data.get("gasPrice", self.web3.to_wei("1", "gwei"))),
            "value": int(tx_data.get("value", "0")),
            "nonce": nonce,
        }

        # Step 4: Sign
        signed_tx = self.web3.eth.account.sign_transaction(
            transaction,
            self.wallet.key,
        )

        # Step 5: Broadcast
        if settings.agent_mode == "paper":
            logger.info(
                "paper_trade_skipped_broadcast",
                input_token=input_token,
                output_token=output_token,
                amount=float(amount_in),
                tx_data=tx_data,
            )
            return {
                "status": "paper_trade",
                "input_token": input_token,
                "output_token": output_token,
                "amount_in": float(amount_in),
                "expected_out": quote.get("outAmounts", ["0"])[0],
                "gas_estimate": quote.get("gasEstimate"),
                "price_impact": quote.get("priceImpact"),
            }

        tx_hash = self.web3.eth.send_raw_transaction(signed_tx.rawTransaction)

        logger.info(
            "swap_broadcasted",
            tx_hash=tx_hash.hex(),
            input_token=input_token,
            output_token=output_token,
        )

        # Step 6: Wait for confirmation
        receipt = await self._wait_for_confirmation(tx_hash)

        return {
            "status": "confirmed" if receipt["status"] == 1 else "failed",
            "tx_hash": tx_hash.hex(),
            "block_number": receipt["blockNumber"],
            "gas_used": receipt["gasUsed"],
            "effective_gas_price": receipt.get("effectiveGasPrice"),
            "input_token": input_token,
            "output_token": output_token,
            "amount_in": float(amount_in),
        }

    async def approve_token(
        self,
        token_address: str,
        spender_address: str,
        amount: Optional[Decimal] = None,
    ) -> str:
        """Approve token spending for Odos router.

        Must be called before swapping ERC20 tokens.

        Args:
            token_address: Token to approve
            spender_address: Odos router address
            amount: Approval amount (max if None)

        Returns:
            Transaction hash
        """
        # Standard ERC20 approve ABI
        approve_abi = [
            {
                "constant": False,
                "inputs": [
                    {"name": "_spender", "type": "address"},
                    {"name": "_value", "type": "uint256"},
                ],
                "name": "approve",
                "outputs": [{"name": "", "type": "bool"}],
                "type": "function",
            }
        ]

        token_contract = self.web3.eth.contract(
            address=Web3.to_checksum_address(token_address),
            abi=approve_abi,
        )

        approval_amount = int(amount) if amount else 2**256 - 1

        nonce = await self._get_nonce()

        tx = token_contract.functions.approve(
            Web3.to_checksum_address(spender_address),
            approval_amount,
        ).build_transaction({
            "from": self.wallet.address,
            "nonce": nonce,
            "gas": 100000,
            "gasPrice": self.web3.to_wei("1", "gwei"),
            "chainId": self.chain_id,
        })

        signed_tx = self.web3.eth.account.sign_transaction(tx, self.wallet.key)
        tx_hash = self.web3.eth.send_raw_transaction(signed_tx.rawTransaction)

        logger.info(
            "token_approval_broadcasted",
            token=token_address,
            spender=spender_address,
            tx_hash=tx_hash.hex(),
        )

        receipt = await self._wait_for_confirmation(tx_hash)

        return tx_hash.hex()

    async def _get_nonce(self) -> int:
        """Get next nonce for wallet."""
        if self._nonce_cache is None:
            self._nonce_cache = self.web3.eth.get_transaction_count(
                self.wallet.address,
                "pending",
            )
        else:
            self._nonce_cache += 1

        return self._nonce_cache

    async def _wait_for_confirmation(
        self,
        tx_hash,
        timeout: int = 120,
        poll_interval: float = 2.0,
    ) -> dict:
        """Wait for transaction confirmation."""
        import asyncio

        start = datetime.utcnow()

        while True:
            try:
                receipt = self.web3.eth.get_transaction_receipt(tx_hash)
                if receipt:
                    logger.info(
                        "transaction_confirmed",
                        tx_hash=tx_hash.hex(),
                        block=receipt["blockNumber"],
                        gas_used=receipt["gasUsed"],
                        status=receipt["status"],
                    )
                    return receipt
            except Exception:
                pass

            await asyncio.sleep(poll_interval)

            if (datetime.utcnow() - start).total_seconds() > timeout:
                raise TimeoutError(f"Transaction {tx_hash.hex()} not confirmed within {timeout}s")

    async def get_token_balance(
        self,
        token_address: str,
        decimals: int = 18,
    ) -> Decimal:
        """Get token balance for wallet."""
        if token_address.lower() == "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee":
            # ETH
            balance_wei = self.web3.eth.get_balance(self.wallet.address)
            return Decimal(balance_wei) / Decimal(10**18)

        # ERC20
        balance_abi = [
            {
                "constant": True,
                "inputs": [{"name": "_owner", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "balance", "type": "uint256"}],
                "type": "function",
            }
        ]

        contract = self.web3.eth.contract(
            address=Web3.to_checksum_address(token_address),
            abi=balance_abi,
        )

        balance = contract.functions.balanceOf(self.wallet.address).call()
        return Decimal(balance) / Decimal(10**decimals)

    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()

"""Solana wallet client for signing and sending transactions."""

import base64
import json
from typing import Optional, Dict, Any

import httpx
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from solders.pubkey import Pubkey


class SolanaClient:
    """Solana RPC client with wallet signing."""

    def __init__(self, rpc_url: str, private_key: Optional[str] = None):
        self.http = httpx.AsyncClient(timeout=60.0)
        self.rpc_url = rpc_url
        self._keypair: Optional[Keypair] = None
        self._pubkey: Optional[Pubkey] = None

        if private_key:
            try:
                pk = private_key.strip()
                if pk.startswith("["):
                    secret_bytes = json.loads(pk)
                    self._keypair = Keypair.from_bytes(bytes(secret_bytes))
                else:
                    self._keypair = Keypair.from_base58_string(pk)
                self._pubkey = self._keypair.pubkey()
            except Exception as e:
                raise RuntimeError(f"Failed to load Solana wallet: {e}")

    @property
    def is_loaded(self) -> bool:
        return self._keypair is not None

    @property
    def pubkey(self) -> Optional[str]:
        return str(self._pubkey) if self._pubkey else None

    async def close(self):
        await self.http.aclose()

    async def _rpc_call(self, method: str, params: list) -> Dict[str, Any]:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params,
        }
        resp = await self.http.post(self.rpc_url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"Solana RPC error: {data['error']}")
        return data["result"]

    async def get_balance(self) -> int:
        if not self._pubkey:
            raise RuntimeError("Solana wallet not loaded")
        result = await self._rpc_call("getBalance", [str(self._pubkey)])
        return result["value"]

    async def get_latest_blockhash(self) -> str:
        result = await self._rpc_call("getLatestBlockhash", [{"commitment": "finalized"}])
        return result["value"]["blockhash"]

    async def get_fee_estimate(self) -> int:
        """Get recent fee estimate in lamports."""
        try:
            result = await self._rpc_call("getRecentBlockhash", [{"commitment": "processed"}])
            # Return a conservative estimate: 5000 lamports (0.000005 SOL)
            return 5000
        except Exception:
            return 5_000_000  # Fallback to 0.005 SOL

    async def send_transaction(self, signed_tx: VersionedTransaction) -> str:
        serialized = bytes(signed_tx)
        encoded = base64.b64encode(serialized).decode("utf-8")
        result = await self._rpc_call("sendTransaction", [
            encoded,
            {
                "encoding": "base64",
                "preflightCommitment": "confirmed",
                "maxRetries": 3,
            }
        ])
        return result

    async def confirm_transaction(self, signature: str, timeout_sec: int = 60) -> Dict[str, Any]:
        import asyncio
        deadline = asyncio.get_event_loop().time() + timeout_sec
        while asyncio.get_event_loop().time() < deadline:
            result = await self._rpc_call("getSignatureStatuses", [[signature]])
            status = result["value"][0]
            if status:
                if status.get("confirmationStatus") in ("confirmed", "finalized"):
                    return status
                if status.get("err"):
                    raise RuntimeError(f"Transaction failed: {status['err']}")
            await asyncio.sleep(2)
        raise RuntimeError(f"Transaction confirmation timeout: {signature}")

    def sign_jupiter_swap(self, swap_transaction_b64: str) -> VersionedTransaction:
        if not self._keypair:
            raise RuntimeError("Solana wallet not loaded")
        tx_bytes = base64.b64decode(swap_transaction_b64)
        tx = VersionedTransaction.from_bytes(tx_bytes)
        signed = VersionedTransaction(tx.message, [self._keypair])
        return signed


# Singleton helper for consumers that want module-level access
def get_solana_client() -> SolanaClient:
    from config import get_settings
    s = get_settings()
    return SolanaClient(
        rpc_url=s.solana_rpc,
        private_key=s.solana_wallet_private_key.get_secret_value() if s.solana_wallet_private_key else None,
    )

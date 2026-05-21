"""Wallet manager for dynamic wallet switching via dashboard/API."""

import json
import os
from decimal import Decimal
from typing import Optional
from datetime import datetime

from web3 import Web3
from eth_account import Account

from src.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

WALLET_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "../../config/wallet.json")


class WalletManager:
    """Manages wallet configuration with hot-reload capability.
    
    Allows changing wallet private key without restarting the agent.
    Reads from file, falls back to env var, supports runtime updates.
    """

    def __init__(self, web3: Web3 = None):
        self.web3 = web3 or Web3(Web3.HTTPProvider(settings.base_rpc_url))
        self._wallet: Optional[Account] = None
        self._config_file = WALLET_CONFIG_PATH
        self._load_wallet()

    def _load_wallet(self):
        """Load wallet from config file or env var."""
        # Try config file first (allows runtime updates)
        if os.path.exists(self._config_file):
            try:
                with open(self._config_file, "r") as f:
                    config = json.load(f)
                
                private_key = config.get("private_key", "")
                if private_key:
                    self._wallet = Account.from_key(private_key)
                    logger.info(
                        "wallet_loaded_from_config",
                        address=self._wallet.address,
                        config_file=self._config_file,
                    )
                    return
            except Exception as e:
                logger.error("wallet_config_load_failed", error=str(e))
        
        # Fall back to env var
        try:
            private_key = settings.base_wallet_private_key.get_secret_value()
            if private_key:
                self._wallet = Account.from_key(private_key)
                logger.info(
                    "wallet_loaded_from_env",
                    address=self._wallet.address,
                )
                return
        except Exception as e:
            logger.error("wallet_env_load_failed", error=str(e))
        
        logger.warning("no_wallet_configured")

    def get_wallet(self) -> Optional[Account]:
        """Get current wallet."""
        return self._wallet

    def get_address(self) -> Optional[str]:
        """Get wallet address."""
        return self._wallet.address if self._wallet else None

    def is_configured(self) -> bool:
        """Check if wallet is configured."""
        return self._wallet is not None

    def update_wallet(self, private_key: str, save_to_file: bool = True) -> dict:
        """Update wallet with new private key.
        
        Args:
            private_key: New private key (with or without 0x prefix)
            save_to_file: Whether to persist to config file
            
        Returns:
            Status dict with new address
        """
        try:
            # Normalize private key
            if not private_key.startswith("0x"):
                private_key = "0x" + private_key
            
            # Validate by creating account
            new_wallet = Account.from_key(private_key)
            old_address = self._wallet.address if self._wallet else None
            
            self._wallet = new_wallet
            
            if save_to_file:
                self._save_config(private_key)
            
            logger.info(
                "wallet_updated",
                old_address=old_address,
                new_address=new_wallet.address,
                saved=save_to_file,
            )
            
            return {
                "success": True,
                "address": new_wallet.address,
                "previous_address": old_address,
                "message": f"Wallet updated to {new_wallet.address}",
            }
            
        except Exception as e:
            logger.error("wallet_update_failed", error=str(e))
            return {
                "success": False,
                "error": str(e),
                "message": "Invalid private key",
            }

    def _save_config(self, private_key: str):
        """Save wallet config to file."""
        os.makedirs(os.path.dirname(self._config_file), exist_ok=True)
        
        config = {
            "private_key": private_key,
            "address": self._wallet.address,
            "updated_at": datetime.utcnow().isoformat(),
        }
        
        with open(self._config_file, "w") as f:
            json.dump(config, f, indent=2)
        
        # Secure file permissions (owner read/write only)
        os.chmod(self._config_file, 0o600)
        
        logger.info("wallet_config_saved", file=self._config_file)

    def get_balance(self, token_address: Optional[str] = None) -> Decimal:
        """Get wallet balance.
        
        Args:
            token_address: Token address (None for ETH)
            
        Returns:
            Balance in human-readable format
        """
        if not self._wallet:
            return Decimal("0")
        
        try:
            if token_address is None or token_address.lower() == "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee":
                # ETH balance
                balance_wei = self.web3.eth.get_balance(self._wallet.address)
                return Decimal(balance_wei) / Decimal(10**18)
            else:
                # ERC20 balance
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
                
                balance = contract.functions.balanceOf(self._wallet.address).call()
                # Assume 18 decimals for now
                return Decimal(balance) / Decimal(10**18)
                
        except Exception as e:
            logger.error("balance_check_failed", error=str(e))
            return Decimal("0")

    def reload_wallet(self):
        """Reload wallet from config file."""
        logger.info("wallet_reload_requested")
        self._load_wallet()

    def to_dict(self) -> dict:
        """Get wallet info for dashboard display."""
        if not self._wallet:
            return {
                "configured": False,
                "address": None,
                "eth_balance": "0",
            }
        
        return {
            "configured": True,
            "address": self._wallet.address,
            "eth_balance": str(self.get_balance()),
        }

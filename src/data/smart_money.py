"""Smart money wallet labeling and tracking.

Uses free/community data sources to identify smart money wallets:
- Dune Analytics (free tier: 2,500 credits/month)
- Nansen (free tier: 1,000 trial credits)
- Manual curation of known smart money wallets
- Heuristic-based labeling (profit history, trade frequency, timing)
"""

import httpx
from decimal import Decimal
from datetime import datetime, timedelta
from typing import Any, Optional
from collections import defaultdict

from src.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


class SmartMoneyTracker:
    """Tracks and labels smart money wallets for early signal detection.

    Labels wallets based on:
    1. Known smart money addresses (curated list)
    2. Profit history (realized gains)
    3. Trade timing (buying before pumps)
    4. Win rate consistency
    """

    # Known smart money / influencer wallets on Base
    # These are publicly known addresses of successful traders/VCs
    KNOWN_SMART_MONEY = {
        # Add known addresses here as you discover them
        # Format: "0x...": {"label": "whale_name", "type": "vc|whale|influencer"}
    }

    def __init__(
        self,
        dune_api_key: Optional[str] = None,
        nansen_api_key: Optional[str] = None,
    ):
        self.dune_api_key = dune_api_key or getattr(settings, 'dune_api_key', None)
        self.nansen_api_key = nansen_api_key or getattr(settings, 'nansen_api_key', None)
        
        self.dune_client = None
        self.nansen_client = None
        
        if self.dune_api_key:
            self.dune_client = httpx.AsyncClient(
                base_url="https://api.dune.com/api/v1",
                headers={"X-Dune-API-Key": self.dune_api_key},
                timeout=60.0,
            )
        
        if self.nansen_api_key:
            self.nansen_client = httpx.AsyncClient(
                base_url="https://api.nansen.ai/v1",
                headers={"X-API-Key": self.nansen_api_key},
                timeout=60.0,
            )
        
        # Local tracking
        self._wallet_scores: dict[str, dict] = defaultdict(lambda: {
            "trades": 0,
            "wins": 0,
            "total_pnl": Decimal("0"),
            "labels": set(),
            "first_seen": datetime.utcnow(),
            "last_trade": None,
        })
        
        self._token_smart_flows: dict[str, dict] = defaultdict(lambda: {
            "inflows": Decimal("0"),
            "outflows": Decimal("0"),
            "unique_buyers": set(),
            "unique_sellers": set(),
            "last_updated": datetime.utcnow(),
        })

    async def label_wallet(self, wallet_address: str) -> dict[str, Any]:
        """Get labels and score for a wallet.
        
        Returns smart money classification with confidence.
        """
        wallet_address = wallet_address.lower()
        
        # Check known addresses
        if wallet_address in self.KNOWN_SMART_MONEY:
            known = self.KNOWN_SMART_MONEY[wallet_address]
            return {
                "address": wallet_address,
                "is_smart_money": True,
                "confidence": 0.95,
                "labels": [known["label"], known["type"]],
                "source": "curated",
            }
        
        # Check cached scores
        if wallet_address in self._wallet_scores:
            score = self._wallet_scores[wallet_address]
            win_rate = score["wins"] / score["trades"] if score["trades"] > 0 else 0
            
            # Heuristic scoring
            is_smart = (
                win_rate > 0.6 and score["trades"] >= 5
            ) or score["total_pnl"] > Decimal("10000")
            
            return {
                "address": wallet_address,
                "is_smart_money": is_smart,
                "confidence": min(win_rate * 0.8 + 0.1, 0.9) if is_smart else 0.3,
                "labels": list(score["labels"]),
                "win_rate": win_rate,
                "total_pnl": float(score["total_pnl"]),
                "trade_count": score["trades"],
                "source": "heuristic",
            }
        
        # Try Dune if available
        if self.dune_client:
            try:
                dune_labels = await self._query_dune_labels(wallet_address)
                if dune_labels:
                    return dune_labels
            except Exception as e:
                logger.debug("dune_label_query_failed", error=str(e))
        
        # Try Nansen if available
        if self.nansen_client:
            try:
                nansen_labels = await self._query_nansen_labels(wallet_address)
                if nansen_labels:
                    return nansen_labels
            except Exception as e:
                logger.debug("nansen_label_query_failed", error=str(e))
        
        # Unknown wallet
        return {
            "address": wallet_address,
            "is_smart_money": False,
            "confidence": 0.0,
            "labels": [],
            "source": "unknown",
        }

    async def analyze_token_flows(
        self,
        token_address: str,
        transfers: list[dict],
    ) -> dict[str, Any]:
        """Analyze transfers to identify smart money flows.
        
        Args:
            token_address: Token being analyzed
            transfers: List of transfer events from BaseScan
            
        Returns:
            Smart money flow summary
        """
        token_address = token_address.lower()
        flows = self._token_smart_flows[token_address]
        
        smart_buyers = set()
        smart_sellers = set()
        smart_inflow = Decimal("0")
        smart_outflow = Decimal("0")
        
        for transfer in transfers:
            from_addr = transfer.get("from", "").lower()
            to_addr = transfer.get("to", "").lower()
            value = Decimal(str(transfer.get("value", 0)))
            
            # Label both sides
            from_label = await self.label_wallet(from_addr)
            to_label = await self.label_wallet(to_addr)
            
            # Track smart money buying
            if to_label["is_smart_money"] and value > 0:
                smart_buyers.add(to_addr)
                smart_inflow += value
                
                # Update wallet score
                self._wallet_scores[to_addr]["trades"] += 1
                self._wallet_scores[to_addr]["last_trade"] = datetime.utcnow()
            
            # Track smart money selling
            if from_label["is_smart_money"] and value > 0:
                smart_sellers.add(from_addr)
                smart_outflow += value
                
                self._wallet_scores[from_addr]["trades"] += 1
                self._wallet_scores[from_addr]["last_trade"] = datetime.utcnow()
        
        # Update token flows
        flows["inflows"] += smart_inflow
        flows["outflows"] += smart_outflow
        flows["unique_buyers"].update(smart_buyers)
        flows["unique_sellers"].update(smart_sellers)
        flows["last_updated"] = datetime.utcnow()
        
        net_flow = smart_inflow - smart_outflow
        
        return {
            "token_address": token_address,
            "smart_inflow_24h": float(smart_inflow),
            "smart_outflow_24h": float(smart_outflow),
            "smart_net_flow": float(net_flow),
            "smart_buyers": len(smart_buyers),
            "smart_sellers": len(smart_sellers),
            "smart_buyer_addresses": list(smart_buyers)[:10],  # Limit
            "smart_seller_addresses": list(smart_sellers)[:10],
            "flow_signal": "accumulating" if net_flow > 0 else "distributing" if net_flow < 0 else "neutral",
            "confidence": min(len(smart_buyers) * 0.1 + 0.3, 0.9),
        }

    async def get_smart_money_signals(self, token_address: str) -> dict[str, Any]:
        """Get aggregated smart money signals for a token.
        
        Returns buy/sell pressure from labeled wallets.
        """
        token_address = token_address.lower()
        flows = self._token_smart_flows.get(token_address)
        
        if not flows:
            return {
                "token_address": token_address,
                "signal": "no_data",
                "confidence": 0,
                "smart_buyers": 0,
                "smart_sellers": 0,
            }
        
        net_flow = flows["inflows"] - flows["outflows"]
        total_flow = flows["inflows"] + flows["outflows"]
        
        if total_flow == 0:
            signal = "neutral"
            confidence = 0
        else:
            flow_ratio = net_flow / total_flow
            
            if flow_ratio > 0.3:
                signal = "strong_buy"
                confidence = min(abs(flow_ratio) * 2, 0.95)
            elif flow_ratio > 0.1:
                signal = "buy"
                confidence = min(abs(flow_ratio) * 3, 0.8)
            elif flow_ratio < -0.3:
                signal = "strong_sell"
                confidence = min(abs(flow_ratio) * 2, 0.95)
            elif flow_ratio < -0.1:
                signal = "sell"
                confidence = min(abs(flow_ratio) * 3, 0.8)
            else:
                signal = "neutral"
                confidence = 0.5
        
        return {
            "token_address": token_address,
            "signal": signal,
            "confidence": float(confidence),
            "smart_inflow": float(flows["inflows"]),
            "smart_outflow": float(flows["outflows"]),
            "smart_net_flow": float(net_flow),
            "unique_smart_buyers": len(flows["unique_buyers"]),
            "unique_smart_sellers": len(flows["unique_sellers"]),
            "last_updated": flows["last_updated"].isoformat(),
        }

    async def _query_dune_labels(self, wallet_address: str) -> Optional[dict]:
        """Query Dune for wallet labels.
        
        Uses Dune's free tier (2,500 credits/month).
        """
        if not self.dune_client:
            return None
        
        # Dune doesn't have a direct wallet label API
        # You'd need to create a query that checks against known labels
        # For now, this is a placeholder
        
        logger.debug("dune_label_query_not_implemented")
        return None

    async def _query_nansen_labels(self, wallet_address: str) -> Optional[dict]:
        """Query Nansen for wallet labels.
        
        Free tier: 1,000 trial credits (10x cost of Pro).
        Label lookup: 100 credits (Pro) = 1,000 credits (Free).
        """
        if not self.nansen_client:
            return None
        
        try:
            response = await self.nansen_client.get(
                f"/profiler/address/current-balances",
                params={"address": wallet_address},
            )
            
            if response.status_code == 200:
                data = response.json()
                
                # Check if wallet has significant holdings
                total_value = sum(
                    b.get("usd_value", 0) 
                    for b in data.get("balances", [])
                )
                
                if total_value > 100000:  # $100k+
                    return {
                        "address": wallet_address,
                        "is_smart_money": True,
                        "confidence": 0.6,
                        "labels": ["high_value"],
                        "portfolio_value": total_value,
                        "source": "nansen",
                    }
            
            return None
            
        except Exception as e:
            logger.debug("nansen_query_error", error=str(e))
            return None

    def add_known_wallet(self, address: str, label: str, wallet_type: str = "whale"):
        """Add a known smart money wallet to the curated list."""
        self.KNOWN_SMART_MONEY[address.lower()] = {
            "label": label,
            "type": wallet_type,
        }
        logger.info("known_wallet_added", address=address, label=label)

    def update_wallet_performance(
        self,
        wallet_address: str,
        trade_pnl: Decimal,
        was_win: bool,
    ):
        """Update a wallet's performance score after a trade.
        
        Call this when you detect a wallet has closed a position.
        """
        wallet_address = wallet_address.lower()
        score = self._wallet_scores[wallet_address]
        
        score["trades"] += 1
        score["total_pnl"] += trade_pnl
        
        if was_win:
            score["wins"] += 1
        
        # Auto-label based on performance
        win_rate = score["wins"] / score["trades"]
        
        if score["trades"] >= 10 and win_rate > 0.7:
            score["labels"].add("consistent_winner")
        elif score["total_pnl"] > Decimal("50000"):
            score["labels"].add("high_pnl")
        elif score["trades"] >= 5 and win_rate > 0.6:
            score["labels"].add("profitable")
        
        logger.debug(
            "wallet_performance_updated",
            wallet=wallet_address,
            trades=score["trades"],
            win_rate=win_rate,
            pnl=float(score["total_pnl"]),
        )

    async def close(self):
        """Close API clients."""
        if self.dune_client:
            await self.dune_client.aclose()
        if self.nansen_client:
            await self.nansen_client.aclose()

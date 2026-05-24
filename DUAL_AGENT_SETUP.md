# Dual-Agent Architecture Setup

## Overview

The crypto trading agent now runs **two independent agents** plus a **wallet monitor**:

| Component | File | Purpose | Check Interval |
|-----------|------|---------|----------------|
| **Buy Agent** | `scanner.py` | Discovers tokens, analyzes with AI, executes buys | 5 min |
| **Sell Agent** | `position_manager.py` | Monitors positions, enforces exits, recycles capital | 30 sec |
| **Wallet Monitor** | `wallet_monitor.py` | Tracks balances, computes capital allocation | 60 sec |

---

## Sell Agent Rules (Execution Order)

The Sell Agent evaluates every open position every 30 seconds. Rules are checked in priority order:

| Priority | Rule | Threshold | Action |
|----------|------|-----------|--------|
| 1 | **Emergency Stop Loss** | -30% | Sell 100% |
| 2 | **Standard Stop Loss** | -15% | Sell 100% |
| 3 | **Profit Target 2** | +50% | Sell 80% (if not already hit) |
| 4 | **Profit Target 1** | +25% | Sell 60% (if not already hit) |
| 5 | **Trailing Stop** | -10% from peak | Sell 100% (only if up >5% from entry) |
| 6 | **Max Hold Time** | 7 days | Sell 100% |
| 7 | **Capital Recycle** | -20% + low capital | Sell 100% (only if free capital < 20%) |

---

## Capital Allocation

The Wallet Monitor computes:

- **Total Portfolio Value** = Liquid + Position Value
- **Deployed %** = Position Value / Total Portfolio
- **Free %** = 100% - Deployed %
- **Can Buy?** = Free % >= 20%
- **Should Recycle?** = Free % < 20% AND positions exist

The Buy Agent uses this to:
1. Know how much it can invest (`max_new_position_size`)
2. Avoid buying when capital is fully deployed

The Sell Agent uses this to:
1. Sell underperformers when capital is needed
2. Free up SOL for new opportunities

---

## New Database Fields

The `trades` table now tracks:

| Field | Purpose |
|-------|---------|
| `highest_price_seen` | Peak price since entry (for trailing stop) |
| `trailing_stop_price` | Current trailing stop level |
| `profit_target_1_hit` | Whether +25% target was reached |
| `profit_target_2_hit` | Whether +50% target was reached |
| `amount_sold_pct` | How much of position already sold |

---

## Configuration

Add to `.env`:

```env
# Sell Agent
SELL_AGENT_ENABLED=true
SELL_CHECK_INTERVAL_SECONDS=30
TRAILING_STOP_ENABLED=true
TRAILING_STOP_DISTANCE_PCT=0.10
PROFIT_TARGET_1_PCT=0.25
PROFIT_TARGET_1_SELL_PCT=0.60
PROFIT_TARGET_2_PCT=0.50
PROFIT_TARGET_2_SELL_PCT=0.80
MAX_HOLD_HOURS=168
UNDERPREFORM_SELL_THRESHOLD_PCT=-0.20
CAPITAL_RECYCLE_ENABLED=true
MIN_FREE_CAPITAL_PCT=0.20
EMERGENCY_STOP_LOSS_PCT=0.30
```

---

## Files Changed

| File | Change |
|------|--------|
| `config.py` | Added sell agent + capital management settings |
| `models.py` | Added position tracking fields to Trade model |
| `database.py` | Added `get_open_positions()`, `get_portfolio_summary()`, `update_trade_highest_price()`, `update_trade_profit_target()` |
| `executor.py` | Deprecated old `check_positions()`, added proper sell execution |
| `main.py` | Now runs scanner + position_manager + wallet_monitor + server |
| `position_manager.py` | **NEW** — Sell Agent |
| `wallet_monitor.py` | **NEW** — Capital allocation tracker |

---

## Testing

Run the test suite:

```bash
cd ~/autonomous-revenue-agent-hermes
python3 -c "
import asyncio
from position_manager import PositionManager
from database import DB
from models import TradeStatus

async def test():
    pm = PositionManager()
    
    # Test stop loss
    trades = await DB.get_trades(status=TradeStatus.EXECUTED, side='buy')
    for trade in trades:
        result = await pm.evaluate_position(trade)
        if result['should_sell']:
            print(f'SELL {trade.symbol}: {result[\"reason\"]} at {result[\"pnl_pct\"]:.1f}%')
    
    await pm.close()

asyncio.run(test())
"
```

---

## Deployment

```bash
# Start the agent
python3 main.py

# The dashboard is available at http://localhost:8000
# Tabs: Watchlist, Market, Deployers, Trades, Positions, Performance, Logs, Settings
```

All four components run concurrently:
- Scanner (buy agent) finds opportunities
- Position Manager (sell agent) protects capital
- Wallet Monitor tracks allocation
- Dashboard shows everything

# Crypto Trading Agent Status

## Current Issues

### All Buys Failing
**Base chain (Odos):** Rate limited — free tier is 1 RPS, scanner triggers multiple buys quickly
**Solana (Jupiter):** Two issues:
1. `Could not fetch SOL price` — Jupiter Price API v3 returns null for some tokens
2. `Insufficient SOL balance` — Wallet has 0.016 SOL, needs ~0.06 for $5 trade

### Root Cause: AGENT_MODE Mismatch
- `fly.toml` sets `AGENT_MODE = "paper"`
- But `fly secrets` has `AGENT_MODE = "live"` (overrides fly.toml)
- `settings.is_paper` returns False, so live trading path is taken
- `live_trading_enabled` in DB is now False (I set it)

### Current Settings
- `live_trading_enabled`: False (in DB)
- `AGENT_MODE`: live (from fly secrets, overrides fly.toml)
- Effective mode: paper (because live_trading_enabled is False)

## Fixes Applied
1. Jupiter Price API migrated from v2 to v3
2. Trade sizes reduced: min $1, max $50, default $5
3. `live_trading_enabled` set to False in DB
4. `fly.toml` changed to paper mode (but overridden by secret)

## Next Steps
1. Remove `AGENT_MODE` from fly secrets so fly.toml controls it
2. Or set `AGENT_MODE=paper` in fly secrets
3. Fund Solana wallet with SOL for live trading
4. Get Odos API key for higher rate limits

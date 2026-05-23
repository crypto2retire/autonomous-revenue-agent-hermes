# Trade Size Configuration Changes

## New Settings (config.py)
- `min_trade_size_usd`: 1.0 (was 10.0)
- `max_trade_size_usd`: 50.0 (was 1000.0)
- `default_trade_size_usd`: 5.0 (NEW)
- `max_daily_loss_usd`: 50.0 (was 100.0)
- `stop_loss_pct`: 0.15 (was 0.05)
- `take_profit_pct`: 0.25 (was 0.10)
- `pumpfun_min_trade_usd`: 1.0 (NEW)
- `pumpfun_max_trade_usd`: 10.0 (NEW)
- `pumpfun_scan_interval_seconds`: 60 (NEW)

## Current Trade Status
- All trades now using $5.00 instead of $10.00
- Still failing due to:
  1. Solana trades: Insufficient SOL balance (0.016 SOL, need ~0.06 for $5 trade)
  2. Base trades: Odos API rate limiting (1 RPS free tier)

## Next Steps
1. Fund Solana wallet with more SOL
2. Consider getting Odos API key for higher rate limits
3. Or switch to paper mode for testing

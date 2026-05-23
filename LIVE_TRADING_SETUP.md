# Live Trading Setup Requirements

## Current Status
- `AGENT_MODE`: live (in fly.toml)
- `live_trading_enabled`: True (in database)
- App is deployed and healthy

## Why Trades Are Still Failing

### Base Chain (Odos)
- **Error**: `Odos API rate limited after 3 retries`
- **Cause**: Free tier is 1 request per second. Scanner triggers multiple buys quickly.
- **Fix Options**:
  1. Get Odos API key for higher rate limits (enterprise tier)
  2. Increase delay between trades in scanner
  3. Skip Base chain trading for now

### Solana (Jupiter)
- **Error**: `Could not fetch SOL price for trade sizing`
- **Cause**: Jupiter Price API v3 returns null intermittently
- **Fix Applied**: Added CoinGecko fallback, but still failing
- **Additional Error**: `Insufficient SOL balance` - wallet has 0.016 SOL

## Required Actions to Enable Live Trading

### 1. Fund Solana Wallet
Wallet address: `DFiddee8CSaVWrHLeu2aaPJRs2qhiqmzgpmjb1im2Avn`
Need: At least 0.5 SOL for $5 trades with fees

### 2. Fix Solana Price API
The Jupiter Price API is unreliable. Options:
- Use CoinGecko exclusively for SOL price
- Use a dedicated RPC node (Helius/QuickNode) with better reliability
- Cache SOL price and refresh every 30 seconds

### 3. Fix Base Chain Rate Limiting
Options:
- Get Odos API key (paid tier)
- Add trade queue with 2-second delays between executions
- Disable Base trading temporarily

## Recommended Immediate Fix
Disable Base trading and focus on Solana only until:
1. Wallet is funded
2. Price API is reliable
3. Rate limits are resolved

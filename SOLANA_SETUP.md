# Solana-Only Trading Setup

## Why Solana Only?
- Lower transaction fees ($0.00025 vs $0.50+ on Base)
- Faster finality (400ms vs 2s on Base)
- Better for short-term/momentum trading
- Jupiter aggregator provides best execution

## Price Data Stack (Priority Order)

### 1. Birdeye API (Recommended - $199/month Premium)
- **Best for**: Real-time token prices, WebSocket streaming
- **Rate limit**: 50 RPS (Premium)
- **Features**: Tick-level trades, OHLCV, wallet portfolio, new listings
- **Signup**: https://birdeye.so/data-api/pricing
- **Set secret**: `fly secrets set BIRDEYE_API_KEY=your_key -a crypto-agent-serene-surf-3922`

### 2. Jupiter Price API v3 (Free)
- **Best for**: SOL price, major tokens
- **Rate limit**: Unknown (free tier)
- **Limitations**: Returns null for some tokens, not as reliable
- **Already configured** in `solana_price_client.py`

### 3. DexScreener API (Free)
- **Best for**: Pair data, liquidity info
- **Rate limit**: 300 req/min for pairs
- **Limitations**: No WebSocket, REST only
- **Already configured** in `solana_price_client.py`

### 4. CoinGecko (Free tier)
- **Best for**: Backup price source
- **Rate limit**: 10-30 calls/min (free)
- **Limitations**: Delayed data, not all tokens
- **Already configured** in `solana_price_client.py`

## Recommended Setup for Short-Term Trading

### Option A: Start Free (Current)
- Jupiter + DexScreener + CoinGecko fallback
- Will work for most tokens but may miss some
- Good for testing

### Option B: Birdeye Premium ($199/month)
- Real-time WebSocket prices
- Tick-level trade data
- Most accurate for momentum trading
- 50 RPS rate limit

### Option C: Helius Business ($499/month)
- LaserStream gRPC for real-time data
- Dedicated RPC node option ($2900/month)
- Best for high-frequency trading
- Includes transaction landing (Sender)

## Required Secrets

```bash
# Already set (verify)
fly secrets list -a crypto-agent-serene-surf-3922

# Add Birdeye API key (recommended)
fly secrets set BIRDEYE_API_KEY=your_key -a crypto-agent-serene-surf-3922

# Add Helius API key (optional, for better RPC)
fly secrets set HELIUS_API_KEY=your_key -a crypto-agent-serene-surf-3922

# Add Jupiter API key (optional, for priority quotes)
fly secrets set JUPITER_API_KEY=your_key -a crypto-agent-serene-surf-3922
```

## Wallet Funding

Your Solana wallet: `DFiddee8CSaVWrHLeu2aaPJRs2qhiqmzgpmjb1im2Avn`

Need: At least 0.5 SOL for $5 trades with fees
Current: 0.016 SOL (INSUFFICIENT)

Fund from:
- Coinbase -> Solana withdrawal
- Phantom wallet -> Buy SOL
- Jupiter -> Swap USDC to SOL

## Next Steps

1. Fund wallet with 0.5+ SOL
2. Add Birdeye API key for best price accuracy
3. Monitor trades in dashboard
4. Adjust profit targets/stop loss as needed

## Current Config

- `chains_to_scan`: solana (Base disabled)
- `min_trade_size_usd`: $1.00
- `max_trade_size_usd`: $50.00
- `default_trade_size_usd`: $5.00
- `pumpfun_profit_target_1`: 25% (sell 60%)
- `pumpfun_profit_target_2`: 50% (sell 80%)
- `pumpfun_stop_loss`: -15%

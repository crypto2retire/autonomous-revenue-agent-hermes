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
Current: 0.5164 SOL (FUNDED - READY TO TRADE)

## Next Steps

1. Test with free APIs first
2. If profitable, upgrade to Birdeye for better accuracy
3. Monitor trades in dashboard
4. Adjust profit targets/stop loss as needed

## ROI Analysis: Birdeye Premium ($199/month)

### Break-even Calculation
- Monthly cost: $199
- Average trade size: $5
- Average profit target: 25%
- Gross profit per winning trade: $1.25
- After Jupiter fees (~0.5%): $1.19 net profit per win

**Break-even: 167 winning trades per month**
- ~5-6 winning trades per day
- With 60% win rate: ~9 trades per day total
- Very achievable with active pump.fun scanning

### Value Proposition
**Birdeye provides:**
1. **Faster price updates** - WebSocket vs 15-30s polling
2. **More accurate prices** - Tick-level vs aggregated
3. **Higher rate limits** - 50 RPS vs 1-10 RPS free tiers
4. **Better token coverage** - New listings detected faster

**For short-term trading, speed matters:**
- 5-second delay on a pump.fun token = missing 10-50% of move
- Birdeye WebSocket gives near real-time data
- Free APIs have 15-60s delays

### Recommendation
**Start with free APIs, upgrade to Birdeye if:**
- You're making 5+ trades per day
- Free APIs are causing missed entries
- You're consistently profitable but want better execution

**Birdeye ROI depends on volume:**
- Low volume (1-2 trades/day): Not worth $199
- Medium volume (5-10 trades/day): Break-even at 25% win rate
- High volume (20+ trades/day): Easily profitable

## Current Config

- `chains_to_scan`: solana (Base disabled)
- `min_trade_size_usd`: $1.00
- `max_trade_size_usd`: $50.00
- `default_trade_size_usd`: $5.00
- `pumpfun_profit_target_1`: 25% (sell 60%)
- `pumpfun_profit_target_2`: 50% (sell 80%)
- `pumpfun_stop_loss`: -15%

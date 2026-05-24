# Deploy to Render.com with PostgreSQL

## Step 1: Push Code to GitHub

```bash
cd ~/autonomous-revenue-agent-hermes
git add -A
git commit -m "feat: Render deployment ready - PostgreSQL + Docker"
git push origin main
```

## Step 2: Create Render Account

1. Go to https://dashboard.render.com
2. Sign up with GitHub
3. Click **New +** → **Blueprint**

## Step 3: Deploy from Blueprint

1. Connect your GitHub repo: `crypto2retire/autonomous-revenue-agent-hermes`
2. Render reads `render.yaml` automatically
3. It creates:
   - **Web Service**: `crypto-trading-agent` (Docker)
   - **PostgreSQL Database**: `agent-db`

## Step 4: Add Secret Environment Variables

After the initial deploy, go to your Web Service → **Environment** tab:

### Required Secrets (sync: false in render.yaml)

| Variable | How to Get |
|----------|-----------|
| `DEEPSEEK_API_KEY` | https://platform.deepseek.com |
| `BASE_WALLET_PRIVATE_KEY` | Your Base wallet private key |
| `BASE_WALLET_ADDRESS` | Your Base wallet address |
| `SOLANA_WALLET_PRIVATE_KEY` | Your Solana wallet private key (base58) |
| `SOLANA_WALLET_ADDRESS` | Your Solana wallet address |

### Optional API Keys

| Variable | How to Get |
|----------|-----------|
| `VENICE_API_KEY` | https://venice.ai/settings/api |
| `BASESCAN_API_KEY` | https://basescan.org/apis |
| `COINGECKO_API_KEY` | https://www.coingecko.com/en/developers/dashboard |
| `DUNE_API_KEY` | https://dune.com/settings/api |
| `BIRDEYE_API_KEY` | https://birdeye.so/profile |

### Switch to Live Trading

Change `AGENT_MODE` from `paper` to `live` when ready.

## Step 5: Verify Deployment

1. Wait for build to complete (2-3 minutes)
2. Click the service URL (e.g., `https://crypto-trading-agent-xxx.onrender.com`)
3. Check `/health` endpoint
4. View dashboard at root `/`

## Architecture on Render

```
┌─────────────────────────────────────────┐
│         Render Web Service              │
│  ┌─────────┐ ┌─────────┐ ┌──────────┐ │
│  │ Scanner │ │Sell Agent│ │Wallet    │ │
│  │(Buy)    │ │         │ │Monitor   │ │
│  │5 min    │ │30 sec   │ │60 sec    │ │
│  └────┬────┘ └────┬────┘ └────┬─────┘ │
│       │           │           │        │
│  ┌────┴───────────┴───────────┴─────┐  │
│  │      FastAPI Dashboard :8000      │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│      Render PostgreSQL Database         │
│         agent-db (Standard)             │
└─────────────────────────────────────────┘
```

## Database Migrations

Tables are auto-created on startup via `DB.init()` in `main.py`.

To verify:
```bash
# Connect to Render PostgreSQL via psql
psql $(render psql agent-db)

# List tables
\dt

# Check trades
SELECT trade_id, symbol, status, pnl_pct FROM trades;
```

## Monitoring

- **Dashboard**: Service URL → `/`
- **Health**: `/health`
- **Logs**: Render Dashboard → Logs tab
- **Metrics**: Render Dashboard → Metrics tab

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Database connection error | Check `DATABASE_URL` is set from blueprint |
| SSL error | `database_url_clean` in config.py handles this |
| Build fails | Check `Dockerfile` and `requirements.txt` |
| Out of memory | Upgrade plan or reduce `MAX_POSITIONS` |

## Cost

| Component | Plan | Monthly |
|-----------|------|---------|
| Web Service | Standard | ~$7 |
| PostgreSQL | Standard | ~$7 |
| **Total** | | **~$14/mo** |

Free tier available but sleeps after 15 min inactivity (not suitable for trading bot).

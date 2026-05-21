# Autonomous Revenue Agent

An autonomous AI agent that seeks revenue opportunities to cover its own costs and grow its capital. Built to leverage free Venice AI API credits from A0T staking.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    AUTONOMOUS REVENUE AGENT                  │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   Venice AI  │  │  Opportunity │  │    Wallet    │      │
│  │   (A0T)      │  │   Scanner    │  │   Monitor    │      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘      │
│         │                 │                 │               │
│         └─────────────────┼─────────────────┘               │
│                           ▼                                 │
│                  ┌─────────────────┐                        │
│                  │   Survival Loop │                        │
│                  │  (Main Engine)  │                        │
│                  └────────┬────────┘                        │
│                           │                                 │
│         ┌─────────────────┼─────────────────┐               │
│         ▼                 ▼                 ▼               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   Trade      │  │   Service    │  │   Health     │      │
│  │   Executor   │  │  Marketplace │  │   Check      │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────┘
```

## Core Philosophy

**Holder + Volume First**: Traditional chart signals lag behind on-chain activity. This agent focuses on:
- **Holder growth**: New wallets = early interest before price moves
- **Volume patterns**: Activity spikes precede breakouts
- **Smart money flows**: Whale accumulation/distribution
- **Concentration changes**: Distribution = bullish, concentration = bearish

## Features

### 1. Opportunity Discovery
- Scans Base chain tokens for holder + volume signals
- AI analysis via Venice (free with A0T stake)
- Filters for minimum liquidity, holder count, and growth rate

### 2. Risk Management
- Position sizing based on confidence and risk level
- Daily loss limits and trade count caps
- Portfolio value tracking

### 3. Service Marketplace
- Offers WhatShouldICharge pricing estimates
- Phase 2: CTC Business Hub, BMM-POS, DoneLocal
- Agent-to-agent commerce

### 4. Survival Loop
- Monitors wallet balance and runway
- Switches to survival mode when threatened
- Emergency shutdown preserves capital

## Setup

### Prerequisites
- Python 3.11+
- A0T tokens staked for Venice API access
- Base wallet with ETH for gas
- Fly.io account (or other host)

### Installation

```bash
# Clone repository
git clone https://github.com/crypto2retire/autonomous-revenue-agent-hermes.git
cd autonomous-revenue-agent-hermes

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your values
```

### Configuration

Edit `.env`:

```env
# Venice AI (from A0T staking dashboard)
VENICE_API_KEY=your_venice_api_key

# Base wallet
BASE_WALLET_PRIVATE_KEY=your_private_key
BASE_WALLET_ADDRESS=your_wallet_address

# WhatShouldICharge
WSIC_API_KEY=your_wsic_api_key

# Database (Fly.io Postgres)
DATABASE_URL=your_database_url

# Agent mode: paper (safe) or live (real trades)
AGENT_MODE=paper
```

### Running

```bash
# Paper trading (safe, no real trades)
python main.py

# Live trading (real money at risk)
AGENT_MODE=live python main.py
```

### Deploy to Fly.io

```bash
# Launch app
fly launch

# Set secrets
fly secrets set VENICE_API_KEY=xxx
fly secrets set BASE_WALLET_PRIVATE_KEY=xxx
fly secrets set BASE_WALLET_ADDRESS=xxx
fly secrets set WSIC_API_KEY=xxx
fly secrets set DATABASE_URL=xxx

# Deploy
fly deploy
```

## Project Structure

```
autonomous-revenue-agent/
├── src/
│   ├── config/          # Settings and configuration
│   ├── venice/          # Venice AI client (A0T staking)
│   ├── opportunity/     # Opportunity scanner and models
│   ├── wallet/          # Wallet monitoring and holder tracking
│   ├── trade/           # Trade execution and risk management
│   ├── service/         # Service marketplace (WSIC integration)
│   ├── survival/        # Main survival loop
│   └── utils/           # Logging and utilities
├── main.py              # Entry point
├── Dockerfile           # Container image
├── fly.toml             # Fly.io configuration
├── requirements.txt     # Python dependencies
└── .env.example         # Environment template
```

## Data Sources (TODO)

- [ ] DexScreener API - Price, volume, liquidity
- [ ] BaseScan API - Holder data, transfers
- [ ] Dune Analytics - Smart money labels
- [ ] Alchemy/Infura - Raw on-chain data
- [ ] Odos/Uniswap - DEX execution

## Roadmap

### Phase 1: Foundation (Current)
- [x] Project structure
- [x] Venice AI integration
- [x] Opportunity models
- [x] Survival loop
- [ ] Live data source integration
- [ ] DEX trade execution

### Phase 2: Services
- [ ] WhatShouldICharge marketplace
- [ ] CTC Business Hub integration
- [ ] BMM-POS integration
- [ ] DoneLocal integration

### Phase 3: Intelligence
- [ ] Smart money wallet tracking
- [ ] Cross-token holder analysis
- [ ] Volume pattern recognition
- [ ] AI model fine-tuning

## Safety

- **Paper mode**: Default, simulates trades without real money
- **Risk limits**: Max 2% per trade, daily loss limits
- **Emergency shutdown**: Auto-stops if balance drops too low
- **No crypto mining**: Compliant with host terms of service

## License

MIT

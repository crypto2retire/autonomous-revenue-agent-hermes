"""FastAPI dashboard and API for the crypto trading agent."""

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from typing import Optional

from database import DB
from config import get_settings

settings = get_settings()

app = FastAPI(title="Crypto Trading Agent")


@app.on_event("startup")
async def startup():
    await DB.init()


# ── Health ─────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "agent": "crypto-trading-agent"}


@app.get("/api/status")
async def get_status():
    """Return agent health, last price refresh timestamps, and component status."""
    from datetime import datetime
    now = datetime.utcnow()
    
    try:
        # Get latest log events for each component
        logs = await DB.get_logs(limit=50, hours=1)
        
        latest_scan = None
        latest_price_refresh = None
        latest_trade = None
        
        for log in logs:
            if latest_scan is None and "scan" in (log.event or "").lower():
                latest_scan = log.created_at
            if latest_price_refresh is None and "price" in (log.event or "").lower():
                latest_price_refresh = log.created_at
            if latest_trade is None and "trade" in (log.event or "").lower():
                latest_trade = log.created_at
        
        # Count active coins and positions
        coins = await DB.get_all_coins(limit=1)
        positions = await DB.get_open_positions()
        
        return {
            "status": "ok",
            "agent": "crypto-trading-agent",
            "timestamp": now.isoformat(),
            "components": {
                "scanner": {
                    "status": "healthy" if latest_scan is not None and (now - latest_scan).total_seconds() < 300 else "stale",
                    "last_scan": latest_scan.isoformat() if latest_scan is not None else None,
                },
                "price_refresh": {
                    "status": "healthy" if latest_price_refresh is not None and (now - latest_price_refresh).total_seconds() < 120 else "stale",
                    "last_refresh": latest_price_refresh.isoformat() if latest_price_refresh is not None else None,
                },
                "trading": {
                    "status": "healthy" if latest_trade is not None and (now - latest_trade).total_seconds() < 600 else "idle",
                    "last_trade": latest_trade.isoformat() if latest_trade is not None else None,
                },
            },
            "counts": {
                "tracked_coins": len(coins) if coins else 0,
                "open_positions": len(positions),
            },
        }
    except Exception as e:
        # Don't crash the endpoint — return degraded status
        return {
            "status": "degraded",
            "agent": "crypto-trading-agent",
            "timestamp": now.isoformat(),
            "error": str(e),
            "components": {
                "scanner": {"status": "unknown", "last_scan": None},
                "price_refresh": {"status": "unknown", "last_refresh": None},
                "trading": {"status": "unknown", "last_trade": None},
            },
            "counts": {
                "tracked_coins": 0,
                "open_positions": 0,
            },
        }


# ── Coins / Watchlist ──────────────────────────────────────────────

@app.get("/api/coins")
async def get_coins(
    signal: Optional[str] = None,
    min_score: Optional[float] = None,
    deployer: Optional[str] = None,
    is_rugged: Optional[bool] = None,
    chain: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
):
    coins = await DB.get_all_coins(
        signal=signal,
        min_score=min_score,
        deployer_address=deployer,
        is_rugged=is_rugged,
        chain=chain,
        limit=limit,
    )
    # Build stats
    total = len(coins)
    buy_signals = sum(1 for c in coins if c.signal == "buy")
    sell_signals = sum(1 for c in coins if c.signal == "sell")
    bullish = sum(1 for c in coins if c.signal == "bullish")
    bearish = sum(1 for c in coins if c.signal == "bearish")
    avoid = sum(1 for c in coins if c.signal == "avoid")
    hold = sum(1 for c in coins if c.signal == "hold")
    rugged = sum(1 for c in coins if c.is_rugged)
    
    # Chain breakdown
    base_count = sum(1 for c in coins if c.chain == "base")
    solana_count = sum(1 for c in coins if c.chain == "solana")
    
    # Calculate average confidence
    avg_confidence = 0.0
    if total > 0:
        conf_sum = 0.0
        for c in coins:
            cv = c.confidence
            try:
                if cv is not None:
                    conf_sum += float(str(cv))
            except (TypeError, ValueError):
                pass
        avg_confidence = conf_sum / total
    
    # Get top gainer
    top_gainer = None
    top_gain_pct = 0.0
    for c in coins:
        pg = c.peak_gain_pct
        if pg is not None:
            pct = float(pg)
            if pct > top_gain_pct:
                top_gain_pct = pct
                top_gainer = c
    
    stats = {
        "total_coins": total,
        "base_coins": base_count,
        "solana_coins": solana_count,
        "buy_signals": buy_signals,
        "sell_signals": sell_signals,
        "bullish_signals": bullish,
        "bearish_signals": bearish,
        "avoid_signals": avoid,
        "hold_signals": hold,
        "rugged_coins": rugged,
        "avg_confidence": round(avg_confidence, 2),
        "top_gainer_symbol": top_gainer.symbol if top_gainer else None,
        "top_gainer_pct": round(top_gain_pct, 2) if top_gainer else 0,
    }
    return {
        "coins": [c.to_dict() for c in coins],
        "stats": stats,
        "count": len(coins),
    }


@app.get("/api/coins/gainers")
async def get_gainers(limit: int = 20, min_gain_pct: float = 5.0):
    coins = await DB.get_successful_coins(min_gain_pct=min_gain_pct, limit=limit)
    return {"coins": [c.to_dict() for c in coins]}


@app.get("/api/coins/losers")
async def get_losers(limit: int = 20):
    coins = await DB.get_all_coins(limit=500)
    losers = [c for c in coins if c.price_change_pct is not None and float(c.price_change_pct) < -5]
    losers.sort(key=lambda x: float(x.price_change_pct or 0))
    return {"coins": [c.to_dict() for c in losers[:limit]]}


@app.get("/api/coins/trending")
async def get_trending(limit: int = 20):
    coins = await DB.get_all_coins(limit=500)
    # Sort by scan count (most scanned = trending)
    trending = sorted(coins, key=lambda x: x.scan_count, reverse=True)
    return {"coins": [c.to_dict() for c in trending[:limit]]}


@app.get("/api/coins/{token_address}")
async def get_coin_detail(token_address: str):
    coin = await DB.get_coin(token_address)
    if not coin:
        return {"error": "Coin not found"}
    
    # Get price history
    price_history = await DB.get_price_history(token_address, hours=168)  # 7 days
    
    # Get deployer info
    deployer = None
    if coin.deployer_address:
        deployer = await DB.get_deployer(coin.deployer_address)
    
    # Get other coins from same deployer
    deployer_coins = []
    if coin.deployer_address:
        deployer_coins = await DB.get_coins_by_deployer(coin.deployer_address)
    
    return {
        "coin": coin.to_dict(),
        "price_history": [h.to_dict() for h in price_history],
        "deployer": deployer.to_dict() if deployer else None,
        "deployer_coins": [c.to_dict() for c in deployer_coins if c.token_address != token_address],
    }


# ── Deployers ──────────────────────────────────────────────────────

@app.get("/api/deployers")
async def get_deployers(
    reputation: Optional[str] = None,
    min_score: Optional[float] = None,
    limit: int = Query(100, ge=1, le=500),
):
    deployers = await DB.get_all_deployers(
        reputation=reputation,
        min_score=min_score,
        limit=limit,
    )
    return {
        "deployers": [d.to_dict() for d in deployers],
        "count": len(deployers),
    }


@app.get("/api/deployers/{address}")
async def get_deployer_detail(address: str):
    deployer = await DB.get_deployer(address)
    if not deployer:
        return {"error": "Deployer not found"}
    
    coins = await DB.get_coins_by_deployer(address)
    return {
        "deployer": deployer.to_dict(),
        "coins": [c.to_dict() for c in coins],
    }


# ── Price History ──────────────────────────────────────────────────

@app.get("/api/price-history/{token_address}")
async def get_price_history(token_address: str, hours: int = 24):
    history = await DB.get_price_history(token_address, hours=hours)
    return {"history": [h.to_dict() for h in history], "count": len(history)}


# ── Trades ─────────────────────────────────────────────────────────

@app.get("/api/trades")
async def get_trades(status: Optional[str] = None, chain: Optional[str] = None, limit: int = 100):
    trades = await DB.get_trades(status=status, chain=chain, limit=limit)
    return {"trades": [t.to_dict() for t in trades], "count": len(trades)}


@app.get("/api/positions")
async def get_positions():
    """Get all open positions with current PNL."""
    positions = await DB.get_open_positions()
    summary = await DB.get_portfolio_summary()
    return {
        "positions": positions,
        "summary": summary,
    }


@app.get("/api/portfolio")
async def get_portfolio():
    """Get portfolio summary with total PNL."""
    summary = await DB.get_portfolio_summary()
    return {"summary": summary}


# ── Performance ────────────────────────────────────────────────────

@app.get("/api/performance")
async def get_performance(hours: int = 24):
    summary = await DB.get_performance_summary(hours=hours)
    return {"summary": summary}


# ── Logs ───────────────────────────────────────────────────────────

@app.get("/api/logs")
async def get_logs(event: Optional[str] = None, limit: int = 100):
    logs = await DB.get_logs(event=event, limit=limit)
    return {"logs": [l.to_dict() for l in logs], "count": len(logs)}


# ── Settings ───────────────────────────────────────────────────────

@app.get("/api/settings")
async def get_settings_api():
    settings_list = await DB.get_all_settings()
    return {"settings": [s.to_dict() for s in settings_list]}


@app.post("/api/settings/{key}")
async def set_setting_api(key: str, value: str, value_type: str = "string"):
    await DB.set_setting(key, value, value_type)
    return {"status": "ok", "key": key}


# ── Live Trading Toggle ────────────────────────────────────────────

@app.get("/api/birdeye-usage")
async def get_birdeye_usage_api():
    """Get Birdeye API usage stats."""
    from solana_price_client import get_solana_price_client
    try:
        client = await get_solana_price_client()
        usage = client.get_birdeye_usage()
        return {
            "birdeye_usage": usage,
            "status": "ok",
        }
    except Exception as e:
        return {"error": str(e), "status": "error"}


@app.get("/api/trading/status")
async def get_trading_status():
    """Get current trading status. Live is only effective when env AGENT_MODE=live and dashboard switch is enabled."""
    live_requested = await DB.get_setting("live_trading_enabled", False)
    effective_live = bool(live_requested and settings.is_live)
    return {
        "live_trading_enabled": effective_live,
        "live_requested": bool(live_requested),
        "agent_mode": settings.agent_mode,
        "effective_mode": "live" if effective_live else "paper",
        "paper_trading_enabled": not effective_live,
        "max_positions": settings.max_positions,
        "trade_size_usd": settings.min_trade_size_usd,
    }


@app.post("/api/trading/toggle")
async def toggle_trading():
    """Toggle live trading on/off."""
    current = await DB.get_setting("live_trading_enabled", False)
    new_value = not current
    await DB.set_setting("live_trading_enabled", new_value, "bool", "Whether live trading is enabled (true) or paper trading only (false)")
    await DB.log_event("info", "trading_toggled", f"Live trading {'enabled' if new_value else 'disabled'}")
    return {"live_trading_enabled": new_value, "message": f"Live trading {'enabled' if new_value else 'disabled'}"}


@app.post("/api/trading/enable")
async def enable_trading():
    """Enable live trading."""
    await DB.set_setting("live_trading_enabled", True, "bool", "Whether live trading is enabled")
    await DB.log_event("info", "trading_enabled", "Live trading enabled")
    return {"live_trading_enabled": True, "message": "Live trading enabled"}


@app.post("/api/trading/disable")
async def disable_trading():
    """Disable live trading (paper mode)."""
    await DB.set_setting("live_trading_enabled", False, "bool", "Whether live trading is enabled")
    await DB.log_event("info", "trading_disabled", "Live trading disabled - paper mode only")
    return {"live_trading_enabled": False, "message": "Live trading disabled - paper mode only"}


# ── HTML Dashboard ─────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return """<!DOCTYPE html>
<html>
<head>
    <title>Crypto Trading Agent</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0a0e1a; color: #e0e6ed; line-height: 1.6;
        }
        .container { max-width: 1400px; margin: 0 auto; padding: 20px; }
        h1 { font-size: 1.8rem; margin-bottom: 10px; color: #00d4aa; }
        .subtitle { color: #8892a0; margin-bottom: 20px; }
        .tabs {
            display: flex; gap: 5px; margin-bottom: 20px;
            border-bottom: 1px solid #1a2332; padding-bottom: 10px;
            flex-wrap: wrap;
        }
        .tab {
            padding: 10px 20px; cursor: pointer; border-radius: 6px 6px 0 0;
            background: #111827; border: 1px solid #1a2332;
            color: #8892a0; font-weight: 500;
        }
        .tab.active { background: #1a2332; color: #00d4aa; border-bottom-color: #00d4aa; }
        .tab:hover { color: #e0e6ed; }
        .panel { display: none; }
        .panel.active { display: block; }
        .stats-grid {
            display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 15px; margin-bottom: 20px;
        }
        .stat-card {
            background: #111827; border: 1px solid #1a2332; border-radius: 8px;
            padding: 15px; text-align: center;
        }
        .stat-value { font-size: 1.5rem; font-weight: 700; color: #00d4aa; }
        .stat-label { font-size: 0.8rem; color: #8892a0; margin-top: 5px; }
        table {
            width: 100%; border-collapse: collapse; background: #111827;
            border-radius: 8px; overflow: hidden; font-size: 0.9rem;
        }
        th, td { padding: 10px 12px; text-align: left; border-bottom: 1px solid #1a2332; }
        th { background: #0d1117; color: #8892a0; font-weight: 600; font-size: 0.8rem; text-transform: uppercase; }
        tr:hover { background: #1a2332; }
        .badge {
            display: inline-block; padding: 3px 8px; border-radius: 4px;
            font-size: 0.75rem; font-weight: 600;
        }
        .badge-buy { background: #064e3b; color: #34d399; }
        .badge-sell { background: #7f1d1d; color: #f87171; }
        .badge-hold { background: #1e3a5f; color: #60a5fa; }
        .badge-avoid { background: #4b5563; color: #9ca3af; }
        .badge-bullish { background: #064e3b; color: #34d399; }
        .badge-bearish { background: #7f1d1d; color: #f87171; }
        .badge-neutral { background: #4b5563; color: #9ca3af; }
        .badge-trusted { background: #064e3b; color: #34d399; }
        .badge-rugger { background: #7f1d1d; color: #f87171; }
        .badge-suspect { background: #92400e; color: #fbbf24; }
        .positive { color: #34d399; }
        .negative { color: #f87171; }
        .refresh-bar {
            display: flex; justify-content: space-between; align-items: center;
            margin-bottom: 15px; color: #8892a0; font-size: 0.85rem;
        }
        .btn {
            padding: 6px 14px; border-radius: 4px; border: none;
            background: #00d4aa; color: #0a0e1a; font-weight: 600; cursor: pointer;
        }
        .btn:hover { background: #00b894; }
        .btn-secondary {
            background: #1a2332; color: #e0e6ed; border: 1px solid #2d3748;
        }
        .btn-secondary:hover { background: #2d3748; }
        .filters { display: flex; gap: 10px; margin-bottom: 15px; flex-wrap: wrap; }
        .filters select, .filters input {
            padding: 6px 10px; border-radius: 4px; border: 1px solid #1a2332;
            background: #111827; color: #e0e6ed;
        }
        .health-bar {
            display: flex; gap: 15px; align-items: center; margin-bottom: 15px;
            padding: 10px 15px; background: #111827; border-radius: 8px;
            border: 1px solid #1a2332; font-size: 0.85rem;
        }
        .health-indicator {
            display: flex; align-items: center; gap: 6px;
        }
        .health-dot {
            width: 8px; height: 8px; border-radius: 50%;
        }
        .health-dot.healthy { background: #34d399; }
        .health-dot.stale { background: #fbbf24; }
        .health-dot.idle { background: #9ca3af; }
        .health-dot.offline { background: #64748b; }
        .health-label { color: #8892a0; }
        .health-value { color: #e0e6ed; font-weight: 600; }
        .deployer-info {
            background: #111827; border: 1px solid #1a2332; border-radius: 8px;
            padding: 15px; margin-bottom: 15px;
        }
        .deployer-info h3 { color: #00d4aa; margin-bottom: 10px; }
        .deployer-info p { margin: 5px 0; }
        .coin-detail {
            background: #111827; border: 1px solid #1a2332; border-radius: 8px;
            padding: 20px; margin-bottom: 20px;
        }
        .coin-detail h2 { color: #00d4aa; margin-bottom: 15px; }
        .coin-detail .info-grid {
            display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px; margin-bottom: 20px;
        }
        .coin-detail .info-item { 
            background: #0d1117; padding: 10px; border-radius: 6px;
        }
        .coin-detail .info-label { color: #8892a0; font-size: 0.8rem; }
        .coin-detail .info-value { font-size: 1.1rem; font-weight: 600; }
        .chart-container {
            background: #111827; border: 1px solid #1a2332; border-radius: 8px;
            padding: 20px; margin-bottom: 20px;
            height: 400px;
        }
        .back-btn {
            margin-bottom: 15px;
        }
        @media (max-width: 768px) {
            .stats-grid { grid-template-columns: repeat(2, 1fr); }
            table { font-size: 0.8rem; }
            th, td { padding: 8px; }
            .chart-container { height: 300px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🤖 Crypto Trading Agent</h1>
        <div class="health-bar" id="health-bar">
            <div class="health-indicator">
                <div class="health-dot idle" id="health-scanner-dot"></div>
                <span class="health-label">Scanner:</span>
                <span class="health-value" id="health-scanner">Loading...</span>
            </div>
            <div class="health-indicator">
                <div class="health-dot idle" id="health-price-dot"></div>
                <span class="health-label">Prices:</span>
                <span class="health-value" id="health-price">Loading...</span>
            </div>
            <div class="health-indicator">
                <div class="health-dot idle" id="health-trade-dot"></div>
                <span class="health-label">Trading:</span>
                <span class="health-value" id="health-trade">Loading...</span>
            </div>
            <div class="health-indicator">
                <span class="health-label">Coins:</span>
                <span class="health-value" id="health-coins">-</span>
            </div>
            <div class="health-indicator">
                <span class="health-label">Positions:</span>
                <span class="health-value" id="health-positions">-</span>
            </div>
        </div>
        <p class="subtitle">Autonomous scanner, analyzer &amp; executor</p>

        <div class="tabs">
            <div class="tab active" onclick="showTab('watchlist')">📊 Watchlist</div>
            <div class="tab" onclick="showTab('market')">📈 Market</div>
            <div class="tab" onclick="showTab('deployers')">👤 Deployers</div>
            <div class="tab" onclick="showTab('trades')">💰 Trades</div>
            <div class="tab" onclick="showTab('positions')">📈 Positions</div>
            <div class="tab" onclick="showTab('performance')">📊 Performance</div>
            <div class="tab" onclick="showTab('logs')">📝 Logs</div>
            <div class="tab" onclick="showTab('settings')">⚙️ Settings</div>
        </div>

        <!-- Watchlist Panel -->
        <div class="panel active" id="watchlist-panel">
            <div class="refresh-bar">
                <span id="watchlist-count">Loading...</span>
                <button class="btn" onclick="loadWatchlist()">Refresh</button>
            </div>
            <div class="stats-grid" id="watchlist-stats"></div>
            <div class="filters">
                <select id="signal-filter" onchange="loadWatchlist()">
                    <option value="">All Signals</option>
                    <option value="buy">Buy</option>
                    <option value="sell">Sell</option>
                    <option value="bullish">Bullish</option>
                    <option value="bearish">Bearish</option>
                    <option value="hold">Hold</option>
                    <option value="avoid">Avoid</option>
                </select>
                <select id="rugged-filter" onchange="loadWatchlist()">
                    <option value="">All Coins</option>
                    <option value="false">Active Only</option>
                    <option value="true">Rugged Only</option>
                </select>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>Symbol</th>
                        <th>Signal</th>
                        <th>Price</th>
                        <th>1m</th>
                        <th>5m</th>
                        <th>30m</th>
                        <th>1h</th>
                        <th>Volume 24h</th>
                        <th>Liquidity</th>
                        <th>Holders</th>
                        <th>AI Score</th>
                        <th>Scans</th>
                        <th>Deployer</th>
                        <th>Last Seen</th>
                    </tr>
                </thead>
                <tbody id="watchlist-body"></tbody>
            </table>
        </div>

        <!-- Market Panel -->
        <div class="panel" id="market-panel">
            <div class="refresh-bar">
                <span>Market Overview</span>
                <button class="btn" onclick="loadMarket()">Refresh</button>
            </div>
            <div class="stats-grid" id="market-stats"></div>
            
            <h3 style="margin: 20px 0 10px; color: #00d4aa;">🔥 Top Gainers</h3>
            <table>
                <thead>
                    <tr>
                        <th>Symbol</th>
                        <th>Price</th>
                        <th>Peak Gain</th>
                        <th>Signal</th>
                        <th>AI Score</th>
                        <th>Source</th>
                    </tr>
                </thead>
                <tbody id="market-gainers-body"></tbody>
            </table>
            
            <h3 style="margin: 20px 0 10px; color: #f87171;">📉 Top Losers</h3>
            <table>
                <thead>
                    <tr>
                        <th>Symbol</th>
                        <th>Price</th>
                        <th>Change</th>
                        <th>Signal</th>
                        <th>AI Score</th>
                    </tr>
                </thead>
                <tbody id="market-losers-body"></tbody>
            </table>
            
            <h3 style="margin: 20px 0 10px; color: #60a5fa;">📊 Trending (Most Scanned)</h3>
            <table>
                <thead>
                    <tr>
                        <th>Symbol</th>
                        <th>Scans</th>
                        <th>Price</th>
                        <th>Signal</th>
                        <th>AI Score</th>
                    </tr>
                </thead>
                <tbody id="market-trending-body"></tbody>
            </table>
        </div>

        <!-- Deployers Panel -->
        <div class="panel" id="deployers-panel">
            <div class="refresh-bar">
                <span id="deployers-count">Loading...</span>
                <button class="btn" onclick="loadDeployers()">Refresh</button>
            </div>
            <div class="stats-grid" id="deployers-stats"></div>
            <div class="filters">
                <select id="reputation-filter" onchange="loadDeployers()">
                    <option value="">All Reputations</option>
                    <option value="trusted">Trusted</option>
                    <option value="verified">Verified</option>
                    <option value="suspect">Suspect</option>
                    <option value="rugger">Rugger</option>
                    <option value="unknown">Unknown</option>
                </select>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>Address</th>
                        <th>Reputation</th>
                        <th>Score</th>
                        <th>Tokens</th>
                        <th>Success</th>
                        <th>Rugs</th>
                        <th>First Seen</th>
                    </tr>
                </thead>
                <tbody id="deployers-body"></tbody>
            </table>
        </div>

        <!-- Trades Panel -->
        <div class="panel" id="trades-panel">
            <div class="refresh-bar">
                <span id="trades-count">Loading...</span>
                <button class="btn" onclick="loadTrades()">Refresh</button>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>Symbol</th>
                        <th>Side</th>
                        <th>Amount</th>
                        <th>Price</th>
                        <th>Total</th>
                        <th>Type</th>
                        <th>Status</th>
                        <th>Created</th>
                    </tr>
                </thead>
                <tbody id="trades-body"></tbody>
            </table>
        </div>

        <!-- Performance Panel -->
        <div class="panel" id="performance-panel">
            <div class="refresh-bar">
                <span>Performance Summary</span>
                <button class="btn" onclick="loadPerformance()">Refresh</button>
            </div>
            <div class="stats-grid" id="performance-stats"></div>
        </div>

        <!-- Positions Panel -->
        <div class="panel" id="positions-panel">
            <div class="refresh-bar">
                <span id="positions-count">Loading...</span>
                <button class="btn" onclick="loadPositions()">Refresh</button>
            </div>
            <div class="stats-grid" id="positions-stats"></div>
            <table>
                <thead>
                    <tr>
                        <th>Symbol</th>
                        <th>Amount</th>
                        <th>Entry Price</th>
                        <th>Current Price</th>
                        <th>PNL ($)</th>
                        <th>PNL %</th>
                        <th>Entry Time</th>
                        <th>TX</th>
                    </tr>
                </thead>
                <tbody id="positions-body"></tbody>
            </table>
        </div>

        <!-- Logs Panel -->
        <div class="panel" id="logs-panel">
            <div class="refresh-bar">
                <span id="logs-count">Loading...</span>
                <button class="btn" onclick="loadLogs()">Refresh</button>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>Time</th>
                        <th>Level</th>
                        <th>Event</th>
                        <th>Message</th>
                    </tr>
                </thead>
                <tbody id="logs-body"></tbody>
            </table>
        </div>

        <!-- Settings Panel -->
        <div class="panel" id="settings-panel">
            <div class="refresh-bar">
                <span>Agent Settings</span>
            </div>
            <div class="stats-grid" id="settings-stats">
                <div class="stat-card">
                    <div class="stat-value" id="trading-status">Loading...</div>
                    <div class="stat-label">Trading Mode</div>
                </div>
            </div>
            <div style="background: #111827; border: 1px solid #1a2332; border-radius: 8px; padding: 20px; margin-top: 20px;">
                <h3 style="color: #00d4aa; margin-bottom: 15px;">🔄 Live Trading Toggle</h3>
                <p style="color: #8892a0; margin-bottom: 20px;">
                    Control whether the agent executes real trades with real funds. 
                    When disabled, the agent runs in paper trading mode (simulated trades only).
                </p>
                <div id="trading-toggle-section">
                    <div style="display: flex; align-items: center; gap: 15px; margin-bottom: 20px;">
                        <div id="trading-indicator" style="width: 12px; height: 12px; border-radius: 50%; background: #4b5563;"></div>
                        <span id="trading-text" style="font-size: 1.1rem; font-weight: 600;">Loading...</span>
                    </div>
                    <button class="btn" id="trading-toggle-btn" onclick="toggleTrading()" style="width: auto;">Toggle Trading</button>
                </div>
                <div id="trading-message" style="margin-top: 15px; padding: 10px; border-radius: 4px; display: none;"></div>
            </div>
            
            <div style="background: #111827; border: 1px solid #1a2332; border-radius: 8px; padding: 20px; margin-top: 20px;">
                <h3 style="color: #00d4aa; margin-bottom: 15px;">📋 All Settings</h3>
                <div id="settings-list">Loading...</div>
            </div>
        </div>

        <!-- Coin Detail Panel -->
        <div class="panel" id="coin-detail-panel">
            <button class="btn btn-secondary back-btn" onclick="showTab('watchlist')">← Back to Watchlist</button>
            <div id="coin-detail-content"></div>
        </div>
    </div>

    <script>
        function showTab(name) {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
            event.target.classList.add('active');
            document.getElementById(name + '-panel').classList.add('active');
            if (name === 'watchlist') loadWatchlist();
            if (name === 'market') loadMarket();
            if (name === 'deployers') loadDeployers();
            if (name === 'trades') loadTrades();
            if (name === 'positions') loadPositions();
            if (name === 'performance') loadPerformance();
            if (name === 'logs') loadLogs();
            if (name === 'settings') loadSettings();
        }

        function fmtNum(n, d=2) {
            if (n === null || n === undefined) return '-';
            if (n >= 1e9) return '$' + (n/1e9).toFixed(d) + 'B';
            if (n >= 1e6) return '$' + (n/1e6).toFixed(d) + 'M';
            if (n >= 1e3) return '$' + (n/1e3).toFixed(d) + 'K';
            return '$' + n.toFixed(d);
        }

        function fmtPct(n) {
            if (n === null || n === undefined) return '-';
            const cls = n >= 0 ? 'positive' : 'negative';
            return '<span class="' + cls + '" style="font-weight:600">' + (n >= 0 ? '+' : '') + n.toFixed(2) + '%</span>';
        }

        function fmtCompact(n) {
            if (n === null || n === undefined || n === 0) return '-';
            const abs = Math.abs(n);
            if (abs >= 1e9) return '$' + (n/1e9).toFixed(2) + 'B';
            if (abs >= 1e6) return '$' + (n/1e6).toFixed(2) + 'M';
            if (abs >= 1e3) return '$' + (n/1e3).toFixed(1) + 'K';
            return '$' + n.toFixed(0);
        }

        function timeAgo(iso) {
            if (!iso) return '-';
            const d = new Date(iso);
            const diff = (Date.now() - d.getTime()) / 1000;
            if (diff < 60) return Math.floor(diff) + 's ago';
            if (diff < 3600) return Math.floor(diff/60) + 'm ago';
            if (diff < 86400) return Math.floor(diff/3600) + 'h ago';
            return Math.floor(diff/86400) + 'd ago';
        }

        function shortAddr(addr) {
            if (!addr) return '-';
            return addr.substring(0, 6) + '...' + addr.substring(addr.length - 4);
        }

        async function loadWatchlist() {
            const signal = document.getElementById('signal-filter').value;
            const rugged = document.getElementById('rugged-filter').value;
            let url = '/api/coins?limit=200';
            if (signal) url += '&signal=' + signal;
            if (rugged) url += '&is_rugged=' + rugged;

            try {
                const res = await fetch(url);
                if (!res.ok) throw new Error('HTTP ' + res.status);
                const data = await res.json();

                document.getElementById('watchlist-count').textContent = (data.count || 0) + ' coins tracked';

                const stats = data.stats || {};
                document.getElementById('watchlist-stats').innerHTML = `
                    <div class="stat-card"><div class="stat-value">${stats.total_coins || 0}</div><div class="stat-label">Total Coins</div></div>
                    <div class="stat-card"><div class="stat-value">${stats.buy_signals || 0}</div><div class="stat-label">Buy Signals</div></div>
                    <div class="stat-card"><div class="stat-value">${stats.avoid_signals || 0}</div><div class="stat-label">Avoid</div></div>
                    <div class="stat-card"><div class="stat-value">${stats.hold_signals || 0}</div><div class="stat-label">Hold</div></div>
                    <div class="stat-card"><div class="stat-value">${stats.rugged_coins || 0}</div><div class="stat-label">Rugged</div></div>
                    <div class="stat-card"><div class="stat-value">${(stats.avg_confidence || 0).toFixed(0)}%</div><div class="stat-label">Avg Confidence</div></div>
                `;

                const tbody = document.getElementById('watchlist-body');
                if (!data.coins || data.coins.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="14" style="text-align:center;color:#8892a0">No coins found</td></tr>';
                    return;
                }
                tbody.innerHTML = data.coins.map(c => `
                    <tr style="cursor:pointer" onclick="showCoinDetail('${c.token_address}')">
                        <td><strong>${c.symbol}</strong><br><small style="color:#8892a0">${c.name || ''}</small></td>
                        <td><span class="badge badge-${c.signal}">${c.signal?.toUpperCase()}</span></td>
                        <td>${fmtNum(c.last_price_usd || c.first_price_usd, 6)}</td>
                        <td class="${c.price_change_1m_pct > 0 ? 'positive' : c.price_change_1m_pct < 0 ? 'negative' : ''}">${fmtPct(c.price_change_1m_pct)}</td>
                        <td class="${c.price_change_5m_pct > 0 ? 'positive' : c.price_change_5m_pct < 0 ? 'negative' : ''}">${fmtPct(c.price_change_5m_pct)}</td>
                        <td class="${c.price_change_30m_pct > 0 ? 'positive' : c.price_change_30m_pct < 0 ? 'negative' : ''}">${fmtPct(c.price_change_30m_pct)}</td>
                        <td class="${c.price_change_1h_pct > 0 ? 'positive' : c.price_change_1h_pct < 0 ? 'negative' : ''}">${fmtPct(c.price_change_1h_pct)}</td>
                        <td>${fmtCompact(c.volume_24h)}</td>
                        <td>${fmtCompact(c.liquidity_usd)}</td>
                        <td>${c.holder_count ? c.holder_count.toLocaleString() : '-'}</td>
                        <td>${((c.confidence || 0) * 100).toFixed(0)}%</td>
                        <td>${c.scan_count || 0}</td>
                        <td>${c.deployer_address ? `<a href="#" onclick="event.stopPropagation();showDeployer('${c.deployer_address}');return false">${shortAddr(c.deployer_address)}</a>` : '-'}</td>
                        <td>${timeAgo(c.last_seen_at)}</td>
                    </tr>
                `).join('');
            } catch (e) {
                console.error('Watchlist load failed:', e);
                document.getElementById('watchlist-body').innerHTML = `<tr><td colspan="14" style="text-align:center;color:#f87171">Error loading watchlist: ${e.message}</td></tr>`;
            }
        }

        async function showCoinDetail(tokenAddress) {
            const res = await fetch('/api/coins/' + tokenAddress);
            const data = await res.json();
            
            if (data.error) {
                alert(data.error);
                return;
            }
            
            const coin = data.coin;
            const history = data.price_history;
            
            // Switch to detail panel
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
            document.getElementById('coin-detail-panel').classList.add('active');
            
            // Build detail HTML
            const detailHtml = `
                <div class="coin-detail">
                    <h2>${coin.symbol} — ${coin.name}</h2>
                    <div class="info-grid">
                        <div class="info-item">
                            <div class="info-label">Signal</div>
                            <div class="info-value"><span class="badge badge-${coin.signal}">${coin.signal?.toUpperCase()}</span></div>
                        </div>
                        <div class="info-item">
                            <div class="info-label">AI Confidence</div>
                            <div class="info-value">${((coin.confidence || 0) * 100).toFixed(0)}%</div>
                        </div>
                        <div class="info-item">
                            <div class="info-label">Current Price</div>
                            <div class="info-value">${fmtNum(coin.last_price_usd, 6)}</div>
                        </div>
                        <div class="info-item">
                            <div class="info-label">Discovery Price</div>
                            <div class="info-value">${fmtNum(coin.first_price_usd, 6)}</div>
                        </div>
                        <div class="info-item">
                            <div class="info-label">Peak Gain</div>
                            <div class="info-value">${fmtPct(coin.peak_gain_pct)}</div>
                        </div>
                        <div class="info-item">
                            <div class="info-label">Peak Loss</div>
                            <div class="info-value">${fmtPct(coin.peak_loss_pct)}</div>
                        </div>
                        <div class="info-item">
                            <div class="info-label">Volume 24h</div>
                            <div class="info-value">${fmtNum(coin.volume_24h)}</div>
                        </div>
                        <div class="info-item">
                            <div class="info-label">Liquidity</div>
                            <div class="info-value">${fmtNum(coin.liquidity_usd)}</div>
                        </div>
                        <div class="info-item">
                            <div class="info-label">Market Cap</div>
                            <div class="info-value">${fmtNum(coin.market_cap)}</div>
                        </div>
                        <div class="info-item">
                            <div class="info-label">Discovery Source</div>
                            <div class="info-value">${coin.discovery_source || 'Unknown'}</div>
                        </div>
                        <div class="info-item">
                            <div class="info-label">Scans</div>
                            <div class="info-value">${coin.scan_count || 0}</div>
                        </div>
                        <div class="info-item">
                            <div class="info-label">First Seen</div>
                            <div class="info-value">${timeAgo(coin.first_seen_at)}</div>
                        </div>
                    </div>
                    
                    ${coin.ai_analysis ? `<div style="margin-top: 15px; padding: 15px; background: #0d1117; border-radius: 6px;">
                        <div class="info-label">AI Analysis</div>
                        <div style="margin-top: 8px; white-space: pre-wrap;">${coin.ai_analysis}</div>
                    </div>` : ''}
                </div>
                
                ${history.length > 0 ? `
                <div class="chart-container">
                    <canvas id="priceChart"></canvas>
                </div>
                ` : '<div style="text-align: center; padding: 40px; color: #8892a0;">No price history available yet</div>'}
                
                ${data.deployer ? `
                <div class="deployer-info">
                    <h3>👤 Deployer</h3>
                    <p><strong>Address:</strong> ${data.deployer.address}</p>
                    <p><strong>Reputation:</strong> <span class="badge badge-${data.deployer.reputation}">${data.deployer.reputation?.toUpperCase()}</span></p>
                    <p><strong>Score:</strong> ${((data.deployer.reputation_score || 0) * 100).toFixed(0)}%</p>
                    <p><strong>Tokens Deployed:</strong> ${data.deployer.total_tokens_deployed || 0}</p>
                    <p><strong>Successful:</strong> ${data.deployer.successful_tokens || 0}</p>
                    <p><strong>Rugged:</strong> ${data.deployer.rugged_tokens || 0}</p>
                </div>
                ` : ''}
                
                ${data.deployer_coins?.length > 0 ? `
                <h3 style="margin: 20px 0 10px; color: #00d4aa;">Other Coins from Same Deployer</h3>
                <table>
                    <thead>
                        <tr><th>Symbol</th><th>Signal</th><th>Price</th><th>Peak Gain</th></tr>
                    </thead>
                    <tbody>
                        ${data.deployer_coins.map(c => `
                            <tr>
                                <td><strong>${c.symbol}</strong></td>
                                <td><span class="badge badge-${c.signal}">${c.signal?.toUpperCase()}</span></td>
                                <td>${fmtNum(c.last_price_usd, 6)}</td>
                                <td>${fmtPct(c.peak_gain_pct)}</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
                ` : ''}
            `;
            
            document.getElementById('coin-detail-content').innerHTML = detailHtml;
            
            // Render chart if we have history
            if (history.length > 0) {
                const ctx = document.getElementById('priceChart').getContext('2d');
                new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: history.map(h => new Date(h.created_at).toLocaleTimeString()),
                        datasets: [{
                            label: 'Price (USD)',
                            data: history.map(h => h.price_usd),
                            borderColor: '#00d4aa',
                            backgroundColor: 'rgba(0, 212, 170, 0.1)',
                            fill: true,
                            tension: 0.4,
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: { display: false },
                            title: { display: true, text: 'Price History', color: '#e0e6ed' }
                        },
                        scales: {
                            x: { ticks: { color: '#8892a0' }, grid: { color: '#1a2332' } },
                            y: { ticks: { color: '#8892a0' }, grid: { color: '#1a2332' } }
                        }
                    }
                });
            }
        }

        async function loadMarket() {
            // Load all market data concurrently
            const [gainersRes, losersRes, trendingRes, coinsRes] = await Promise.all([
                fetch('/api/coins/gainers?limit=10'),
                fetch('/api/coins/losers?limit=10'),
                fetch('/api/coins/trending?limit=10'),
                fetch('/api/coins?limit=1'),
            ]);
            
            const gainers = await gainersRes.json();
            const losers = await losersRes.json();
            const trending = await trendingRes.json();
            const coins = await coinsRes.json();
            
            // Market stats
            const stats = coins.stats || {};
            document.getElementById('market-stats').innerHTML = `
                <div class="stat-card"><div class="stat-value">${stats.total_coins || 0}</div><div class="stat-label">Total Tracked</div></div>
                <div class="stat-card"><div class="stat-value">${stats.buy_signals || 0}</div><div class="stat-label">Buy Signals</div></div>
                <div class="stat-card"><div class="stat-value">${stats.bullish_signals || 0}</div><div class="stat-label">Bullish</div></div>
                <div class="stat-card"><div class="stat-value">${stats.avoid_signals || 0}</div><div class="stat-label">Avoid</div></div>
                <div class="stat-card"><div class="stat-value">${stats.rugged_coins || 0}</div><div class="stat-label">Rugged</div></div>
                <div class="stat-card"><div class="stat-value">${stats.top_gainer_symbol || '-'}</div><div class="stat-label">Top Gainer</div></div>
            `;
            
            // Gainers
            document.getElementById('market-gainers-body').innerHTML = (gainers.coins || []).map(c => `
                <tr style="cursor:pointer" onclick="showCoinDetail('${c.token_address}')">
                    <td><strong>${c.symbol}</strong><br><small style="color:#8892a0">${c.name || ''}</small></td>
                    <td>${fmtNum(c.last_price_usd, 6)}</td>
                    <td class="positive">+${(c.peak_gain_pct || 0).toFixed(2)}%</td>
                    <td><span class="badge badge-${c.signal}">${c.signal?.toUpperCase()}</span></td>
                    <td>${((c.confidence || 0) * 100).toFixed(0)}%</td>
                    <td>${c.discovery_source || 'Unknown'}</td>
                </tr>
            `).join('') || '<tr><td colspan="6" style="text-align:center;color:#8892a0">No gainers yet</td></tr>';
            
            // Losers
            document.getElementById('market-losers-body').innerHTML = (losers.coins || []).map(c => `
                <tr style="cursor:pointer" onclick="showCoinDetail('${c.token_address}')">
                    <td><strong>${c.symbol}</strong><br><small style="color:#8892a0">${c.name || ''}</small></td>
                    <td>${fmtNum(c.last_price_usd, 6)}</td>
                    <td class="negative">${(c.price_change_pct || 0).toFixed(2)}%</td>
                    <td><span class="badge badge-${c.signal}">${c.signal?.toUpperCase()}</span></td>
                    <td>${((c.confidence || 0) * 100).toFixed(0)}%</td>
                </tr>
            `).join('') || '<tr><td colspan="5" style="text-align:center;color:#8892a0">No losers yet</td></tr>';
            
            // Trending
            document.getElementById('market-trending-body').innerHTML = (trending.coins || []).map(c => `
                <tr style="cursor:pointer" onclick="showCoinDetail('${c.token_address}')">
                    <td><strong>${c.symbol}</strong><br><small style="color:#8892a0">${c.name || ''}</small></td>
                    <td>${c.scan_count || 0}</td>
                    <td>${fmtNum(c.last_price_usd, 6)}</td>
                    <td><span class="badge badge-${c.signal}">${c.signal?.toUpperCase()}</span></td>
                    <td>${((c.confidence || 0) * 100).toFixed(0)}%</td>
                </tr>
            `).join('') || '<tr><td colspan="5" style="text-align:center;color:#8892a0">No trending coins yet</td></tr>';
        }

        async function loadDeployers() {
            const reputation = document.getElementById('reputation-filter').value;
            let url = '/api/deployers?limit=200';
            if (reputation) url += '&reputation=' + reputation;

            const res = await fetch(url);
            const data = await res.json();

            document.getElementById('deployers-count').textContent = data.count + ' deployers tracked';

            const trusted = data.deployers.filter(d => d.reputation === 'trusted').length;
            const rugger = data.deployers.filter(d => d.reputation === 'rugger').length;
            const suspect = data.deployers.filter(d => d.reputation === 'suspect').length;

            document.getElementById('deployers-stats').innerHTML = `
                <div class="stat-card"><div class="stat-value">${data.count || 0}</div><div class="stat-label">Total Deployers</div></div>
                <div class="stat-card"><div class="stat-value">${trusted}</div><div class="stat-label">Trusted</div></div>
                <div class="stat-card"><div class="stat-value">${suspect}</div><div class="stat-label">Suspect</div></div>
                <div class="stat-card"><div class="stat-value">${rugger}</div><div class="stat-label">Ruggers</div></div>
            `;

            document.getElementById('deployers-body').innerHTML = data.deployers.map(d => `
                <tr>
                    <td><code>${shortAddr(d.address)}</code></td>
                    <td><span class="badge badge-${d.reputation}">${d.reputation?.toUpperCase()}</span></td>
                    <td>${((d.reputation_score || 0) * 100).toFixed(0)}%</td>
                    <td>${d.total_tokens_deployed || 0}</td>
                    <td>${d.successful_tokens || 0}</td>
                    <td>${d.rugged_tokens || 0}</td>
                    <td>${timeAgo(d.first_seen_at)}</td>
                </tr>
            `).join('');
        }

        async function showDeployer(address) {
            // For now, just alert - could expand to show deployer detail page
            const res = await fetch('/api/deployers/' + address);
            const data = await res.json();
            if (data.error) {
                alert('Deployer not found');
                return;
            }
            alert(`Deployer: ${shortAddr(address)}\\nReputation: ${data.deployer.reputation}\\nTokens: ${data.deployer.total_tokens_deployed}\\nSuccess: ${data.deployer.successful_tokens}\\nRugs: ${data.deployer.rugged_tokens}`);
        }

        async function loadTrades() {
            const res = await fetch('/api/trades?limit=100');
            const data = await res.json();
            document.getElementById('trades-count').textContent = data.count + ' trades';

            document.getElementById('trades-body').innerHTML = data.trades.map(t => `
                <tr>
                    <td><strong>${t.symbol || '?'}</strong></td>
                    <td><span class="badge badge-${t.side === 'buy' ? 'buy' : 'sell'}">${t.side?.toUpperCase()}</span></td>
                    <td>${fmtNum(t.amount_usd)}</td>
                    <td>${fmtNum(t.entry_price, 6)}</td>
                    <td>${fmtNum(t.amount_usd)}</td>
                    <td>${t.is_paper ? 'Paper' : 'Live'}</td>
                    <td><span class="badge badge-${t.status}">${t.status?.toUpperCase()}</span></td>
                    <td>${timeAgo(t.created_at)}</td>
                </tr>
            `).join('') || '<tr><td colspan="8" style="text-align:center;color:#8892a0">No trades yet</td></tr>';
        }

        async function loadPerformance() {
            const res = await fetch('/api/performance');
            const data = await res.json();
            const s = data.summary || {};

            document.getElementById('performance-stats').innerHTML = `
                <div class="stat-card"><div class="stat-value">${fmtNum(s.current_balance)}</div><div class="stat-label">Balance</div></div>
                <div class="stat-card"><div class="stat-value">${s.total_coins_scanned || 0}</div><div class="stat-label">Coins Scanned</div></div>
                <div class="stat-card"><div class="stat-value">${s.bullish_signals || 0}</div><div class="stat-label">Bullish</div></div>
                <div class="stat-card"><div class="stat-value">${s.bearish_signals || 0}</div><div class="stat-label">Bearish</div></div>
                <div class="stat-card"><div class="stat-value">${s.total_deployers || 0}</div><div class="stat-label">Deployers</div></div>
                <div class="stat-card"><div class="stat-value">${s.trusted_deployers || 0}</div><div class="stat-label">Trusted</div></div>
                <div class="stat-card"><div class="stat-value">${s.total_trades || 0}</div><div class="stat-label">Total Trades</div></div>
                <div class="stat-card"><div class="stat-value">${s.buy_trades || 0}</div><div class="stat-label">Buys</div></div>
            `;
        }

        async function loadPositions() {
            const res = await fetch('/api/positions');
            const data = await res.json();
            const positions = data.positions || [];
            const summary = data.summary || {};
            
            document.getElementById('positions-count').textContent = `${positions.length} open positions`;
            
            // Portfolio summary stats
            const totalPnl = summary.total_pnl_usd || 0;
            const totalPnlPct = summary.total_pnl_pct || 0;
            const pnlColor = totalPnl >= 0 ? '#34d399' : '#f87171';
            
            document.getElementById('positions-stats').innerHTML = `
                <div class="stat-card"><div class="stat-value">$${fmtNum(summary.total_invested || 0)}</div><div class="stat-label">Total Invested</div></div>
                <div class="stat-card"><div class="stat-value">$${fmtNum(summary.total_current_value || 0)}</div><div class="stat-label">Current Value</div></div>
                <div class="stat-card"><div class="stat-value" style="color: ${pnlColor}">$${fmtNum(totalPnl)}</div><div class="stat-label">Total PNL</div></div>
                <div class="stat-card"><div class="stat-value" style="color: ${pnlColor}">${fmtPct(totalPnlPct)}</div><div class="stat-label">PNL %</div></div>
                <div class="stat-card"><div class="stat-value">${summary.position_count || 0}</div><div class="stat-label">Positions</div></div>
            `;
            
            document.getElementById('positions-body').innerHTML = positions.map(p => {
                const pnlColor = p.pnl_usd >= 0 ? 'positive' : 'negative';
                const txLink = p.tx_hash ? `<a href="https://solscan.io/tx/${p.tx_hash}" target="_blank" style="color: #00d4aa;">View</a>` : '-';
                return `
                    <tr>
                        <td><strong>${p.symbol}</strong></td>
                        <td>$${fmtNum(p.amount_usd)}</td>
                        <td>$${p.entry_price > 0 ? fmtNum(p.entry_price) : '-'}</td>
                        <td>$${p.current_price > 0 ? fmtNum(p.current_price) : '-'}</td>
                        <td class="${pnlColor}">$${fmtNum(p.pnl_usd)}</td>
                        <td class="${pnlColor}">${fmtPct(p.pnl_pct)}</td>
                        <td>${timeAgo(p.executed_at)}</td>
                        <td>${txLink}</td>
                    </tr>
                `;
            }).join('') || '<tr><td colspan="8" style="text-align:center;color:#8892a0">No open positions</td></tr>';
        }

        async function loadLogs() {
            const res = await fetch('/api/logs?limit=100');
            const data = await res.json();
            document.getElementById('logs-count').textContent = data.count + ' log entries';

            document.getElementById('logs-body').innerHTML = data.logs.map(l => `
                <tr>
                    <td>${timeAgo(l.created_at)}</td>
                    <td><span class="badge badge-${l.level === 'error' ? 'sell' : l.level === 'warning' ? 'hold' : 'buy'}">${l.level}</span></td>
                    <td>${l.event}</td>
                    <td>${l.message}</td>
                </tr>
            `).join('');
        }

        async function loadSettings() {
            // Load trading status
            const statusRes = await fetch('/api/trading/status');
            const statusData = await statusRes.json();
            const isLive = statusData.live_trading_enabled;
            const effectiveMode = statusData.effective_mode || (isLive ? 'live' : 'paper');
            
            document.getElementById('trading-status').textContent = effectiveMode.toUpperCase();
            document.getElementById('trading-status').style.color = isLive ? '#f87171' : '#00d4aa';
            
            document.getElementById('trading-indicator').style.background = isLive ? '#f87171' : '#00d4aa';
            document.getElementById('trading-text').textContent = isLive ? 'Live Trading Enabled' : `Paper Trading Active (AGENT_MODE=${statusData.agent_mode || 'paper'})`;
            document.getElementById('trading-text').style.color = isLive ? '#f87171' : '#00d4aa';
            
            // Load all settings
            const settingsRes = await fetch('/api/settings');
            const settingsData = await settingsRes.json();
            
            document.getElementById('settings-list').innerHTML = `
                <table>
                    <thead>
                        <tr><th>Key</th><th>Value</th><th>Type</th><th>Updated</th></tr>
                    </thead>
                    <tbody>
                        ${settingsData.settings.map(s => `
                            <tr>
                                <td><code>${s.key}</code></td>
                                <td>${s.value}</td>
                                <td>${s.value_type}</td>
                                <td>${timeAgo(s.updated_at)}</td>
                            </tr>
                        `).join('') || '<tr><td colspan="4" style="text-align:center;color:#8892a0">No settings saved yet</td></tr>'}
                    </tbody>
                </table>
            `;
        }

        async function toggleTrading() {
            const btn = document.getElementById('trading-toggle-btn');
            btn.disabled = true;
            btn.textContent = 'Toggling...';
            
            try {
                const res = await fetch('/api/trading/toggle', { method: 'POST' });
                const data = await res.json();
                
                const msgDiv = document.getElementById('trading-message');
                msgDiv.style.display = 'block';
                msgDiv.style.background = data.live_trading_enabled ? 'rgba(248, 113, 113, 0.1)' : 'rgba(0, 212, 170, 0.1)';
                msgDiv.style.color = data.live_trading_enabled ? '#f87171' : '#00d4aa';
                msgDiv.textContent = data.message;
                
                // Reload settings display
                await loadSettings();
                
                setTimeout(() => {
                    msgDiv.style.display = 'none';
                }, 3000);
            } catch (e) {
                const msgDiv = document.getElementById('trading-message');
                msgDiv.style.display = 'block';
                msgDiv.style.background = 'rgba(248, 113, 113, 0.1)';
                msgDiv.style.color = '#f87171';
                msgDiv.textContent = 'Error: ' + e.message;
            } finally {
                btn.disabled = false;
                btn.textContent = 'Toggle Trading';
            }
        }

        async function loadHealthBar() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                
                const scannerStatus = data.components?.scanner?.status || 'idle';
                const priceStatus = data.components?.price_refresh?.status || 'idle';
                const tradeStatus = data.components?.trading?.status || 'idle';
                
                document.getElementById('health-scanner').textContent = scannerStatus;
                document.getElementById('health-scanner-dot').className = 'health-dot ' + scannerStatus;
                
                document.getElementById('health-price').textContent = priceStatus;
                document.getElementById('health-price-dot').className = 'health-dot ' + priceStatus;
                
                document.getElementById('health-trade').textContent = tradeStatus;
                document.getElementById('health-trade-dot').className = 'health-dot ' + tradeStatus;
                
                document.getElementById('health-coins').textContent = data.counts?.tracked_coins || 0;
                document.getElementById('health-positions').textContent = data.counts?.open_positions || 0;
            } catch (e) {
                console.error('Health bar fetch failed:', e);
                document.getElementById('health-scanner').textContent = 'offline';
                document.getElementById('health-scanner-dot').className = 'health-dot offline';
                document.getElementById('health-price').textContent = 'offline';
                document.getElementById('health-price-dot').className = 'health-dot offline';
                document.getElementById('health-trade').textContent = 'offline';
                document.getElementById('health-trade-dot').className = 'health-dot offline';
            }
        }

        // Auto-refresh all visible panels every 30s
        function refreshActivePanel() {
            loadHealthBar();
            const panels = document.querySelectorAll('.panel.active');
            panels.forEach(panel => {
                const id = panel.id;
                if (id === 'watchlist-panel') loadWatchlist();
                if (id === 'market-panel') loadMarket();
                if (id === 'deployers-panel') loadDeployers();
                if (id === 'trades-panel') loadTrades();
                if (id === 'positions-panel') loadPositions();
                if (id === 'performance-panel') loadPerformance();
                if (id === 'logs-panel') loadLogs();
                if (id === 'settings-panel') loadSettings();
            });
        }

        // Initial load
        loadHealthBar();
        loadWatchlist();
        loadSettings();
        loadPositions();

        // Auto-refresh every 30s
        setInterval(refreshActivePanel, 30000);
    </script>
</body>
</html>"""

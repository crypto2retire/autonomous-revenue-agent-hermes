"""FastAPI dashboard and API for the crypto trading agent."""

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from typing import Optional

from database import DB, init_db

app = FastAPI(title="Crypto Trading Agent")


@app.on_event("startup")
async def startup():
    await init_db()


# ── Health ─────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "agent": "crypto-trading-agent"}


# ── Coins / Watchlist ──────────────────────────────────────────────

@app.get("/api/coins")
async def get_coins(
    signal: Optional[str] = None,
    min_score: Optional[float] = None,
    deployer: Optional[str] = None,
    is_rugged: Optional[bool] = None,
    limit: int = Query(100, ge=1, le=500),
):
    coins = await DB.get_all_coins(
        signal=signal,
        min_score=min_score,
        deployer_address=deployer,
        is_rugged=is_rugged,
        limit=limit,
    )
    # Build stats
    total = len(coins)
    buy_signals = sum(1 for c in coins if c.signal == "buy")
    sell_signals = sum(1 for c in coins if c.signal == "sell")
    bullish = sum(1 for c in coins if c.signal == "bullish")
    bearish = sum(1 for c in coins if c.signal == "bearish")
    avoid = sum(1 for c in coins if c.signal == "avoid")
    rugged = sum(1 for c in coins if c.is_rugged)
    top_gainer = max((c.price_change_pct for c in coins if c.price_change_pct is not None), default=0)
    
    stats = {
        "total_coins": total,
        "buy_signals": buy_signals,
        "sell_signals": sell_signals,
        "bullish_signals": bullish,
        "bearish_signals": bearish,
        "avoid_signals": avoid,
        "rugged_coins": rugged,
        "top_gainer_pct": top_gainer,
    }
    return {
        "coins": [c.to_dict() for c in coins],
        "stats": stats,
        "count": len(coins),
    }


@app.get("/api/coins/gainers")
async def get_gainers(limit: int = 20, min_gain_pct: float = 100.0):
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
async def get_trades(status: Optional[str] = None, limit: int = 100):
    trades = await DB.get_trades(status=status, limit=limit)
    return {"trades": [t.to_dict() for t in trades], "count": len(trades)}


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


# ── HTML Dashboard ─────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return """<!DOCTYPE html>
<html>
<head>
    <title>Crypto Trading Agent</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
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
            display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 15px; margin-bottom: 20px;
        }
        .stat-card {
            background: #111827; border: 1px solid #1a2332; border-radius: 8px;
            padding: 15px; text-align: center;
        }
        .stat-value { font-size: 1.6rem; font-weight: 700; color: #00d4aa; }
        .stat-label { font-size: 0.85rem; color: #8892a0; margin-top: 5px; }
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
        .filters { display: flex; gap: 10px; margin-bottom: 15px; flex-wrap: wrap; }
        .filters select, .filters input {
            padding: 6px 10px; border-radius: 4px; border: 1px solid #1a2332;
            background: #111827; color: #e0e6ed;
        }
        .deployer-info {
            background: #111827; border: 1px solid #1a2332; border-radius: 8px;
            padding: 15px; margin-bottom: 15px;
        }
        .deployer-info h3 { color: #00d4aa; margin-bottom: 10px; }
        .deployer-info p { margin: 5px 0; }
        @media (max-width: 768px) {
            .stats-grid { grid-template-columns: repeat(2, 1fr); }
            table { font-size: 0.8rem; }
            th, td { padding: 8px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🤖 Crypto Trading Agent</h1>
        <p class="subtitle">Autonomous scanner, analyzer &amp; executor</p>

        <div class="tabs">
            <div class="tab active" onclick="showTab('watchlist')">📊 Watchlist</div>
            <div class="tab" onclick="showTab('deployers')">👤 Deployers</div>
            <div class="tab" onclick="showTab('trades')">💰 Trades</div>
            <div class="tab" onclick="showTab('performance')">📈 Performance</div>
            <div class="tab" onclick="showTab('logs')">📝 Logs</div>
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
                        <th>Peak Gain</th>
                        <th>AI Score</th>
                        <th>Scans</th>
                        <th>Deployer</th>
                        <th>Last Seen</th>
                    </tr>
                </thead>
                <tbody id="watchlist-body"></tbody>
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
    </div>

    <script>
        function showTab(name) {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
            event.target.classList.add('active');
            document.getElementById(name + '-panel').classList.add('active');
            if (name === 'watchlist') loadWatchlist();
            if (name === 'deployers') loadDeployers();
            if (name === 'trades') loadTrades();
            if (name === 'performance') loadPerformance();
            if (name === 'logs') loadLogs();
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
            return '<span class="' + cls + '">' + (n >= 0 ? '+' : '') + n.toFixed(2) + '%</span>';
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

            const res = await fetch(url);
            const data = await res.json();

            document.getElementById('watchlist-count').textContent = data.count + ' coins tracked';

            const stats = data.stats;
            document.getElementById('watchlist-stats').innerHTML = `
                <div class="stat-card"><div class="stat-value">${stats.total_coins || 0}</div><div class="stat-label">Total Coins</div></div>
                <div class="stat-card"><div class="stat-value">${stats.buy_signals || 0}</div><div class="stat-label">Buy Signals</div></div>
                <div class="stat-card"><div class="stat-value">${stats.avoid_signals || 0}</div><div class="stat-label">Avoid</div></div>
                <div class="stat-card"><div class="stat-value">${stats.rugged_coins || 0}</div><div class="stat-label">Rugged</div></div>
            `;

            const tbody = document.getElementById('watchlist-body');
            tbody.innerHTML = data.coins.map(c => `
                <tr>
                    <td><strong>${c.symbol}</strong><br><small style="color:#8892a0">${c.name || ''}</small></td>
                    <td><span class="badge badge-${c.signal}">${c.signal?.toUpperCase()}</span></td>
                    <td>${fmtNum(c.last_price_usd || c.first_price_usd, 6)}</td>
                    <td>${fmtPct(c.peak_gain_pct)}</td>
                    <td>${((c.confidence || 0) * 100).toFixed(0)}%</td>
                    <td>${c.scan_count || 0}</td>
                    <td>${c.deployer_address ? '<a href="javascript:showDeployer(\'' + c.deployer_address + '\')">' + shortAddr(c.deployer_address) + '</a>' : '-'}</td>
                    <td>${timeAgo(c.last_seen_at)}</td>
                </tr>
            `).join('');
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

            const tbody = document.getElementById('deployers-body');
            tbody.innerHTML = data.deployers.map(d => `
                <tr>
                    <td><strong>${shortAddr(d.address)}</strong></td>
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
            // Switch to deployers tab and filter
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
            event.target.classList.add('active');
            document.getElementById('deployers-panel').classList.add('active');
            loadDeployers();
        }

        async function loadTrades() {
            const res = await fetch('/api/trades?limit=100');
            const data = await res.json();
            document.getElementById('trades-count').textContent = data.count + ' trades';

            document.getElementById('trades-body').innerHTML = data.trades.map(t => `
                <tr>
                    <td>${t.symbol}</td>
                    <td>${t.side?.toUpperCase()}</td>
                    <td>${fmtNum(t.amount)}</td>
                    <td>${fmtNum(t.price, 6)}</td>
                    <td>${fmtNum(t.total_value)}</td>
                    <td>${t.trade_type}</td>
                    <td><span class="badge badge-${t.status === 'completed' ? 'buy' : 'avoid'}">${t.status}</span></td>
                    <td>${timeAgo(t.created_at)}</td>
                </tr>
            `).join('');
        }

        async function loadPerformance() {
            const res = await fetch('/api/performance?hours=24');
            const data = await res.json();
            const s = data.summary;
            document.getElementById('performance-stats').innerHTML = `
                <div class="stat-card"><div class="stat-value">${fmtNum(s.current_balance)}</div><div class="stat-label">Current Balance</div></div>
                <div class="stat-card"><div class="stat-value">${s.total_trades || 0}</div><div class="stat-label">Total Trades</div></div>
                <div class="stat-card"><div class="stat-value">${s.buy_trades || 0}</div><div class="stat-label">Buys</div></div>
                <div class="stat-card"><div class="stat-value">${s.sell_trades || 0}</div><div class="stat-label">Sells</div></div>
                <div class="stat-card"><div class="stat-value">${fmtNum(s.total_volume)}</div><div class="stat-label">Total Volume</div></div>
                <div class="stat-card"><div class="stat-value">${s.total_coins_scanned || 0}</div><div class="stat-label">Coins Scanned</div></div>
                <div class="stat-card"><div class="stat-value">${s.total_deployers || 0}</div><div class="stat-label">Deployers</div></div>
                <div class="stat-card"><div class="stat-value">${s.trusted_deployers || 0}</div><div class="stat-label">Trusted</div></div>
            `;
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

        // Auto-refresh watchlist every 30s
        loadWatchlist();
        setInterval(() => {
            if (document.getElementById('watchlist-panel').classList.contains('active')) {
                loadWatchlist();
            }
        }, 30000);
    </script>
</body>
</html>"""

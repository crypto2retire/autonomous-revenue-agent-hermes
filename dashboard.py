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
    tags: Optional[str] = None,
    watching: Optional[bool] = None,
    min_change: Optional[float] = None,
    limit: int = Query(100, ge=1, le=500),
):
    coins = await DB.get_coins(
        signal=signal,
        tags=tags,
        is_watching=watching,
        min_price_change=min_change,
        limit=limit,
    )
    stats = await DB.get_coin_stats()
    return {
        "coins": [c.to_dict() for c in coins],
        "stats": stats,
        "count": len(coins),
    }


@app.get("/api/coins/gainers")
async def get_gainers(limit: int = 20):
    coins = await DB.get_coins(min_price_change=5.0, limit=limit)
    return {"coins": [c.to_dict() for c in coins]}


@app.get("/api/coins/losers")
async def get_losers(limit: int = 20):
    coins = await DB.get_coins(min_price_change=-100.0, limit=limit)
    losers = [c for c in coins if c.price_change_pct is not None and float(c.price_change_pct) < -5]
    return {"coins": [c.to_dict() for c in losers[:limit]]}


@app.get("/api/coins/trending")
async def get_trending(limit: int = 20):
    coins = await DB.get_coins(tags="trending", limit=limit)
    return {"coins": [c.to_dict() for c in coins]}


# ── Trades ─────────────────────────────────────────────────────────

@app.get("/api/trades")
async def get_trades(status: Optional[str] = None, limit: int = 100):
    trades = await DB.get_trades(status=status, limit=limit)
    return {"trades": [t.to_dict() for t in trades], "count": len(trades)}


# ── Performance ────────────────────────────────────────────────────

@app.get("/api/performance")
async def get_performance(days: int = 7):
    metrics = await DB.get_performance(days=days)
    return {"metrics": [m.to_dict() for m in metrics]}


# ── Logs ───────────────────────────────────────────────────────────

@app.get("/api/logs")
async def get_logs(event: Optional[str] = None, limit: int = 100):
    logs = await DB.get_logs(event=event, limit=limit)
    return {"logs": [l.to_dict() for l in logs], "count": len(logs)}


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
                    <option value="hold">Hold</option>
                    <option value="avoid">Avoid</option>
                </select>
                <select id="tag-filter" onchange="loadWatchlist()">
                    <option value="">All Tags</option>
                    <option value="trending">Trending</option>
                    <option value="gainer">Gainers</option>
                    <option value="new">New</option>
                </select>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>Symbol</th>
                        <th>Signal</th>
                        <th>Price</th>
                        <th>Change</th>
                        <th>Volume</th>
                        <th>Liquidity</th>
                        <th>Confidence</th>
                        <th>Scans</th>
                        <th>Last Seen</th>
                    </tr>
                </thead>
                <tbody id="watchlist-body"></tbody>
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
                        <th>Trade ID</th>
                        <th>Symbol</th>
                        <th>Side</th>
                        <th>Status</th>
                        <th>Amount</th>
                        <th>Entry</th>
                        <th>PnL</th>
                        <th>Signal</th>
                        <th>Created</th>
                    </tr>
                </thead>
                <tbody id="trades-body"></tbody>
            </table>
        </div>

        <!-- Performance Panel -->
        <div class="panel" id="performance-panel">
            <div class="refresh-bar">
                <span>Last 7 days</span>
                <button class="btn" onclick="loadPerformance()">Refresh</button>
            </div>
            <div id="performance-chart"></div>
            <table>
                <thead>
                    <tr>
                        <th>Period</th>
                        <th>Trades</th>
                        <th>Wins</th>
                        <th>Losses</th>
                        <th>Win Rate</th>
                        <th>Total PnL</th>
                        <th>Avg Size</th>
                    </tr>
                </thead>
                <tbody id="performance-body"></tbody>
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
                        <th>Symbol</th>
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

        async function loadWatchlist() {
            const signal = document.getElementById('signal-filter').value;
            const tags = document.getElementById('tag-filter').value;
            let url = '/api/coins?limit=200';
            if (signal) url += '&signal=' + signal;
            if (tags) url += '&tags=' + tags;

            const res = await fetch(url);
            const data = await res.json();

            document.getElementById('watchlist-count').textContent = data.count + ' coins tracked';

            const stats = data.stats;
            document.getElementById('watchlist-stats').innerHTML = `
                <div class="stat-card"><div class="stat-value">${stats.total_coins || 0}</div><div class="stat-label">Total Coins</div></div>
                <div class="stat-card"><div class="stat-value">${stats.watching || 0}</div><div class="stat-label">Watching</div></div>
                <div class="stat-card"><div class="stat-value">${stats.buy_signals || 0}</div><div class="stat-label">Buy Signals</div></div>
                <div class="stat-card"><div class="stat-value">${fmtPct(stats.top_gainer_pct)}</div><div class="stat-label">Top Gainer</div></div>
            `;

            const tbody = document.getElementById('watchlist-body');
            tbody.innerHTML = data.coins.map(c => `
                <tr>
                    <td><strong>${c.symbol}</strong><br><small style="color:#8892a0">${c.name || ''}</small></td>
                    <td><span class="badge badge-${c.signal}">${c.signal?.toUpperCase()}</span></td>
                    <td>${fmtNum(c.last_price_usd, 6)}</td>
                    <td>${fmtPct(c.price_change_pct)}</td>
                    <td>${fmtNum(c.volume_24h)}</td>
                    <td>${fmtNum(c.liquidity_usd)}</td>
                    <td>${(c.confidence * 100).toFixed(0)}%</td>
                    <td>${c.scan_count}</td>
                    <td>${timeAgo(c.last_seen_at)}</td>
                </tr>
            `).join('');
        }

        async function loadTrades() {
            const res = await fetch('/api/trades?limit=100');
            const data = await res.json();
            document.getElementById('trades-count').textContent = data.count + ' trades';

            document.getElementById('trades-body').innerHTML = data.trades.map(t => `
                <tr>
                    <td><code>${t.trade_id}</code></td>
                    <td>${t.symbol}</td>
                    <td>${t.side?.toUpperCase()}</td>
                    <td><span class="badge badge-${t.status === 'executed' ? 'buy' : t.status === 'closed' ? 'hold' : 'avoid'}">${t.status}</span></td>
                    <td>${fmtNum(t.amount_usd)}</td>
                    <td>${fmtNum(t.entry_price, 6)}</td>
                    <td>${fmtPct(t.pnl_pct)}</td>
                    <td><span class="badge badge-${t.signal}">${t.signal?.toUpperCase()}</span></td>
                    <td>${timeAgo(t.created_at)}</td>
                </tr>
            `).join('');
        }

        async function loadPerformance() {
            const res = await fetch('/api/performance?days=7');
            const data = await res.json();
            document.getElementById('performance-body').innerHTML = data.metrics.map(m => `
                <tr>
                    <td>${m.period}</td>
                    <td>${m.trades_count}</td>
                    <td class="positive">${m.winning_trades}</td>
                    <td class="negative">${m.losing_trades}</td>
                    <td>${(m.win_rate * 100).toFixed(1)}%</td>
                    <td>${fmtNum(m.total_pnl_usd)}</td>
                    <td>${fmtNum(m.avg_trade_size)}</td>
                </tr>
            `).join('');
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
                    <td>${l.symbol || '-'}</td>
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

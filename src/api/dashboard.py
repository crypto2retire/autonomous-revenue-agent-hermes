"""FastAPI dashboard for agent management.

Provides endpoints for:
- Wallet management (view, update, switch)
- Agent status and controls
- Opportunity viewing
- Trade history
- Visual HTML dashboard
"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from decimal import Decimal
from datetime import datetime

from src.wallet.manager import WalletManager
from src.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

app = FastAPI(title="Autonomous Revenue Agent Dashboard")

wallet_manager = WalletManager()


# --- Pydantic Models ---

class WalletUpdateRequest(BaseModel):
    private_key: str = Field(..., description="New wallet private key")
    save: bool = Field(default=True, description="Save to config file")


class WalletUpdateResponse(BaseModel):
    success: bool
    address: str
    message: str


class WalletInfo(BaseModel):
    configured: bool
    address: str | None
    eth_balance: str | None
    message: str | None


class AgentStatus(BaseModel):
    status: str
    wallet_configured: bool
    wallet_address: str | None
    mode: str
    trading_enabled: bool = True
    version: str = "1.0.0"


class ModeUpdateRequest(BaseModel):
    mode: str = Field(..., description="Agent mode: paper or live")


class ModeUpdateResponse(BaseModel):
    success: bool
    mode: str
    message: str


class TradingToggleResponse(BaseModel):
    success: bool
    trading_enabled: bool
    message: str


# --- HTML Dashboard ---

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Autonomous Revenue Agent Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0a0e1a;
            color: #e0e6ed;
            min-height: 100vh;
        }
        .container { max-width: 1400px; margin: 0 auto; padding: 20px; }
        header {
            background: linear-gradient(135deg, #1a1f2e 0%, #0f1419 100%);
            border-bottom: 1px solid #2a3f5f;
            padding: 20px 0;
            margin-bottom: 30px;
        }
        header h1 {
            font-size: 28px;
            background: linear-gradient(90deg, #00d4ff, #7b2cbf);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        header .subtitle { color: #6b7b8f; font-size: 14px; margin-top: 5px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }
        .card {
            background: #111827;
            border: 1px solid #1e3a5f;
            border-radius: 12px;
            padding: 20px;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        .card:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 25px rgba(0, 212, 255, 0.1);
        }
        .card h2 {
            font-size: 16px;
            color: #00d4ff;
            margin-bottom: 15px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .status-badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
        }
        .status-running { background: rgba(0, 255, 136, 0.15); color: #00ff88; }
        .status-paper { background: rgba(0, 212, 255, 0.15); color: #00d4ff; }
        .status-live { background: rgba(255, 68, 68, 0.15); color: #ff4444; }
        .metric {
            display: flex;
            justify-content: space-between;
            padding: 10px 0;
            border-bottom: 1px solid #1e3a5f;
        }
        .metric:last-child { border-bottom: none; }
        .metric-label { color: #6b7b8f; font-size: 13px; }
        .metric-value { color: #e0e6ed; font-weight: 600; font-size: 14px; }
        .address {
            font-family: 'SF Mono', monospace;
            font-size: 12px;
            background: #0a0e1a;
            padding: 8px 12px;
            border-radius: 6px;
            border: 1px solid #1e3a5f;
            word-break: break-all;
        }
        .btn {
            background: linear-gradient(135deg, #00d4ff, #7b2cbf);
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            transition: opacity 0.2s;
            width: 100%;
            margin-top: 10px;
        }
        .btn:hover { opacity: 0.9; }
        .btn-secondary {
            background: #1e3a5f;
            margin-top: 8px;
        }
        .input-group { margin-top: 15px; }
        .input-group label {
            display: block;
            color: #6b7b8f;
            font-size: 12px;
            margin-bottom: 5px;
        }
        .input-group input {
            width: 100%;
            padding: 10px;
            background: #0a0e1a;
            border: 1px solid #1e3a5f;
            border-radius: 6px;
            color: #e0e6ed;
            font-family: 'SF Mono', monospace;
            font-size: 12px;
        }
        .input-group input:focus {
            outline: none;
            border-color: #00d4ff;
        }
        .log-entry {
            font-family: 'SF Mono', monospace;
            font-size: 11px;
            padding: 6px 0;
            border-bottom: 1px solid #1e3a5f;
            color: #8b9bb4;
        }
        .log-entry:last-child { border-bottom: none; }
        .log-time { color: #00d4ff; }
        .log-info { color: #00ff88; }
        .log-error { color: #ff4444; }
        .log-warn { color: #ffaa00; }
        .refresh-indicator {
            display: inline-block;
            width: 8px;
            height: 8px;
            background: #00ff88;
            border-radius: 50%;
            margin-left: 8px;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.3; }
        }
        .tabs {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            border-bottom: 1px solid #1e3a5f;
            padding-bottom: 10px;
            flex-wrap: wrap;
        }
        .tab {
            padding: 8px 16px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
            color: #6b7b8f;
            transition: all 0.2s;
        }
        .tab:hover { color: #e0e6ed; background: #1e3a5f; }
        .tab.active { color: #00d4ff; background: rgba(0, 212, 255, 0.1); }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        .opportunity-row, .trade-row, .position-row, .tx-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px;
            background: #0a0e1a;
            border-radius: 8px;
            margin-bottom: 8px;
            border: 1px solid #1e3a5f;
        }
        .opportunity-token, .trade-token, .position-token { font-weight: 600; color: #00d4ff; }
        .opportunity-signal, .trade-status, .position-status {
            font-size: 12px;
            padding: 2px 8px;
            border-radius: 4px;
        }
        .signal-buy { background: rgba(0, 255, 136, 0.15); color: #00ff88; }
        .signal-sell { background: rgba(255, 68, 68, 0.15); color: #ff4444; }
        .signal-hold { background: rgba(255, 170, 0, 0.15); color: #ffaa00; }
        .status-executed { background: rgba(0, 255, 136, 0.15); color: #00ff88; }
        .status-pending { background: rgba(255, 170, 0, 0.15); color: #ffaa00; }
        .status-failed { background: rgba(255, 68, 68, 0.15); color: #ff4444; }
        .status-closed { background: rgba(0, 212, 255, 0.15); color: #00d4ff; }
        .data-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }
        .data-table th {
            text-align: left;
            padding: 10px;
            color: #6b7b8f;
            border-bottom: 1px solid #1e3a5f;
            font-weight: 600;
        }
        .data-table td {
            padding: 10px;
            border-bottom: 1px solid #1e3a5f;
        }
        .data-table tr:hover td { background: rgba(0, 212, 255, 0.05); }
        .pnl-positive { color: #00ff88; }
        .pnl-negative { color: #ff4444; }
        .chart-container {
            height: 250px;
            background: #0a0e1a;
            border-radius: 8px;
            border: 1px solid #1e3a5f;
            padding: 15px;
            margin-top: 15px;
        }
        @media (max-width: 768px) {
            .grid { grid-template-columns: 1fr; }
            header h1 { font-size: 22px; }
            .tabs { gap: 5px; }
            .tab { padding: 6px 10px; font-size: 12px; }
        }
    </style>
</head>
<body>
    <header>
        <div class="container">
            <h1>Autonomous Revenue Agent</h1>
            <div class="subtitle">AI-powered crypto opportunity scanner &middot; <span class="refresh-indicator"></span> Live</div>
        </div>
    </header>

    <div class="container">
        <div class="tabs">
            <div class="tab active" onclick="showTab('overview')">Overview</div>
            <div class="tab" onclick="showTab('trades')">Trades</div>
            <div class="tab" onclick="showTab('positions')">Positions</div>
            <div class="tab" onclick="showTab('opportunities')">Opportunities</div>
            <div class="tab" onclick="showTab('performance')">Performance</div>
            <div class="tab" onclick="showTab('history')">History</div>
            <div class="tab" onclick="showTab('wallet')">Wallet</div>
            <div class="tab" onclick="showTab('logs')">Logs</div>
        </div>

        <!-- Overview Tab -->
        <div id="overview" class="tab-content active">
            <div class="grid">
                <div class="card">
                    <h2>Agent Status</h2>
                    <div class="metric">
                        <span class="metric-label">Status</span>
                        <span class="status-badge status-running">Running</span>
                    </div>
                    <div class="metric">
                        <span class="metric-label">Mode</span>
                        <span class="status-badge status-paper" id="mode-badge">Paper Trading</span>
                    </div>
                    <div class="metric">
                        <span class="metric-label">Trading</span>
                        <span class="status-badge status-running" id="trading-badge">Enabled</span>
                    </div>
                    <div class="metric">
                        <span class="metric-label">Version</span>
                        <span class="metric-value">1.0.0</span>
                    </div>
                    <div class="metric">
                        <span class="metric-label">Uptime</span>
                        <span class="metric-value" id="uptime">--</span>
                    </div>
                </div>

                <div class="card">
                    <h2>Wallet</h2>
                    <div class="metric">
                        <span class="metric-label">Address</span>
                        <span class="metric-value" id="wallet-address">--</span>
                    </div>
                    <div class="metric">
                        <span class="metric-label">ETH Balance</span>
                        <span class="metric-value" id="eth-balance">--</span>
                    </div>
                    <div class="metric">
                        <span class="metric-label">Network</span>
                        <span class="metric-value">Base</span>
                    </div>
                </div>

                <div class="card">
                    <h2>Performance</h2>
                    <div class="metric">
                        <span class="metric-label">Total PnL</span>
                        <span class="metric-value" id="total-pnl" style="color: #00ff88;">+$0.00</span>
                    </div>
                    <div class="metric">
                        <span class="metric-label">Trades</span>
                        <span class="metric-value" id="total-trades">0</span>
                    </div>
                    <div class="metric">
                        <span class="metric-label">Win Rate</span>
                        <span class="metric-value" id="win-rate">--</span>
                    </div>
                    <div class="metric">
                        <span class="metric-label">Open Positions</span>
                        <span class="metric-value" id="open-positions">0</span>
                    </div>
                    <div class="metric">
                        <span class="metric-label">Unrealized PnL</span>
                        <span class="metric-value" id="unrealized-pnl">$0.00</span>
                    </div>
                </div>

                <div class="card">
                    <h2>Quick Actions</h2>
                    <button class="btn" onclick="refreshAll()">Refresh All</button>
                    <button class="btn btn-secondary" id="mode-btn" onclick="switchMode()">Switch to Live Mode</button>
                    <button class="btn btn-secondary" id="trading-btn" onclick="toggleTrading()" style="background: #ff4444;">Stop Trading</button>
                    <button class="btn btn-secondary" onclick="location.reload()">Reload Dashboard</button>
                </div>
            </div>
        </div>

        <!-- Trades Tab -->
        <div id="trades" class="tab-content">
            <div class="card">
                <h2>Trade History</h2>
                <div style="margin-bottom: 15px; display: flex; gap: 10px;">
                    <select id="trade-filter" onchange="fetchTrades()" style="background: #0a0e1a; border: 1px solid #1e3a5f; color: #e0e6ed; padding: 8px 12px; border-radius: 6px;">
                        <option value="">All Status</option>
                        <option value="executed">Executed</option>
                        <option value="closed">Closed</option>
                        <option value="failed">Failed</option>
                        <option value="pending">Pending</option>
                    </select>
                    <button class="btn" onclick="fetchTrades()" style="width: auto; margin-top: 0;">Refresh</button>
                </div>
                <div id="trades-container">
                    <div style="color: #6b7b8f; text-align: center; padding: 40px;">Loading trades...</div>
                </div>
            </div>
        </div>

        <!-- Positions Tab -->
        <div id="positions" class="tab-content">
            <div class="card">
                <h2>Open Positions</h2>
                <div id="positions-summary" style="margin-bottom: 15px; padding: 12px; background: #0a0e1a; border-radius: 8px;">
                    <span style="color: #6b7b8f;">Loading...</span>
                </div>
                <div id="positions-container">
                    <div style="color: #6b7b8f; text-align: center; padding: 40px;">Loading positions...</div>
                </div>
            </div>
        </div>

        <!-- Opportunities Tab -->
        <div id="opportunities" class="tab-content">
            <div class="card">
                <h2>Latest Opportunities</h2>
                <button class="btn" onclick="fetchOpportunities()" style="margin-bottom: 15px;">Refresh</button>
                <div id="opportunities-list">
                    <div style="color: #6b7b8f; text-align: center; padding: 40px;">Loading opportunities...</div>
                </div>
            </div>
        </div>

        <!-- Performance Tab -->
        <div id="performance" class="tab-content">
            <div class="grid">
                <div class="card">
                    <h2>Latest Cycle</h2>
                    <div id="performance-latest">
                        <div style="color: #6b7b8f; text-align: center; padding: 20px;">Loading...</div>
                    </div>
                </div>
                <div class="card">
                    <h2>Performance History</h2>
                    <div id="performance-history">
                        <div style="color: #6b7b8f; text-align: center; padding: 20px;">Loading...</div>
                    </div>
                </div>
            </div>
        </div>

        <!-- History Tab -->
        <div id="history" class="tab-content">
            <div class="card">
                <h2>Wallet Balance History</h2>
                <div class="chart-container">
                    <canvas id="wallet-chart"></canvas>
                </div>
                <div style="margin-top: 15px;">
                    <button class="btn btn-secondary" onclick="fetchWalletHistory(24)" style="width: auto; display: inline-block;">24h</button>
                    <button class="btn btn-secondary" onclick="fetchWalletHistory(168)" style="width: auto; display: inline-block;">7d</button>
                    <button class="btn btn-secondary" onclick="fetchWalletHistory(720)" style="width: auto; display: inline-block;">30d</button>
                </div>
            </div>
            <div class="card" style="margin-top: 20px;">
                <h2>Transaction History</h2>
                <div id="transactions-container">
                    <div style="color: #6b7b8f; text-align: center; padding: 40px;">Loading transactions...</div>
                </div>
            </div>
        </div>

        <!-- Wallet Tab -->
        <div id="wallet" class="tab-content">
            <div class="grid">
                <div class="card">
                    <h2>Current Wallet</h2>
                    <div class="metric">
                        <span class="metric-label">Address</span>
                    </div>
                    <div class="address" id="current-address">Loading...</div>
                    <div class="metric" style="margin-top: 15px;">
                        <span class="metric-label">ETH Balance</span>
                        <span class="metric-value" id="wallet-eth">--</span>
                    </div>
                </div>

                <div class="card">
                    <h2>Switch Wallet</h2>
                    <div class="input-group">
                        <label>Private Key</label>
                        <input type="password" id="private-key" placeholder="0x...">
                    </div>
                    <button class="btn" onclick="updateWallet()">Update Wallet</button>
                    <button class="btn btn-secondary" onclick="reloadWallet()">Reload from Config</button>
                    <div id="wallet-message" style="margin-top: 10px; font-size: 13px;"></div>
                </div>
            </div>
        </div>

        <!-- Logs Tab -->
        <div id="logs" class="tab-content">
            <div class="card">
                <h2>Agent Logs</h2>
                <div style="margin-bottom: 15px; display: flex; gap: 10px;">
                    <select id="log-filter" onchange="fetchLogs()" style="background: #0a0e1a; border: 1px solid #1e3a5f; color: #e0e6ed; padding: 8px 12px; border-radius: 6px;">
                        <option value="">All Levels</option>
                        <option value="INFO">INFO</option>
                        <option value="WARNING">WARNING</option>
                        <option value="ERROR">ERROR</option>
                        <option value="CRITICAL">CRITICAL</option>
                    </select>
                    <button class="btn" onclick="fetchLogs()" style="width: auto; margin-top: 0;">Refresh</button>
                </div>
                <div id="logs-container">
                    <div class="log-entry"><span class="log-time">--:--:--</span> Dashboard loaded</div>
                </div>
            </div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script>
        // Tab switching
        function showTab(tabName) {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
            event.target.classList.add('active');
            document.getElementById(tabName).classList.add('active');
            // Load data for tab
            if (tabName === 'trades') fetchTrades();
            if (tabName === 'positions') fetchPositions();
            if (tabName === 'opportunities') fetchOpportunities();
            if (tabName === 'performance') fetchPerformance();
            if (tabName === 'history') { fetchWalletHistory(168); fetchTransactions(); }
            if (tabName === 'logs') fetchLogs();
        }

        // Fetch status
        async function refreshStatus() {
            try {
                const res = await fetch('/status');
                const data = await res.json();
                document.getElementById('wallet-address').textContent = data.wallet_address ? data.wallet_address.slice(0, 10) + '...' + data.wallet_address.slice(-6) : '--';
                document.getElementById('current-address').textContent = data.wallet_address || 'Not configured';
                
                const modeBadge = document.getElementById('mode-badge');
                if (data.mode === 'live') {
                    modeBadge.textContent = 'LIVE TRADING';
                    modeBadge.className = 'status-badge status-live';
                } else {
                    modeBadge.textContent = 'Paper Trading';
                    modeBadge.className = 'status-badge status-paper';
                }
                const tradingBadge = document.getElementById('trading-badge');
                const tradingBtn = document.getElementById('trading-btn');
                if (data.trading_enabled === false) {
                    tradingBadge.textContent = 'DISABLED';
                    tradingBadge.className = 'status-badge status-live';
                    tradingBtn.textContent = 'Resume Trading';
                    tradingBtn.style.background = '#00ff88';
                } else {
                    tradingBadge.textContent = 'Enabled';
                    tradingBadge.className = 'status-badge status-running';
                    tradingBtn.textContent = 'Stop Trading';
                    tradingBtn.style.background = '#ff4444';
                }
            } catch (e) {
                console.error('Failed to fetch status:', e);
            }

            try {
                const res = await fetch('/wallet');
                const data = await res.json();
                document.getElementById('eth-balance').textContent = data.eth_balance ? parseFloat(data.eth_balance).toFixed(6) + ' ETH' : '--';
                document.getElementById('wallet-eth').textContent = data.eth_balance ? parseFloat(data.eth_balance).toFixed(6) + ' ETH' : '--';
            } catch (e) {
                console.error('Failed to fetch wallet:', e);
            }
        }

        // Fetch trades
        async function fetchTrades() {
            const container = document.getElementById('trades-container');
            const filter = document.getElementById('trade-filter').value;
            container.innerHTML = '<div style="color: #6b7b8f; text-align: center; padding: 40px;">Loading...</div>';
            
            try {
                const url = filter ? `/trades?status=${filter}&limit=50` : '/trades?limit=50';
                const res = await fetch(url);
                const data = await res.json();
                
                if (data.error) {
                    container.innerHTML = `<div style="color: #ff4444; text-align: center; padding: 40px;">Error: ${data.error}</div>`;
                    return;
                }
                
                if (data.count === 0) {
                    container.innerHTML = '<div style="color: #6b7b8f; text-align: center; padding: 40px;">No trades yet.</div>';
                    return;
                }
                
                let html = '<table class="data-table"><thead><tr><th>Token</th><th>Type</th><th>Status</th><th>Entry</th><th>Exit</th><th>Size</th><th>PnL</th><th>Mode</th><th>Time</th></tr></thead><tbody>';
                data.trades.forEach(t => {
                    const pnlClass = t.pnl_usd > 0 ? 'pnl-positive' : t.pnl_usd < 0 ? 'pnl-negative' : '';
                    const statusClass = `status-${t.status}`;
                    html += `<tr>
                        <td><strong>${t.token_symbol}</strong><br><span style="font-size: 11px; color: #6b7b8f;">${t.token_address?.slice(0, 8)}...</span></td>
                        <td>${t.trade_type?.toUpperCase()}</td>
                        <td><span class="${statusClass}">${t.status?.toUpperCase()}</span></td>
                        <td>$${t.entry_price?.toFixed(8) || '--'}</td>
                        <td>$${t.exit_price?.toFixed(8) || '--'}</td>
                        <td>$${t.position_size_usd?.toFixed(2) || '--'}</td>
                        <td class="${pnlClass}">${t.pnl_usd ? (t.pnl_usd > 0 ? '+' : '') + '$' + t.pnl_usd.toFixed(2) : '--'}</td>
                        <td><span class="status-badge ${t.mode === 'live' ? 'status-live' : 'status-paper'}">${t.mode?.toUpperCase()}</span></td>
                        <td>${t.created_at ? new Date(t.created_at).toLocaleString() : '--'}</td>
                    </tr>`;
                });
                html += '</tbody></table>';
                container.innerHTML = html;
                
                // Update overview stats
                if (data.stats) {
                    document.getElementById('total-trades').textContent = data.stats.total_trades || 0;
                    document.getElementById('win-rate').textContent = data.stats.win_rate ? data.stats.win_rate.toFixed(1) + '%' : '--';
                    const pnlEl = document.getElementById('total-pnl');
                    const pnl = data.stats.total_pnl_usd || 0;
                    pnlEl.textContent = (pnl >= 0 ? '+' : '') + '$' + pnl.toFixed(2);
                    pnlEl.style.color = pnl >= 0 ? '#00ff88' : '#ff4444';
                }
            } catch (e) {
                container.innerHTML = `<div style="color: #ff4444; text-align: center; padding: 40px;">Error: ${e.message}</div>`;
            }
        }

        // Fetch positions
        async function fetchPositions() {
            const container = document.getElementById('positions-container');
            const summary = document.getElementById('positions-summary');
            container.innerHTML = '<div style="color: #6b7b8f; text-align: center; padding: 40px;">Loading...</div>';
            
            try {
                const res = await fetch('/positions');
                const data = await res.json();
                
                if (data.error) {
                    container.innerHTML = `<div style="color: #ff4444; text-align: center; padding: 40px;">Error: ${data.error}</div>`;
                    return;
                }
                
                summary.innerHTML = `<span style="color: #6b7b8f;">Open Positions: <strong style="color: #00d4ff;">${data.summary?.open_positions || 0}</strong> &nbsp;|&nbsp; Unrealized PnL: <strong style="color: ${(data.summary?.unrealized_pnl_usd || 0) >= 0 ? '#00ff88' : '#ff4444'};">${(data.summary?.unrealized_pnl_usd || 0) >= 0 ? '+' : ''}$${(data.summary?.unrealized_pnl_usd || 0).toFixed(2)}</strong></span>`;
                document.getElementById('open-positions').textContent = data.summary?.open_positions || 0;
                document.getElementById('unrealized-pnl').textContent = (data.summary?.unrealized_pnl_usd || 0) >= 0 ? '+' : '' + '$' + (data.summary?.unrealized_pnl_usd || 0).toFixed(2);
                document.getElementById('unrealized-pnl').style.color = (data.summary?.unrealized_pnl_usd || 0) >= 0 ? '#00ff88' : '#ff4444';
                
                if (data.count === 0) {
                    container.innerHTML = '<div style="color: #6b7b8f; text-align: center; padding: 40px;">No open positions.</div>';
                    return;
                }
                
                let html = '<table class="data-table"><thead><tr><th>Token</th><th>Entry Price</th><th>Current</th><th>Size</th><th>Unrealized PnL</th><th>Opened</th></tr></thead><tbody>';
                data.positions.forEach(p => {
                    const pnlClass = p.unrealized_pnl_usd > 0 ? 'pnl-positive' : p.unrealized_pnl_usd < 0 ? 'pnl-negative' : '';
                    html += `<tr>
                        <td><strong>${p.token_symbol}</strong></td>
                        <td>$${p.entry_price?.toFixed(8) || '--'}</td>
                        <td>$${p.current_price?.toFixed(8) || '--'}</td>
                        <td>$${p.position_size_usd?.toFixed(2) || '--'}</td>
                        <td class="${pnlClass}">${p.unrealized_pnl_usd ? (p.unrealized_pnl_usd > 0 ? '+' : '') + '$' + p.unrealized_pnl_usd.toFixed(2) : '--'} (${p.unrealized_pnl_pct?.toFixed(2) || 0}%)</td>
                        <td>${p.opened_at ? new Date(p.opened_at).toLocaleString() : '--'}</td>
                    </tr>`;
                });
                html += '</tbody></table>';
                container.innerHTML = html;
            } catch (e) {
                container.innerHTML = `<div style="color: #ff4444; text-align: center; padding: 40px;">Error: ${e.message}</div>`;
            }
        }

        // Fetch opportunities
        async function fetchOpportunities() {
            const container = document.getElementById('opportunities-list');
            container.innerHTML = '<div style="color: #6b7b8f; text-align: center; padding: 40px;">Loading...</div>';
            
            try {
                const res = await fetch('/opportunities');
                const data = await res.json();
                
                if (data.error) {
                    container.innerHTML = `<div style="color: #ff4444; text-align: center; padding: 40px;">Error: ${data.error}</div>`;
                    return;
                }
                
                if (data.count === 0) {
                    container.innerHTML = '<div style="color: #6b7b8f; text-align: center; padding: 40px;">No opportunities found yet.</div>';
                    return;
                }
                
                let html = '<table class="data-table"><thead><tr><th>Token</th><th>Signal</th><th>Confidence</th><th>Price</th><th>Volume</th><th>Liquidity</th><th>Holders</th><th>Discovered</th></tr></thead><tbody>';
                data.opportunities.forEach(opp => {
                    html += `<tr>
                        <td><strong>${opp.token_symbol}</strong><br><span style="font-size: 11px; color: #6b7b8f;">${opp.chain}</span></td>
                        <td><span class="opportunity-signal signal-${opp.ai_signal}">${opp.ai_signal?.toUpperCase() || 'UNKNOWN'}</span></td>
                        <td>${opp.ai_confidence ? (opp.ai_confidence * 100).toFixed(0) + '%' : '--'}</td>
                        <td>$${opp.current_price_usd?.toFixed(8) || '0'}</td>
                        <td>$${opp.volume_24h_usd?.toLocaleString() || '0'}</td>
                        <td>$${opp.liquidity_usd?.toLocaleString() || '0'}</td>
                        <td>${opp.total_holders?.toLocaleString() || '--'}</td>
                        <td>${opp.discovered_at ? new Date(opp.discovered_at).toLocaleString() : '--'}</td>
                    </tr>`;
                });
                html += '</tbody></table>';
                container.innerHTML = html;
            } catch (e) {
                container.innerHTML = `<div style="color: #ff4444; text-align: center; padding: 40px;">Error: ${e.message}</div>`;
            }
        }

        // Fetch performance
        async function fetchPerformance() {
            const latestContainer = document.getElementById('performance-latest');
            const historyContainer = document.getElementById('performance-history');
            latestContainer.innerHTML = '<div style="color: #6b7b8f; text-align: center; padding: 20px;">Loading...</div>';
            historyContainer.innerHTML = '<div style="color: #6b7b8f; text-align: center; padding: 20px;">Loading...</div>';
            
            try {
                const res = await fetch('/performance?limit=30');
                const data = await res.json();
                
                if (data.latest) {
                    latestContainer.innerHTML = `
                        <div class="metric"><span class="metric-label">Total PnL</span><span class="metric-value" style="color: ${data.latest.total_pnl_usd >= 0 ? '#00ff88' : '#ff4444'}">${data.latest.total_pnl_usd >= 0 ? '+' : ''}$${data.latest.total_pnl_usd.toFixed(2)}</span></div>
                        <div class="metric"><span class="metric-label">Trades Executed</span><span class="metric-value">${data.latest.trades_executed || 0}</span></div>
                        <div class="metric"><span class="metric-label">Winning Trades</span><span class="metric-value" style="color: #00ff88;">${data.latest.winning_trades || 0}</span></div>
                        <div class="metric"><span class="metric-label">Losing Trades</span><span class="metric-value" style="color: #ff4444;">${data.latest.losing_trades || 0}</span></div>
                        <div class="metric"><span class="metric-label">Cycle Count</span><span class="metric-value">${data.latest.cycle_count || 0}</span></div>
                    `;
                } else {
                    latestContainer.innerHTML = '<div style="color: #6b7b8f; text-align: center;">No performance data yet.</div>';
                }
                
                if (data.metrics && data.metrics.length > 0) {
                    let html = '<table class="data-table"><thead><tr><th>Period</th><th>Trades</th><th>Win/Loss</th><th>PnL</th><th>Cycles</th></tr></thead><tbody>';
                    data.metrics.forEach(m => {
                        const pnlClass = m.total_pnl_usd > 0 ? 'pnl-positive' : m.total_pnl_usd < 0 ? 'pnl-negative' : '';
                        html += `<tr>
                            <td>${m.period_start ? new Date(m.period_start).toLocaleDateString() : '--'}</td>
                            <td>${m.trades_executed || 0}</td>
                            <td>${m.winning_trades || 0} / ${m.losing_trades || 0}</td>
                            <td class="${pnlClass}">${m.total_pnl_usd ? (m.total_pnl_usd > 0 ? '+' : '') + '$' + m.total_pnl_usd.toFixed(2) : '$0.00'}</td>
                            <td>${m.cycle_count || 0}</td>
                        </tr>`;
                    });
                    html += '</tbody></table>';
                    historyContainer.innerHTML = html;
                } else {
                    historyContainer.innerHTML = '<div style="color: #6b7b8f; text-align: center;">No history yet.</div>';
                }
            } catch (e) {
                latestContainer.innerHTML = `<div style="color: #ff4444; text-align: center;">Error: ${e.message}</div>`;
                historyContainer.innerHTML = `<div style="color: #ff4444; text-align: center;">Error: ${e.message}</div>`;
            }
        }

        // Fetch wallet history
        let walletChart = null;
        async function fetchWalletHistory(hours = 168) {
            try {
                const res = await fetch(`/wallet/history?hours=${hours}`);
                const data = await res.json();
                
                if (data.history && data.history.length > 0) {
                    const labels = data.history.map(h => new Date(h.snapshot_at).toLocaleDateString() + ' ' + new Date(h.snapshot_at).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}));
                    const balances = data.history.map(h => h.total_balance_usd);
                    
                    const ctx = document.getElementById('wallet-chart').getContext('2d');
                    
                    if (walletChart) walletChart.destroy();
                    
                    walletChart = new Chart(ctx, {
                        type: 'line',
                        data: {
                            labels: labels,
                            datasets: [{
                                label: 'Balance (USD)',
                                data: balances,
                                borderColor: '#00d4ff',
                                backgroundColor: 'rgba(0, 212, 255, 0.1)',
                                fill: true,
                                tension: 0.4,
                                pointRadius: 2,
                            }]
                        },
                        options: {
                            responsive: true,
                            maintainAspectRatio: false,
                            plugins: {
                                legend: { display: false },
                            },
                            scales: {
                                x: { display: false },
                                y: {
                                    grid: { color: '#1e3a5f' },
                                    ticks: { color: '#6b7b8f', callback: v => '$' + v.toFixed(2) }
                                }
                            }
                        }
                    });
                }
            } catch (e) {
                console.error('Wallet history fetch failed:', e);
            }
        }

        // Fetch transactions
        async function fetchTransactions() {
            const container = document.getElementById('transactions-container');
            container.innerHTML = '<div style="color: #6b7b8f; text-align: center; padding: 40px;">Loading...</div>';
            
            try {
                const res = await fetch('/transactions?limit=50');
                const data = await res.json();
                
                if (data.count === 0) {
                    container.innerHTML = '<div style="color: #6b7b8f; text-align: center; padding: 40px;">No transactions yet.</div>';
                    return;
                }
                
                let html = '<table class="data-table"><thead><tr><th>Type</th><th>Token</th><th>Status</th><th>Amount In</th><th>Amount Out</th><th>Fee</th><th>Mode</th><th>Time</th></tr></thead><tbody>';
                data.transactions.forEach(tx => {
                    html += `<tr>
                        <td>${tx.tx_type?.toUpperCase()}</td>
                        <td>${tx.token_symbol || tx.token_address?.slice(0, 8) + '...'}</td>
                        <td><span class="status-${tx.status}">${tx.status?.toUpperCase()}</span></td>
                        <td>${tx.amount_in?.toFixed(6) || '--'}</td>
                        <td>${tx.amount_out?.toFixed(6) || '--'}</td>
                        <td>$${tx.fee_usd?.toFixed(4) || '--'}</td>
                        <td><span class="status-badge ${tx.mode === 'live' ? 'status-live' : 'status-paper'}">${tx.mode?.toUpperCase()}</span></td>
                        <td>${tx.created_at ? new Date(tx.created_at).toLocaleString() : '--'}</td>
                    </tr>`;
                });
                html += '</tbody></table>';
                container.innerHTML = html;
            } catch (e) {
                container.innerHTML = `<div style="color: #ff4444; text-align: center; padding: 40px;">Error: ${e.message}</div>`;
            }
        }

        // Fetch logs
        async function fetchLogs() {
            const container = document.getElementById('logs-container');
            const filter = document.getElementById('log-filter').value;
            container.innerHTML = '<div style="color: #6b7b8f; text-align: center; padding: 20px;">Loading...</div>';
            
            try {
                const url = filter ? `/logs?level=${filter}&limit=100` : '/logs?limit=100';
                const res = await fetch(url);
                const data = await res.json();
                
                if (data.count === 0) {
                    container.innerHTML = '<div style="color: #6b7b8f; text-align: center; padding: 20px;">No logs yet.</div>';
                    return;
                }
                
                container.innerHTML = '';
                data.logs.forEach(log => {
                    const colorClass = log.level === 'ERROR' ? 'log-error' : log.level === 'WARNING' ? 'log-warn' : log.level === 'CRITICAL' ? 'log-error' : 'log-info';
                    const time = log.created_at ? new Date(log.created_at).toLocaleTimeString() : '--:--:--';
                    container.innerHTML += `<div class="log-entry"><span class="log-time">${time}</span> <span class="${colorClass}">[${log.level}] ${log.event}</span> ${log.message || ''}</div>`;
                });
            } catch (e) {
                container.innerHTML = `<div style="color: #ff4444; text-align: center; padding: 20px;">Error: ${e.message}</div>`;
            }
        }

        // Update wallet
        async function updateWallet() {
            const key = document.getElementById('private-key').value;
            if (!key) {
                document.getElementById('wallet-message').textContent = 'Please enter a private key';
                document.getElementById('wallet-message').style.color = '#ff4444';
                return;
            }

            try {
                const res = await fetch('/wallet/update', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ private_key: key, save: true })
                });
                const data = await res.json();
                document.getElementById('wallet-message').textContent = data.message;
                document.getElementById('wallet-message').style.color = data.success ? '#00ff88' : '#ff4444';
                if (data.success) refreshStatus();
            } catch (e) {
                document.getElementById('wallet-message').textContent = 'Error: ' + e.message;
                document.getElementById('wallet-message').style.color = '#ff4444';
            }
        }

        // Reload wallet
        async function reloadWallet() {
            try {
                const res = await fetch('/wallet/reload', { method: 'POST' });
                const data = await res.json();
                document.getElementById('wallet-message').textContent = data.message;
                document.getElementById('wallet-message').style.color = data.success ? '#00ff88' : '#ff4444';
                if (data.success) refreshStatus();
            } catch (e) {
                document.getElementById('wallet-message').textContent = 'Error: ' + e.message;
                document.getElementById('wallet-message').style.color = '#ff4444';
            }
        }

        // Switch mode
        async function switchMode() {
            const isLive = document.getElementById('mode-badge').textContent === 'LIVE TRADING';
            const newMode = isLive ? 'paper' : 'live';
            const confirmMsg = isLive 
                ? 'Switch to PAPER mode? This will stop using real funds.' 
                : 'Switch to LIVE mode? This will use REAL FUNDS for trading!';
            
            if (!confirm(confirmMsg)) return;
            
            try {
                const res = await fetch('/mode', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ mode: newMode })
                });
                const data = await res.json();
                alert(data.message);
                if (data.success) {
                    document.getElementById('mode-btn').textContent = isLive ? 'Switch to Live Mode' : 'Switch to Paper Mode';
                    refreshStatus();
                }
            } catch (e) {
                alert('Error: ' + e.message);
            }
        }

        // Toggle trading
        async function toggleTrading() {
            const isEnabled = document.getElementById('trading-badge').textContent === 'Enabled';
            const action = isEnabled ? 'stop' : 'start';
            const confirmMsg = isEnabled 
                ? 'STOP all trading? The agent will keep running but will NOT execute any trades.' 
                : 'RESUME trading? The agent will start executing trades again.';
            
            if (!confirm(confirmMsg)) return;
            
            try {
                const res = await fetch('/trading/' + action, { method: 'POST' });
                const data = await res.json();
                alert(data.message);
                if (data.success) {
                    refreshStatus();
                }
            } catch (e) {
                alert('Error: ' + e.message);
            }
        }

        // Refresh all data
        async function refreshAll() {
            await refreshStatus();
            await fetchTrades();
            await fetchPositions();
        }

        // Auto-refresh
        refreshStatus();
        setInterval(refreshStatus, 30000);
        setInterval(() => {
            const activeTab = document.querySelector('.tab-content.active').id;
            if (activeTab === 'trades') fetchTrades();
            if (activeTab === 'positions') fetchPositions();
            if (activeTab === 'opportunities') fetchOpportunities();
            if (activeTab === 'performance') fetchPerformance();
            if (activeTab === 'logs') fetchLogs();
        }, 30000);
    </script>
</body>
</html>
"""


# --- API Endpoints ---

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the visual HTML dashboard."""
    return DASHBOARD_HTML


@app.get("/status", response_model=AgentStatus)
async def get_status():
    """Get current agent status."""
    from main import agent
    return AgentStatus(
        status="running",
        wallet_configured=wallet_manager.is_configured(),
        wallet_address=wallet_manager.get_address(),
        mode=settings.agent_mode,
        trading_enabled=agent.is_trading_enabled if hasattr(agent, 'is_trading_enabled') else True,
    )


@app.get("/wallet", response_model=WalletInfo)
async def get_wallet():
    """Get current wallet information."""
    if not wallet_manager.is_configured():
        return WalletInfo(
            configured=False,
            address=None,
            eth_balance=None,
            message="No wallet configured",
        )

    try:
        balance = wallet_manager.get_balance()
        return WalletInfo(
            configured=True,
            address=wallet_manager.get_address(),
            eth_balance=str(balance) if balance else "0",
            message=None,
        )
    except Exception as e:
        return WalletInfo(
            configured=True,
            address=wallet_manager.get_address(),
            eth_balance=None,
            message=f"Error fetching balance: {str(e)}",
        )


@app.post("/wallet/update", response_model=WalletUpdateResponse)
async def update_wallet(request: WalletUpdateRequest):
    """Update wallet private key (hot reload)."""
    try:
        wallet_manager.update_wallet(request.private_key, save=request.save)
        return WalletUpdateResponse(
            success=True,
            address=wallet_manager.get_address(),
            message=f"Wallet updated to {wallet_manager.get_address()}",
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/wallet/reload", response_model=WalletUpdateResponse)
async def reload_wallet():
    """Reload wallet from config file."""
    try:
        wallet_manager.reload_wallet()
        return WalletUpdateResponse(
            success=True,
            address=wallet_manager.get_address(),
            message=f"Wallet reloaded: {wallet_manager.get_address()}",
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/wallet/balance/{token_address}")
async def get_token_balance(token_address: str):
    """Get balance of a specific token."""
    if not wallet_manager.is_configured():
        raise HTTPException(status_code=400, detail="No wallet configured")

    try:
        balance = wallet_manager.get_token_balance(token_address)
        return {
            "token_address": token_address,
            "balance": str(balance),
            "wallet": wallet_manager.get_address(),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/opportunities")
async def get_opportunities():
    """Get latest discovered opportunities from DB."""
    try:
        from src.db import AgentRepository
        db = AgentRepository()
        await db.initialize()
        
        opps = await db.list_opportunities(limit=50)
        
        results = []
        for opp in opps:
            results.append({
                "id": opp.opp_id,
                "token_address": opp.token_address,
                "token_symbol": opp.token_symbol,
                "token_name": opp.token_name,
                "chain": opp.chain,
                "current_price_usd": float(opp.price_usd) if opp.price_usd else None,
                "price_change_24h_pct": float(opp.price_change_24h_pct) if opp.price_change_24h_pct else None,
                "market_cap_usd": float(opp.market_cap_usd) if opp.market_cap_usd else None,
                "ai_signal": opp.ai_signal,
                "ai_confidence": float(opp.ai_confidence) if opp.ai_confidence else None,
                "ai_risk_level": opp.ai_risk_level,
                "trade_executed": opp.trade_executed,
                "discovered_at": opp.discovered_at.isoformat() if opp.discovered_at else None,
                "volume_24h_usd": float(opp.volume_24h_usd) if opp.volume_24h_usd else None,
                "liquidity_usd": float(opp.liquidity_usd) if opp.liquidity_usd else None,
                "buy_sell_ratio": float(opp.buy_sell_ratio) if opp.buy_sell_ratio else None,
                "total_holders": opp.total_holders,
            })
        
        await db.close()
        
        return {
            "opportunities": results,
            "count": len(results),
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error("opportunities_fetch_failed", error=str(e))
        return {
            "opportunities": [],
            "count": 0,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat(),
        }


@app.get("/trades")
async def get_trades(status: str = None, limit: int = 100, offset: int = 0):
    """Get trade history from DB."""
    try:
        from src.db import AgentRepository
        db = AgentRepository()
        await db.initialize()
        
        trades = await db.list_trades(status=status, limit=limit, offset=offset)
        
        results = []
        for t in trades:
            results.append({
                "trade_id": t.trade_id,
                "token_symbol": t.token_symbol,
                "token_address": t.token_address,
                "chain": t.chain,
                "trade_type": t.trade_type,
                "status": t.status,
                "mode": t.mode,
                "entry_price": float(t.entry_price) if t.entry_price else None,
                "exit_price": float(t.exit_price) if t.exit_price else None,
                "position_size_usd": float(t.position_size_usd) if t.position_size_usd else None,
                "pnl_usd": float(t.pnl_usd) if t.pnl_usd else None,
                "pnl_pct": float(t.pnl_pct) if t.pnl_pct else None,
                "ai_signal": t.ai_signal,
                "ai_confidence": float(t.ai_confidence) if t.ai_confidence else None,
                "ai_risk_level": t.ai_risk_level,
                "executed_at": t.executed_at.isoformat() if t.executed_at else None,
                "closed_at": t.closed_at.isoformat() if t.closed_at else None,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            })
        
        # Get stats
        stats = await db.get_trade_stats()
        await db.close()
        
        return {
            "trades": results,
            "count": len(results),
            "stats": stats,
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error("trades_fetch_failed", error=str(e))
        return {"trades": [], "count": 0, "stats": {}, "error": str(e)}


@app.get("/positions")
async def get_positions():
    """Get current open positions from DB."""
    try:
        from src.db import AgentRepository
        db = AgentRepository()
        await db.initialize()
        
        positions = await db.list_open_positions(status="open")
        summary = await db.get_position_summary()
        
        results = []
        for p in positions:
            results.append({
                "position_id": p.position_id,
                "trade_id": p.trade_id,
                "token_symbol": p.token_symbol,
                "token_address": p.token_address,
                "chain": p.chain,
                "entry_price": float(p.entry_price),
                "current_price": float(p.current_price) if p.current_price else None,
                "position_size_usd": float(p.position_size_usd),
                "unrealized_pnl_usd": float(p.unrealized_pnl_usd),
                "unrealized_pnl_pct": float(p.unrealized_pnl_pct),
                "opened_at": p.opened_at.isoformat() if p.opened_at else None,
                "last_updated": p.last_updated.isoformat() if p.last_updated else None,
            })
        
        await db.close()
        
        return {
            "positions": results,
            "summary": summary,
            "count": len(results),
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error("positions_fetch_failed", error=str(e))
        return {"positions": [], "summary": {}, "count": 0, "error": str(e)}


@app.get("/transactions")
async def get_transactions(trade_id: str = None, limit: int = 100, offset: int = 0):
    """Get transaction history from DB."""
    try:
        from src.db import AgentRepository
        db = AgentRepository()
        await db.initialize()
        
        txs = await db.list_transactions(trade_id=trade_id, limit=limit, offset=offset)
        
        results = []
        for tx in txs:
            results.append({
                "tx_id": tx.tx_id,
                "trade_id": tx.trade_id,
                "tx_type": tx.tx_type,
                "status": tx.status,
                "token_symbol": tx.token_symbol,
                "token_address": tx.token_address,
                "amount_in": float(tx.amount_in) if tx.amount_in else None,
                "amount_out": float(tx.amount_out) if tx.amount_out else None,
                "amount_usd": float(tx.amount_usd) if tx.amount_usd else None,
                "fee_usd": float(tx.fee_usd) if tx.fee_usd else None,
                "tx_hash": tx.tx_hash,
                "mode": tx.mode,
                "created_at": tx.created_at.isoformat() if tx.created_at else None,
                "confirmed_at": tx.confirmed_at.isoformat() if tx.confirmed_at else None,
            })
        
        await db.close()
        
        return {
            "transactions": results,
            "count": len(results),
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error("transactions_fetch_failed", error=str(e))
        return {"transactions": [], "count": 0, "error": str(e)}


@app.get("/performance")
async def get_performance(period_type: str = "day", limit: int = 30):
    """Get performance metrics history from DB."""
    try:
        from src.db import AgentRepository
        db = AgentRepository()
        await db.initialize()
        
        metrics = await db.get_performance_history(period_type=period_type, limit=limit)
        latest = await db.get_latest_performance()
        
        results = []
        for m in metrics:
            results.append({
                "metric_id": m.metric_id,
                "period_type": m.period_type,
                "period_start": m.period_start.isoformat() if m.period_start else None,
                "period_end": m.period_end.isoformat() if m.period_end else None,
                "trades_executed": m.trades_executed,
                "trades_closed": m.trades_closed,
                "winning_trades": m.winning_trades,
                "losing_trades": m.losing_trades,
                "total_pnl_usd": float(m.total_pnl_usd) if m.total_pnl_usd else 0,
                "total_fees_usd": float(m.total_fees_usd) if m.total_fees_usd else 0,
                "starting_balance_usd": float(m.starting_balance_usd) if m.starting_balance_usd else None,
                "ending_balance_usd": float(m.ending_balance_usd) if m.ending_balance_usd else None,
                "open_positions_count": m.open_positions_count,
                "opportunities_found": m.opportunities_found,
                "opportunities_executed": m.opportunities_executed,
                "service_revenue_usd": float(m.service_revenue_usd) if m.service_revenue_usd else 0,
                "cycle_count": m.cycle_count,
                "trading_enabled": m.trading_enabled,
                "survival_mode": m.survival_mode,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            })
        
        latest_data = None
        if latest:
            latest_data = {
                "metric_id": latest.metric_id,
                "period_type": latest.period_type,
                "total_pnl_usd": float(latest.total_pnl_usd) if latest.total_pnl_usd else 0,
                "trades_executed": latest.trades_executed,
                "winning_trades": latest.winning_trades,
                "losing_trades": latest.losing_trades,
                "cycle_count": latest.cycle_count,
            }
        
        await db.close()
        
        return {
            "metrics": results,
            "latest": latest_data,
            "count": len(results),
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error("performance_fetch_failed", error=str(e))
        return {"metrics": [], "latest": None, "count": 0, "error": str(e)}


@app.get("/wallet/history")
async def get_wallet_history(hours: int = 168):
    """Get wallet balance history from DB."""
    try:
        from src.db import AgentRepository
        db = AgentRepository()
        await db.initialize()
        
        history = await db.get_wallet_history(
            wallet_address=settings.base_wallet_address,
            hours=hours,
        )
        
        results = []
        for snap in history:
            results.append({
                "eth_balance": float(snap.eth_balance) if snap.eth_balance else 0,
                "eth_price_usd": float(snap.eth_price_usd) if snap.eth_price_usd else 0,
                "total_balance_usd": float(snap.total_balance_usd) if snap.total_balance_usd else 0,
                "snapshot_at": snap.snapshot_at.isoformat() if snap.snapshot_at else None,
            })
        
        await db.close()
        
        return {
            "history": results,
            "count": len(results),
            "wallet": settings.base_wallet_address,
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error("wallet_history_fetch_failed", error=str(e))
        return {"history": [], "count": 0, "error": str(e)}


@app.get("/logs")
async def get_logs(level: str = None, limit: int = 200, offset: int = 0):
    """Get agent logs from DB."""
    try:
        from src.db import AgentRepository
        db = AgentRepository()
        await db.initialize()
        
        logs = await db.list_logs(level=level, limit=limit, offset=offset)
        
        results = []
        for log in logs:
            results.append({
                "log_id": log.log_id,
                "logger_name": log.logger_name,
                "level": log.level,
                "event": log.event,
                "message": log.message,
                "cycle": log.cycle,
                "token_address": log.token_address,
                "trade_id": log.trade_id,
                "tx_hash": log.tx_hash,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            })
        
        await db.close()
        
        return {
            "logs": results,
            "count": len(results),
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error("logs_fetch_failed", error=str(e))
        return {"logs": [], "count": 0, "error": str(e)}


@app.get("/health")
async def health_check():
    """Health check endpoint for Fly.io."""
    return {"status": "healthy"}


@app.post("/mode", response_model=ModeUpdateResponse)
async def update_mode(request: ModeUpdateRequest):
    """Switch agent between paper and live trading mode."""
    if request.mode not in ("paper", "live"):
        raise HTTPException(
            status_code=400,
            detail="Invalid mode. Must be 'paper' or 'live'"
        )

    try:
        # Update settings
        settings.agent_mode = request.mode

        # Update environment variable for persistence
        import os
        os.environ["AGENT_MODE"] = request.mode

        logger.critical(
            "agent_mode_changed",
            mode=request.mode,
            wallet=wallet_manager.get_address(),
        )

        return ModeUpdateResponse(
            success=True,
            mode=request.mode,
            message=f"Agent switched to {request.mode.upper()} mode. "
                    + ("REAL FUNDS WILL BE USED!" if request.mode == "live" else "Simulated trading only."),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/trading/stop", response_model=TradingToggleResponse)
async def stop_trading():
    """Stop trading - agent keeps running but won't execute trades."""
    try:
        from main import agent
        if agent:
            agent.disable_trading()
            return TradingToggleResponse(
                success=True,
                trading_enabled=False,
                message="Trading STOPPED. Agent is still running but will NOT execute any trades.",
            )
        else:
            return TradingToggleResponse(
                success=False,
                trading_enabled=True,
                message="Agent not initialized yet.",
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/trading/start", response_model=TradingToggleResponse)
async def start_trading():
    """Resume trading."""
    try:
        from main import agent
        if agent:
            agent.enable_trading()
            return TradingToggleResponse(
                success=True,
                trading_enabled=True,
                message="Trading RESUMED. Agent will execute trades again.",
            )
        else:
            return TradingToggleResponse(
                success=False,
                trading_enabled=False,
                message="Agent not initialized yet.",
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

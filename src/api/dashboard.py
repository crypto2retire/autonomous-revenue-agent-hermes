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
    version: str = "1.0.0"


class ModeUpdateRequest(BaseModel):
    mode: str = Field(..., description="Agent mode: paper or live")


class ModeUpdateResponse(BaseModel):
    success: bool
    mode: str
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
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
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
        .opportunity-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px;
            background: #0a0e1a;
            border-radius: 8px;
            margin-bottom: 8px;
            border: 1px solid #1e3a5f;
        }
        .opportunity-token { font-weight: 600; color: #00d4ff; }
        .opportunity-signal { font-size: 12px; padding: 2px 8px; border-radius: 4px; }
        .signal-buy { background: rgba(0, 255, 136, 0.15); color: #00ff88; }
        .signal-sell { background: rgba(255, 68, 68, 0.15); color: #ff4444; }
        .signal-hold { background: rgba(255, 170, 0, 0.15); color: #ffaa00; }
        @media (max-width: 768px) {
            .grid { grid-template-columns: 1fr; }
            header h1 { font-size: 22px; }
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
            <div class="tab" onclick="showTab('wallet')">Wallet</div>
            <div class="tab" onclick="showTab('opportunities')">Opportunities</div>
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
                        <span class="metric-value" style="color: #00ff88;">+$0.00</span>
                    </div>
                    <div class="metric">
                        <span class="metric-label">Trades</span>
                        <span class="metric-value">0</span>
                    </div>
                    <div class="metric">
                        <span class="metric-label">Win Rate</span>
                        <span class="metric-value">--</span>
                    </div>
                    <div class="metric">
                        <span class="metric-label">Opportunities</span>
                        <span class="metric-value" id="opportunity-count">0</span>
                    </div>
                </div>

                <div class="card">
                    <h2>Quick Actions</h2>
                    <button class="btn" onclick="refreshStatus()">Refresh Status</button>
                    <button class="btn btn-secondary" id="mode-btn" onclick="switchMode()">Switch to Live Mode</button>
                    <button class="btn btn-secondary" onclick="location.reload()">Reload Dashboard</button>
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

        <!-- Opportunities Tab -->
        <div id="opportunities" class="tab-content">
            <div class="card">
                <h2>Latest Opportunities</h2>
                <button class="btn" onclick="fetchOpportunities()" style="margin-bottom: 15px;">Scan Now</button>
                <div id="opportunities-list">
                    <div class="opportunity-row">
                        <span style="color: #6b7b8f;">Click "Scan Now" to discover opportunities</span>
                    </div>
                </div>
            </div>
        </div>

        <!-- Logs Tab -->
        <div id="logs" class="tab-content">
            <div class="card">
                <h2>Recent Logs</h2>
                <div id="logs-container">
                    <div class="log-entry"><span class="log-time">--:--:--</span> Dashboard loaded</div>
                </div>
            </div>
        </div>
    </div>

    <script>
        // Tab switching
        function showTab(tabName) {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
            event.target.classList.add('active');
            document.getElementById(tabName).classList.add('active');
        }

        // Fetch status
        async function refreshStatus() {
            try {
                const res = await fetch('/status');
                const data = await res.json();
                document.getElementById('wallet-address').textContent = data.wallet_address ? data.wallet_address.slice(0, 10) + '...' + data.wallet_address.slice(-6) : '--';
                document.getElementById('current-address').textContent = data.wallet_address || 'Not configured';
                
                // Update mode badge
                const modeBadge = document.getElementById('mode-badge');
                if (data.mode === 'live') {
                    modeBadge.textContent = 'LIVE TRADING';
                    modeBadge.className = 'status-badge status-live';
                } else {
                    modeBadge.textContent = 'Paper Trading';
                    modeBadge.className = 'status-badge status-paper';
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

        // Fetch opportunities
        async function fetchOpportunities() {
            const container = document.getElementById('opportunities-list');
            container.innerHTML = '<div class="opportunity-row"><span style="color: #6b7b8f;">Scanning...</span></div>';
            
            try {
                const res = await fetch('/opportunities');
                const data = await res.json();
                
                if (data.error) {
                    container.innerHTML = `<div class="opportunity-row"><span style="color: #ff4444;">Error: ${data.error}</span></div>`;
                    return;
                }
                
                if (data.count === 0) {
                    container.innerHTML = '<div class="opportunity-row"><span style="color: #6b7b8f;">No opportunities found yet. Try again in a few minutes.</span></div>';
                    return;
                }
                
                container.innerHTML = data.opportunities.map(opp => `
                    <div class="opportunity-row">
                        <div>
                            <div class="opportunity-token">${opp.token_symbol} <span style="color: #6b7b8f; font-size: 11px;">${opp.chain}</span></div>
                            <div style="font-size: 11px; color: #6b7b8f; margin-top: 2px;">$${opp.current_price_usd?.toFixed(8) || '0'} | Vol: $${opp.volume_24h_usd?.toLocaleString() || '0'}</div>
                        </div>
                        <div style="text-align: right;">
                            <span class="opportunity-signal signal-${opp.ai_signal}">${opp.ai_signal?.toUpperCase() || 'UNKNOWN'}</span>
                            <div style="font-size: 11px; color: #6b7b8f; margin-top: 2px;">${opp.ai_confidence ? (opp.ai_confidence * 100).toFixed(0) + '%' : ''} confidence</div>
                        </div>
                    </div>
                `).join('');
                
                document.getElementById('opportunity-count').textContent = data.count;
            } catch (e) {
                container.innerHTML = `<div class="opportunity-row"><span style="color: #ff4444;">Error: ${e.message}</span></div>`;
            }
        }

        // Auto-refresh
        refreshStatus();
        setInterval(refreshStatus, 30000);

        // Add log entry
        function addLog(level, message) {
            const container = document.getElementById('logs-container');
            const time = new Date().toLocaleTimeString();
            const colorClass = level === 'error' ? 'log-error' : level === 'warn' ? 'log-warn' : 'log-info';
            container.innerHTML = `<div class="log-entry"><span class="log-time">${time}</span> <span class="${colorClass}">${message}</span></div>` + container.innerHTML;
            if (container.children.length > 50) container.lastChild.remove();
        }

        addLog('info', 'Dashboard connected');
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
    return AgentStatus(
        status="running",
        wallet_configured=wallet_manager.is_configured(),
        wallet_address=wallet_manager.get_address(),
        mode=settings.agent_mode,
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
    """Get latest discovered opportunities."""
    try:
        # Import scanner to get latest opportunities
        from src.opportunity import OpportunityScanner
        from src.venice import VeniceClient
        
        venice = VeniceClient()
        scanner = OpportunityScanner(venice)
        opportunities = await scanner.scan()
        
        # Convert to JSON-serializable format
        results = []
        for opp in opportunities:
            results.append({
                "id": opp.id,
                "token_address": opp.token_address,
                "token_symbol": opp.token_symbol,
                "token_name": opp.token_name,
                "chain": opp.chain,
                "current_price_usd": float(opp.current_price_usd),
                "price_change_24h_pct": float(opp.price_change_24h_pct),
                "market_cap_usd": float(opp.market_cap_usd) if opp.market_cap_usd else None,
                "ai_signal": opp.ai_signal,
                "ai_confidence": float(opp.ai_confidence) if opp.ai_confidence else None,
                "ai_risk_level": opp.ai_risk_level,
                "status": opp.status.value,
                "discovered_at": opp.discovered_at.isoformat() if opp.discovered_at else None,
                "volume_24h_usd": float(opp.volume_metrics.volume_24h_usd) if opp.volume_metrics else None,
                "liquidity_usd": float(opp.volume_metrics.liquidity_usd) if opp.volume_metrics else None,
                "buy_sell_ratio": float(opp.volume_metrics.buy_sell_ratio) if opp.volume_metrics else None,
                "total_holders": opp.holder_metrics.total_holders if opp.holder_metrics else None,
            })
        
        await scanner.close()
        
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

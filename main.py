"""Crypto Trading Agent - Entry point.

Runs:
1. FastAPI dashboard server (port 8000)
2. Background scanner loop (Buy Agent)
3. Background position manager loop (Sell Agent)
4. Background wallet monitor loop
5. Background pump.fun scanner
"""

import asyncio
import os

import uvicorn

from config import get_settings
from database import DB
from scanner import Scanner
from executor import Executor
from position_manager import PositionManager
from wallet_monitor import WalletMonitor
from dashboard import app
from pumpfun_scanner import PumpFunScanner

settings = get_settings()


async def run_scanner():
    """Background token scanner (Buy Agent)."""
    scanner = Scanner()
    try:
        await scanner.run()
    finally:
        await scanner.close()


async def run_position_manager():
    """Background position manager (Sell Agent)."""
    pm = PositionManager()
    try:
        await pm.run()
    finally:
        await pm.close()


async def run_wallet_monitor():
    """Background wallet monitor."""
    wm = WalletMonitor()
    try:
        await wm.run()
    finally:
        await wm.close()


async def run_pumpfun_scanner():
    """Background pump.fun launch scanner."""
    pf = PumpFunScanner()
    try:
        await pf.run()
    finally:
        await pf.close()


async def run_backup():
    """Backup DB to persistent volume every 5 minutes."""
    while True:
        await asyncio.sleep(300)  # 5 minutes
        try:
            await DB.backup()
        except Exception as e:
            print(f"Backup error: {e}")


async def run_price_history_cleanup():
    """Delete old price history older than 24h to keep table small."""
    while True:
        await asyncio.sleep(3600)  # every hour
        try:
            await DB.cleanup_old_price_history()
        except Exception as e:
            print(f"Price history cleanup error: {e}")


async def run_server():
    """FastAPI dashboard server."""
    config = uvicorn.Config(
        app,
        host=settings.host,
        port=settings.port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    """Start everything."""
    # Initialize database
    await DB.init()
    await DB.log_event("info", "agent_started", "Crypto trading agent starting up — Buy Agent + Sell Agent + Wallet Monitor + Pump.fun Scanner")

    # Run all components concurrently
    tasks = [
        run_scanner(),
        run_position_manager(),
        run_wallet_monitor(),
        run_pumpfun_scanner(),
        run_server(),
    ]

    # Only run backup if using SQLite (PostgreSQL doesn't need it)
    database_url = settings.database_url.get_secret_value()
    if database_url.startswith("sqlite"):
        tasks.append(run_backup())
        tasks.append(run_price_history_cleanup())

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())

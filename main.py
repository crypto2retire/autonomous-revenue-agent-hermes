"""Crypto Trading Agent - Entry point.

Runs:
1. FastAPI dashboard server (port 8000)
2. Background scanner loop
3. Background position manager loop
"""

import asyncio
import os

import uvicorn

from config import get_settings
from database import DB
from scanner import Scanner
from executor import Executor
from dashboard import app

settings = get_settings()


async def run_scanner():
    """Background token scanner."""
    scanner = Scanner()
    try:
        await scanner.run()
    finally:
        await scanner.close()


async def run_executor():
    """Background trade executor / position manager."""
    executor = Executor()
    try:
        await executor.run()
    finally:
        await executor.close()


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
    await DB.log_event("info", "agent_started", "Crypto trading agent starting up")

    # Run scanner, executor, and server concurrently
    await asyncio.gather(
        run_scanner(),
        run_executor(),
        run_server(),
    )


if __name__ == "__main__":
    asyncio.run(main())

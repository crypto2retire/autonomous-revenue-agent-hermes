"""Entry point for the autonomous revenue agent."""

import asyncio
import signal
import sys

from src.survival import SurvivalLoop
from src.api.dashboard import app
from src.utils.logger import configure_logging, get_logger

logger = get_logger(__name__)

# Global agent instance for dashboard access
agent = None


async def run_dashboard(host="0.0.0.0", port=8000):
    """Run FastAPI dashboard server."""
    import uvicorn
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    """Main entry point — runs survival loop + dashboard concurrently."""
    global agent
    configure_logging()
    logger.info("starting_autonomous_revenue_agent")

    agent = SurvivalLoop()

    # Handle shutdown signals
    def signal_handler(sig, frame):
        logger.info("shutdown_signal_received", signal=sig)
        if agent:
            agent.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Run survival loop and dashboard concurrently
        await asyncio.gather(
            agent.start(),
            run_dashboard(),
            return_exceptions=True,
        )
    except Exception as e:
        logger.error("agent_fatal_error", error=str(e))
        sys.exit(1)
    finally:
        if agent:
            await agent.shutdown()

    logger.info("agent_exited")


if __name__ == "__main__":
    asyncio.run(main())

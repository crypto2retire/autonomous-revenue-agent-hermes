"""Entry point for the autonomous revenue agent."""

import asyncio
import signal
import sys

from src.survival import SurvivalLoop
from src.utils.logger import configure_logging, get_logger

logger = get_logger(__name__)


async def main():
    """Main entry point."""
    configure_logging()
    logger.info("starting_autonomous_revenue_agent")

    agent = SurvivalLoop()

    # Handle shutdown signals
    def signal_handler(sig, frame):
        logger.info("shutdown_signal_received", signal=sig)
        agent.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        await agent.start()
    except Exception as e:
        logger.error("agent_fatal_error", error=str(e))
        sys.exit(1)
    finally:
        await agent.shutdown()

    logger.info("agent_exited")


if __name__ == "__main__":
    asyncio.run(main())

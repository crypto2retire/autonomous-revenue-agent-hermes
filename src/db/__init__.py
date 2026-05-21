"""Database layer for persistent agent state.

All agent data — trades, transactions, opportunities, wallet snapshots,
logs, and performance metrics — is stored in PostgreSQL so it survives
restarts and is available across dashboard sessions.
"""

from src.db.models import Base
from src.db.repository import AgentRepository

__all__ = ["Base", "AgentRepository"]

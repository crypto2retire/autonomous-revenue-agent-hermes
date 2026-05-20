"""FastAPI dashboard for agent management.

Provides endpoints for:
- Wallet management (view, update, switch)
- Agent status and controls
- Opportunity viewing
- Trade history
"""

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional

from src.wallet import WalletManager
from src.utils.logger import get_logger

logger = get_logger(__name__)

app = FastAPI(title="Autonomous Revenue Agent Dashboard")

# CORS for dashboard frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global wallet manager instance
wallet_manager = WalletManager()


class WalletUpdateRequest(BaseModel):
    """Request to update wallet."""
    private_key: str = Field(..., description="New wallet private key")
    save: bool = Field(default=True, description="Persist to config file")


class WalletResponse(BaseModel):
    """Wallet info response."""
    configured: bool
    address: Optional[str]
    eth_balance: str
    message: Optional[str] = None


class StatusResponse(BaseModel):
    """Agent status response."""
    status: str
    wallet_configured: bool
    wallet_address: Optional[str]
    mode: str


# Dependencies
def get_wallet_manager():
    return wallet_manager


@app.get("/")
async def root():
    return {"message": "Autonomous Revenue Agent Dashboard API"}


@app.get("/status", response_model=StatusResponse)
async def get_status():
    """Get current agent status."""
    from src.config import settings
    
    return StatusResponse(
        status="running",
        wallet_configured=wallet_manager.is_configured,
        wallet_address=wallet_manager.address,
        mode=settings.agent_mode,
    )


@app.get("/wallet", response_model=WalletResponse)
async def get_wallet():
    """Get current wallet info."""
    info = wallet_manager.to_dict()
    return WalletResponse(**info)


@app.post("/wallet/update", response_model=WalletResponse)
async def update_wallet(
    request: WalletUpdateRequest,
    manager: WalletManager = Depends(get_wallet_manager),
):
    """Update wallet with new private key.
    
    Allows changing wallet without restarting the agent.
    """
    result = manager.update_wallet(
        private_key=request.private_key,
        save_to_file=request.save,
    )
    
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    
    # Get updated balance
    info = manager.to_dict()
    info["message"] = result["message"]
    
    return WalletResponse(**info)


@app.post("/wallet/reload")
async def reload_wallet(
    manager: WalletManager = Depends(get_wallet_manager),
):
    """Reload wallet from config file."""
    manager.reload()
    
    return {
        "success": True,
        "wallet": manager.to_dict(),
    }


@app.get("/wallet/balance/{token_address}")
async def get_token_balance(token_address: str):
    """Get balance for specific token."""
    if not wallet_manager.is_configured:
        raise HTTPException(status_code=400, detail="No wallet configured")
    
    balance = wallet_manager.get_balance(token_address)
    
    return {
        "token_address": token_address,
        "balance": str(balance),
        "wallet": wallet_manager.address,
    }


# Health check for Fly.io
@app.get("/health")
async def health_check():
    return {"status": "healthy"}

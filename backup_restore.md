# Database Backup/Restore System

## How It Works

### On Startup (database.py)
- `restore_db()` checks if `/data/agent.db` exists (persistent Fly volume)
- If yes and `/app/agent.db` doesn't exist, copies backup to app directory
- Prints: `Restored DB from /data/agent.db to /app/agent.db`

### Every 5 Minutes (main.py)
- `run_backup()` coroutine runs in background
- Calls `DB.backup()` which copies `/app/agent.db` to `/data/agent.db`
- Prints: `Backed up DB to /data/agent.db`

### On Deploy/Restart
- Old machine: DB is backed up to `/data/agent.db` (persistent volume)
- New machine: `restore_db()` copies `/data/agent.db` to `/app/agent.db`
- Data persists across deploys!

## Verification

### Check current DB
```bash
fly ssh console -a crypto-agent-serene-surf-3922 -C "python3 -c 'import sqlite3; c=sqlite3.connect(\"/app/agent.db\"); print(c.execute(\"SELECT COUNT(*) FROM coin_watch\").fetchone())'"
```

### Check backup
```bash
fly ssh console -a crypto-agent-serene-surf-3922 -C "python3 -c 'import sqlite3; c=sqlite3.connect(\"/data/agent.db\"); print(c.execute(\"SELECT COUNT(*) FROM coin_watch\").fetchone())'"
```

### Check logs
```bash
fly logs -a crypto-agent-serene-surf-3922 | grep -E "(Restored|Backed up)"
```

## Files Changed
- `database.py` — added `restore_db()`, `backup_db()`, `DB.backup()`
- `main.py` — added `run_backup()` background task
- `entrypoint.sh` — ensures `/data` directory exists

## Current Status
- App: https://crypto-agent-serene-surf-3922.fly.dev
- Health: OK
- DB: Local SQLite at `/app/agent.db` with backup to `/data/agent.db`
- Backup interval: Every 5 minutes
- Volume: `agent_data` mounted at `/data` (1GB, encrypted)

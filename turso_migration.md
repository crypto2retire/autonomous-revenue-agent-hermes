# Turso Migration Plan

## Why Turso
- Free tier: 100 databases, 5GB storage, 500M rows read/month
- $4.99/month for unlimited databases + 9GB
- SQLite-compatible (minimal code changes)
- Async SQLAlchemy support via `aiolibsql` dialect
- Cloud-native, persists across deploys/restarts

## Steps

### 1. Install dependency
```bash
pip install sqlalchemy-libsql
```
Add to `requirements.txt`:
```
sqlalchemy-libsql
```

### 2. Update config.py
Add optional Turso credentials:
```python
turso_database_url: Optional[str] = Field(None, description="Turso database URL")
turso_auth_token: Optional[SecretStr] = Field(None, description="Turso auth token")
```

### 3. Update database.py engine creation
Replace SQLite engine block with:
```python
if database_url.startswith("sqlite+aiolibsql://"):
    # Turso async engine
    from sqlalchemy.pool import AsyncAdaptedQueuePool
    engine = create_async_engine(
        database_url,
        poolclass=AsyncAdaptedQueuePool,
        connect_args={
            "auth_token": settings.turso_auth_token.get_secret_value() if settings.turso_auth_token else None,
        },
    )
elif database_url.startswith("sqlite:///"):
    # Local SQLite fallback
    database_url = database_url.replace("sqlite:///", "sqlite+aiosqlite:///")
    engine = create_async_engine(database_url, echo=False, pool_pre_ping=True)
```

### 4. Set environment variables
```
DATABASE_URL=sqlite+aiolibsql:///agent.db
TURSO_DATABASE_URL=libsql://your-db.turso.io
TURSO_AUTH_TOKEN=your-token
```

### 5. Deploy
- Sign up at turso.tech
- Create database: `turso db create agent-db`
- Get URL: `turso db show --url agent-db`
- Get token: `turso db tokens create agent-db`
- Set Fly.io secrets
- Deploy

## Migration from existing data
- Export current SQLite: `sqlite3 app.db ".dump" > backup.sql`
- Import to Turso: `turso db shell agent-db < backup.sql`

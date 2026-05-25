# Fresh Solana Pump.fun Trading Bot Rebuild Plan

> Date: 2026-05-25
> Decision: Stop patching the current bot. Preserve it only as a reference and rebuild a small, observable, testable bot from scratch.

## Executive decision

The current project should be retired as the production/live-trading base.

Reason: repeated fixes are revealing architectural instability, not isolated bugs. The app keeps failing in different layers:

- DB schema drift after refactors
- dashboard health/status not reflecting real runtime behavior
- stale/frozen pricing paths
- DexScreener/API rate-limit noise
- unsafe or ambiguous paper/live state
- pump.fun scanner and execution paths patched in after the fact
- no real regression test suite protecting fixes

Continuing to patch this code is likely to cost more time than rebuilding a smaller bot with hard boundaries and tests.

## Non-negotiable requirements for the fresh build

1. Solana only.
2. Pump.fun / PumpSwap only at first.
3. Paper trading first; live trading must be added only after paper mode proves stable.
4. No database schema drift. Use explicit migrations from day one.
5. No dashboard lies. Every displayed status must come from one clear runtime source.
6. No hidden live-trading behavior. Live trading requires explicit environment + explicit UI/database setting.
7. No unbounded API polling. Every external API gets rate limits, backoff, and cached fallback.
8. No silent failures. All worker errors become structured events with severity, component, and remediation hint.
9. No “AI decides to trade” black box. Start with deterministic rules and logged scoring inputs.
10. Tests must exist before live trading exists.

## Recommended architecture

Use a small service split:

```text
fresh-solana-pumpbot/
  app/
    main.py                 # FastAPI app + worker startup
    config.py               # Pydantic settings
    db.py                   # SQLAlchemy engine/session only
    models.py               # DB models only
    migrations/             # Alembic migrations
    schemas.py              # API response/request models

    providers/
      dexscreener.py        # PumpSwap discovery + token pair data, rate-limited
      birdeye.py            # Optional paid price source
      jupiter.py            # Quotes/swap tx only
      solana_rpc.py         # Wallet balance + tx send/confirm only

    trading/
      scanner.py            # Finds candidates
      scorer.py             # Deterministic scoring
      paper_executor.py     # Simulated fills
      live_executor.py      # Real Jupiter/Solana execution, disabled by default
      position_manager.py   # Stop loss / profit targets
      risk.py               # Sizing, max exposure, kill switches

    workers/
      scheduler.py          # Owns scan/price/position loops
      locks.py              # Prevent overlapping cycles

    api/
      routes_status.py
      routes_tokens.py
      routes_trades.py
      routes_settings.py

    ui/
      dashboard.html        # Dumb dashboard; reads APIs only

  tests/
    test_scoring.py
    test_live_guard.py
    test_rate_limits.py
    test_position_math.py
    test_api_smoke.py
    test_migrations.py
```

## Minimal database model

Keep the DB boring and explicit.

Tables:

1. `tokens`
   - mint_address primary key
   - symbol
   - name
   - source
   - discovered_at
   - first_price_usd
   - last_price_usd
   - liquidity_usd
   - market_cap_usd
   - volume_24h_usd
   - price_change_5m_pct
   - price_change_1h_pct
   - risk_flags_json
   - last_seen_at

2. `scores`
   - id
   - mint_address
   - score
   - signal: avoid/watch/buy
   - reasons_json
   - inputs_json
   - created_at

3. `trades`
   - id
   - mode: paper/live
   - status: proposed/executed/failed/closed
   - mint_address
   - symbol
   - side: buy/sell
   - amount_usd
   - token_amount
   - entry_price_usd
   - exit_price_usd
   - tx_signature nullable
   - failure_reason nullable
   - opened_at
   - closed_at

4. `positions`
   - id
   - mode: paper/live
   - mint_address
   - token_amount
   - entry_price_usd
   - current_price_usd
   - cost_basis_usd
   - current_value_usd
   - realized_pnl_usd
   - unrealized_pnl_usd
   - stop_loss_price_usd
   - target_1_price_usd
   - target_2_price_usd
   - status: open/closed

5. `runtime_events`
   - id
   - level: debug/info/warning/error/critical
   - component
   - event
   - message
   - metadata_json
   - created_at

6. `settings`
   - key
   - value_json
   - updated_at

## Build phases

### Phase 0: Archive current project safely

Objective: Stop treating the old repo as the source of truth.

Steps:
1. Tag current branch as an abandoned rescue attempt:
   `git tag archive/unstable-rescue-2026-05-25`
2. Push the tag:
   `git push origin archive/unstable-rescue-2026-05-25`
3. Keep current repo for reference only.
4. Do not deploy it as the live trading bot.

Verification:
- Tag exists on remote.
- No production deployment is pointed at unreviewed experimental branch without explicit choice.

### Phase 1: Create fresh repo skeleton

Objective: Create a clean FastAPI + worker + tests project.

Steps:
1. Create new directory:
   `/Users/cleartheclutter/fresh-solana-pumpbot`
2. Initialize git.
3. Add pyproject.toml with pinned dependencies:
   - fastapi
   - uvicorn
   - sqlalchemy
   - alembic
   - asyncpg
   - aiosqlite
   - pydantic-settings
   - httpx
   - solders
   - solana
   - pytest
   - pytest-asyncio
   - respx
4. Add app package structure.
5. Add `/health` endpoint.
6. Add first test: health endpoint returns 200.

Verification:
- `pytest -q` passes.
- `python -m compileall app tests` passes.

### Phase 2: Add migrations before models grow

Objective: Prevent the exact schema drift that broke the current bot.

Steps:
1. Configure Alembic.
2. Create initial migration for all tables.
3. Add migration test that creates an old empty DB and upgrades it.
4. Add migration test that verifies required columns exist.

Verification:
- `alembic upgrade head` succeeds on a clean DB.
- `pytest tests/test_migrations.py -q` passes.

### Phase 3: Build provider clients with fake tests first

Objective: External APIs cannot crash the bot or spam errors.

Provider rules:
- Every provider has timeout.
- Every provider has rate limiter.
- Every provider handles 429 with backoff.
- Every provider returns typed success/failure result, not raw exceptions.

Steps:
1. Build DexScreener client.
2. Add tests for:
   - valid response parsing
   - empty response
   - 429 backoff
   - timeout handling
   - malformed JSON
3. Build optional Birdeye client only if API key exists.
4. Build Jupiter quote client, no swap sending yet.
5. Build Solana RPC balance client.

Verification:
- Provider tests pass without touching real APIs.
- One manual smoke command can call real APIs and print result.

### Phase 4: Build deterministic scanner and scorer

Objective: Get truthful watchlist data before trading.

Scoring inputs:
- liquidity_usd
- volume_24h_usd
- market_cap_usd
- price_change_5m_pct if available
- price_change_1h_pct if available
- pair age if available
- risk flags

Initial rule:
- price missing -> avoid
- liquidity under $5,000 -> avoid
- market cap over $10M -> avoid
- no volume -> avoid
- score >= 0.75 -> buy candidate
- score 0.45-0.74 -> watch
- score below 0.45 -> avoid

Important: Do not make a real buy in this phase.

Verification:
- Tests prove low-quality tokens are avoid.
- Tests prove good fake token becomes buy candidate.
- Scanner cycle persists tokens and scores.

### Phase 5: Build paper trading only

Objective: Prove execution math and position lifecycle with zero live risk.

Steps:
1. Paper executor consumes buy candidates.
2. Creates trade and position using actual token price, not USD amount as entry price.
3. Position manager refreshes prices.
4. Stop loss closes at -15%.
5. Target 1 sells 60% at +25%.
6. Target 2 sells 80% total at +50% or closes according to rule.

Verification:
- Unit tests for PNL math.
- Unit tests for partial sell math.
- Unit tests for stop loss.
- Paper mode end-to-end test: candidate -> paper buy -> price update -> position update.

### Phase 6: Build truthful dashboard

Objective: Dashboard only reports what the backend can prove.

Dashboard sections:
1. Runtime status
   - scanner last successful cycle
   - scanner last error
   - provider backoff state
   - current mode: paper/live effective mode
2. Watchlist
   - token data
   - score
   - reasons
   - last seen
3. Positions
   - entry price
   - current price
   - PNL
   - target/stop state
4. Trades
   - proposed/executed/failed/closed
   - failure reason
5. Logs
   - filter by component and severity

Verification:
- API smoke test hits every endpoint.
- Dashboard has no hidden inline calculations that disagree with backend.

### Phase 7: Add live trading guard, but no live execution yet

Objective: Make live mode impossible to accidentally enable.

Rules:
- `AGENT_MODE=live` required.
- DB setting `live_trading_enabled=true` required.
- wallet key present required.
- max trade size configured required.
- live readiness endpoint must pass all checks.
- dashboard must show effective mode, not requested mode.

Verification:
- Test: AGENT_MODE=paper + toggle true = paper effective mode.
- Test: AGENT_MODE=live + toggle false = paper/no-live effective mode.
- Test: AGENT_MODE=live + toggle true + missing wallet = blocked.
- Test: all requirements true = live-ready, but still no execution until Phase 8.

### Phase 8: Add live execution behind kill switch

Objective: Make exactly one tiny live trade possible and observable.

Steps:
1. Build Jupiter swap transaction creation.
2. Build signing and send path.
3. Add dry-run quote endpoint.
4. Add max trade size hard cap.
5. Add daily loss hard cap.
6. Add emergency kill switch.
7. Add transaction confirmation tracking.
8. Add live execution test with mocked Solana/Jupiter.

Verification before real money:
- All tests pass.
- Paper mode has run clean for at least 24 hours.
- Logs show no recurring errors.
- Dashboard shows fresh prices and positions.
- One manual dry-run quote works.

### Phase 9: Deployment

Objective: Deploy only after the bot is boring locally.

Steps:
1. Deploy to Render/Fly as paper mode only.
2. Use managed Postgres or SQLite with explicit migration command.
3. Add startup command that runs migrations before service starts.
4. Add health endpoint check.
5. Add structured logs.

Verification:
- Production health endpoint returns 200.
- Production migration logs show success.
- Paper scanner runs without recurring errors for 24 hours.

## Stop conditions

Stop and do not proceed to live trading if any of these happen:

- recurring provider errors every scan cycle
- dashboard cannot explain current mode clearly
- position price is 0 or stale for open positions
- migration fails or schema differs from model
- paper PNL math is wrong
- scanner emits buy signals without recorded score inputs
- live readiness endpoint says blocked
- user cannot explain from dashboard why a trade was proposed

## What not to copy from the current repo

Do not copy:
- DB schema as-is
- dashboard.py inline monolith
- old multi-chain naming like eth_balance/base/odos
- implicit create_all schema management
- direct provider calls scattered across scanner/executor/position manager
- broad `except Exception` without structured failure result
- live/paper behavior that depends on confusing inverse booleans

Can copy cautiously:
- basic scoring idea after rewriting tests
- wallet address configuration concept
- Jupiter/Solana dependency choices
- target/stop-loss strategy
- some dashboard visual layout, but not backend logic

## Recommended first implementation milestone

The first useful milestone is NOT live trading.

Milestone 1 should be:

- fresh repo boots
- DB migrations work
- DexScreener client handles 429 cleanly
- scanner stores tokens/scores
- dashboard shows watchlist and logs
- no trading code exists yet
- tests pass

That milestone proves the foundation is stable before any money logic is added.

## My recommendation

Start fresh. Do not keep chasing the current project.

The current repo should be treated as a failed prototype that taught us requirements:
- schema migrations matter
- provider backoff matters
- live trading guards matter
- dashboard truth matters
- tests must exist before deployment

The fresh build should be smaller, slower, and boring. That is what you want for anything touching a wallet.

# Bundle Detector (MVP)

Implements MVP steps:
1. Helius websocket monitor for pump.fun + Raydium launch events.
2. Layer 1 binary bundle detection (platform + fee account + identical Jito tip).
3. Telegram bot skeleton with strict report output format.
4. Supabase database layer with auto table creation.
5. Layer 2 historical co-occurrence algorithm via GMGN holdings/activity.
6. Learning feedback loop for serial bundler tagging.

## Run

```bash
bash run.sh

# or run individually
python main.py monitor
python main.py bot
```

## Env vars
Copy `.env.example` to `.env` and fill in real values before running:

```bash
cp .env.example .env
```

- `HELIUS_WEBSOCKET`
- `HELIUS_RPC_URL`
- `HELIUS_PARSE_TX`
- `TELEGRAM_BOT_TOKEN`

- `GMGN_EMAIL`
- `GMGN_PASSWORD`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_KEY`

## GMGN integration
- `api/gmgn.py` includes a Playwright-based session manager that logs in headlessly, extracts a Bearer token, caches it with TTL, and auto-refreshes on expiry/401.
- `GMGNClient` provides:
  - `wallet_daily_profits(wallet_address)`
  - `wallet_holdings(wallet_address)`
  - `wallet_activity(wallet_address)`

Each method returns raw JSON from GMGN.

## Layer 2
- `detection/layer2.py` computes token co-occurrence across a Layer 1 wallet cluster.
- Adaptive token threshold: `ceil(30% of cluster size)`.
- Entry/exit similarity checks use a ±10 minute window.
- Internal labels: `CONFIRMED BUNDLE` for high confidence (3+ tokens with similar entry/exit) and `POSSIBLE BUNDLE` otherwise.

## Database + learning
- `database/models.py` adds `SupabaseDatabase` using `SUPABASE_SERVICE_KEY`, auto-creates tables (`wallets`, `clusters`, `tokens`, `cooccurrence`) on first write, and persists Layer 1/Layer 2 results.
- `learning/feedback.py` adds `LearningSystem`, which increments wallet bundling counts and marks wallets as known bundlers after 3+ cluster appearances.
- Layer 2 wiring calls the learning system so known bundlers can be flagged immediately on subsequent launches.


The script `run.sh` creates/uses `.venv`, installs dependencies, installs Playwright browsers, loads environment variables from `.env`, and starts both monitor and bot simultaneously (logs: `monitor.log`, `bot.log`).

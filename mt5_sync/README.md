# Edge Analysis — MT5 auto-sync

Every trade you close in MetaTrader 5 appears in your Notion journal by itself —
prices, P&L, session, R multiple, MAE/MFE, hold time. You only fill in the
thinking (entry model, mental state, mistakes). Windows PC with the MT5
terminal required.

## Setup

**Downloaded from the app?** There is no setup: `config.ini` already contains
your journal and its key. Go straight to **Run it**. (Treat the folder like a
saved password — the key inside is yours.)

**Got this some other way?** Two minutes of manual setup:
1. https://www.notion.so/my-integrations → **New integration** → name it
   `MT5 Sync` → copy the **Internal Integration Secret**
2. In Notion, open your Trade Journal page → **⋯ → Connections → MT5 Sync**
3. Copy `config.example.ini` to `config.ini`, paste the token, and set
   `database_id` (the 32-character code in your journal's web address)

**Run it**
Double-click **run_sync.bat** (installs what it needs the first time).
Keep the window open while you trade — it checks every few minutes.
First run brings in your last 90 days; already-journaled trades are never
duplicated, so you can stop and start it freely.

## Troubleshooting
- "Couldn't attach to MetaTrader 5" → open the MT5 terminal first.
- "Notion refused the database query" → redo Step 2 (the connection), and
  check the token has no spaces around it.
- A trade shows no R Multiple → it had no stop-loss in MT5, so risk is
  unknowable. Set an SL and the maths comes back.

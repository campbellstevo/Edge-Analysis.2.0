# Edge Analysis — MT5 auto-sync

Every trade you close in MetaTrader 5 appears in your Notion journal by itself —
prices, P&L, session, R multiple, MAE/MFE, hold time. You only fill in the
thinking (entry model, mental state, mistakes). Windows PC with the MT5
terminal required.

## One-time setup (about 5 minutes)

**Step 1 — Get your Notion token**
1. Open https://www.notion.so/my-integrations → **New integration**
2. Name it `MT5 Sync`, pick your workspace → **Submit**
3. Copy the **Internal Integration Secret** (starts with `ntn_`)

**Step 2 — Let it see your journal**
1. In Notion, open your **Trade Journal** database page
2. **⋯ menu (top right) → Connections → MT5 Sync**

**Step 3 — Fill in the config**
1. In this folder, copy `config.example.ini` → rename the copy `config.ini`
   (skip the copy if the app gave you a `config.ini` already)
2. Open it in Notepad and paste your token from Step 1
3. `database_id`: already filled in if you downloaded this from the app.
   Otherwise: open your journal in the browser — the id is the 32-character
   code in the address, before any `?`

**Step 4 — Run it**
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

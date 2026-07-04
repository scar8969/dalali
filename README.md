# Sales Order Portal

A small Flask portal for calculating sales orders with **HKD / CNY to INR** conversion and a **3% markup**. Local-first: runs on your machine with a local SQLite file by default, no Supabase account needed.

## Features

- Add an order with **multiple line items** (product, quantity, unit price)
- Pick currency `HKD` or `CNY`
- Live preview as you type (uses cached exchange rate API)
- Total = `sum(price x quantity) x live rate to INR x 1.03`
- Save to local SQLite (`data/orders.db`)
- Dashboard with search, totals, and status chips
- Order status: `draft` -> `sent` / `cancelled`
- Optional **Supabase** backend (`STORAGE=supabase`)

## Quick start (local)

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

Open <http://127.0.0.1:5000>.

No `.env` needed. The app creates `data/orders.db` on first run.

## Configuration (`.env`)

```bash
SECRET_KEY=any-long-random-string
STORAGE=sqlite            # or "supabase"
DATABASE_PATH=data/orders.db
RATE_API_URL=https://api.exchangerate-api.com/v4/latest
# only when STORAGE=supabase:
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_ANON_KEY=xxxxx   # or SUPABASE_PUBLISHABLE_KEY / SUPABASE_SERVICE_ROLE_KEY
```

For Supabase mode, run `supabase_schema.sql` in the Supabase SQL editor first.

## Currency API

Defaults to `https://api.exchangerate-api.com/v4/latest/{HKD|CNY}`. Rate is cached in memory for 10 minutes per process.

If the rate API is down, click **Preview** to retry, or set `RATE_API_URL` to another provider (e.g. `https://api.frankfurter.app/latest`).

## Project layout

```
dalal/
  api/index.py        Flask app, storage layer, currency logic
  run.py              Local dev entry point
  templates/          Jinja templates
  static/             CSS
  data/orders.db      Auto-created SQLite file
  tests/              pytest unit tests
  requirements.txt
  supabase_schema.sql Optional, only when STORAGE=supabase
```

## Tests

```bash
pip install pytest
pytest -q
```

# Sales Order Portal

Open sales order calculator hosted on Vercel with Supabase for data storage. There is no login and no password.

## Workflow

1. Open the portal.
2. Add product name, quantity, currency (`HKD` or `CNY`), and unit price.
3. The app fetches the live INR exchange rate.
4. The app calculates `unit price x quantity x INR rate x 1.03`.
5. The order is saved in Supabase.

## Environment Variables

Create these in `.env` locally and in Vercel project settings:

```bash
SUPABASE_URL=your-supabase-project-url
SUPABASE_PUBLISHABLE_KEY=your-publishable-key
SECRET_KEY=use-a-long-random-secret
```

`SECRET_KEY` is only used for form protection. It is not a login password.

## Supabase Setup

1. Create a free Supabase project.
2. Open the SQL editor.
3. Run the contents of `supabase_schema.sql`.

## Fix Vercel Internal Server Error

If Vercel shows `SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY must be configured`, add both values in Vercel:

1. Open your Vercel project.
2. Go to Settings > Environment Variables.
3. Add `SUPABASE_URL` from Supabase Project Settings > API.
4. Add `SUPABASE_PUBLISHABLE_KEY` from Supabase Project Settings > API.
5. Redeploy the project.

## Local Development

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python api/index.py
```

Open `http://127.0.0.1:5000`.

## Deploy To Vercel

```bash
vercel
```

The `vercel.json` file routes requests to `api/index.py`.

## Currency Conversion

Rates are fetched from `https://api.exchangerate-api.com/v4/latest/HKD` or `https://api.exchangerate-api.com/v4/latest/CNY` and cached for five minutes per serverless instance.

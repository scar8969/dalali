# Sales Order Portal

Single-user sales order calculator hosted on Vercel with Supabase for data storage.

## Workflow

1. Login with your admin username and password.
2. Add product name, quantity, currency (`HKD` or `CNY`), and unit price.
3. The app fetches the live INR exchange rate.
4. The app calculates `unit price x quantity x INR rate x 1.03`.
5. The order is saved in Supabase and visible from anywhere after login.

## Environment Variables

Create these in `.env` locally and in Vercel project settings:

```bash
SUPABASE_URL=your-supabase-project-url
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
SECRET_KEY=use-a-long-random-secret
ADMIN_USERNAME=admin
ADMIN_PASSWORD=change-this-password
```

`ADMIN_USERNAME` and `ADMIN_PASSWORD` create your login automatically if it does not exist.

## Supabase Setup

1. Create a free Supabase project.
2. Open the SQL editor.
3. Run the contents of `supabase_schema.sql`.

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

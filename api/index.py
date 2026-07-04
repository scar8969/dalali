"""Sales Order Portal - local first, SQLite by default, Supabase optional.

Configuration via environment variables (or .env):

  STORAGE = "sqlite" (default) or "supabase"
  SECRET_KEY = random string for form protection
  DATABASE_PATH = path to sqlite file (default: data/orders.db)
  RATE_API_URL = optional override for currency API
  SUPABASE_URL, SUPABASE_KEY (only when STORAGE=supabase)
"""
import os
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

import requests
from dotenv import load_dotenv
from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
)
app.secret_key = os.environ.get("SECRET_KEY", "dev-change-this-secret")

MARKUP_RATE = Decimal("1.03")
RATE_CACHE_SECONDS = 600
SUPPORTED_CURRENCIES = {"HKD", "CNY"}
RATE_API_URL = os.environ.get("RATE_API_URL", "https://api.exchangerate-api.com/v4/latest")
STORAGE = os.environ.get("STORAGE", "sqlite").lower()
DB_PATH = Path(os.environ.get("DATABASE_PATH", str(DATA_DIR / "orders.db")))

_rate_cache = {}
_rate_lock = threading.Lock()

_supabase = None
_supabase_lock = threading.Lock()


# ---------- helpers ----------

def money(value):
    if value is None or value == "":
        return "-"
    amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{amount:,.2f}"


app.jinja_env.filters["money"] = money


def quantize_rate(rate):
    return Decimal(str(rate)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def require_csrf():
    token = request.form.get("csrf_token")
    if not token or token != session.get("csrf_token"):
        abort(400)


app.context_processor(lambda: {"csrf_token": csrf_token})


# ---------- storage layer ----------

def get_supabase():
    global _supabase
    if _supabase is not None:
        return _supabase
    with _supabase_lock:
        if _supabase is None:
            from supabase import create_client
            url = os.environ.get("SUPABASE_URL")
            key = (
                os.environ.get("SUPABASE_ANON_KEY")
                or os.environ.get("SUPABASE_PUBLISHABLE_KEY")
                or os.environ.get("SUPABASE_KEY")
                or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
            )
            if not url or not key:
                raise RuntimeError("Supabase storage selected but SUPABASE_URL / key not set.")
            _supabase = create_client(url, key)
    return _supabase


@contextmanager
def sqlite_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_sqlite():
    with sqlite_conn() as conn:
        conn.execute(
            """
            create table if not exists orders (
                id integer primary key autoincrement,
                reference text not null,
                notes text,
                currency text not null check (currency in ('HKD','CNY')),
                unit_price numeric(14, 2) not null,
                exchange_rate numeric(14, 4) not null,
                unit_price_inr numeric(14, 2) not null,
                subtotal_inr numeric(14, 2) not null,
                final_inr numeric(14, 2) not null,
                status text not null default 'draft' check (status in ('draft','sent','cancelled')),
                created_at text not null default (datetime('now'))
            )
            """
        )
        conn.execute(
            """
            create table if not exists order_items (
                id integer primary key autoincrement,
                order_id integer not null references orders(id) on delete cascade,
                product_name text not null,
                quantity integer not null check (quantity > 0),
                unit_price_original numeric(14, 2) not null
            )
            """
        )
        conn.execute("create index if not exists idx_orders_created on orders(created_at desc)")
        conn.execute("create index if not exists idx_items_order on order_items(order_id)")


if STORAGE == "sqlite":
    init_sqlite()


# ---------- storage API ----------

def _row_to_order(row):
    return {
        "id": row["id"],
        "reference": row["reference"],
        "notes": row["notes"] or "",
        "currency": row["currency"],
        "unit_price": float(row["unit_price"]),
        "exchange_rate": float(row["exchange_rate"]),
        "unit_price_inr": float(row["unit_price_inr"]),
        "subtotal_inr": float(row["subtotal_inr"]),
        "final_inr": float(row["final_inr"]),
        "status": row["status"],
        "created_at": row["created_at"],
    }


def _row_to_item(row):
    return {
        "id": row["id"],
        "order_id": row["order_id"],
        "product_name": row["product_name"],
        "quantity": row["quantity"],
        "unit_price_original": float(row["unit_price_original"]),
    }


def list_orders():
    if STORAGE == "sqlite":
        with sqlite_conn() as conn:
            orders = [dict(r) for r in conn.execute(
                "select * from orders order by created_at desc, id desc"
            ).fetchall()]
            items = [dict(r) for r in conn.execute(
                """
                select i.* from order_items i
                join orders o on o.id = i.order_id
                order by i.order_id, i.id
                """
            ).fetchall()]
        for order in orders:
            order["items"] = [it for it in items if it["order_id"] == order["id"]]
        return [_row_to_order(o) | {"items": [_row_to_item(i) for i in o["items"]]} for o in orders]
    # supabase
    sb = get_supabase()
    orders = sb.table("orders").select("*").order("created_at", desc=True).execute().data
    for order in orders:
        items = sb.table("order_items").select("*").eq("order_id", order["id"]).execute().data
        order["items"] = items
    return orders


def get_order(order_id):
    if STORAGE == "sqlite":
        with sqlite_conn() as conn:
            order = conn.execute("select * from orders where id = ?", (order_id,)).fetchone()
            if not order:
                return None
            items = [dict(r) for r in conn.execute(
                "select * from order_items where order_id = ? order by id", (order_id,)
            ).fetchall()]
        return _row_to_order(order) | {"items": [_row_to_item(i) for i in items]}
    sb = get_supabase()
    order = sb.table("orders").select("*").eq("id", order_id).limit(1).execute().data
    if not order:
        return None
    order = order[0]
    order["items"] = sb.table("order_items").select("*").eq("order_id", order_id).execute().data
    return order


def create_order(payload):
    if STORAGE == "sqlite":
        with sqlite_conn() as conn:
            cur = conn.execute(
                """
                insert into orders
                (reference, notes, currency, unit_price, exchange_rate,
                 unit_price_inr, subtotal_inr, final_inr, status)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["reference"],
                    payload.get("notes", ""),
                    payload["currency"],
                    payload["unit_price"],
                    payload["exchange_rate"],
                    payload["unit_price_inr"],
                    payload["subtotal_inr"],
                    payload["final_inr"],
                    payload.get("status", "draft"),
                ),
            )
            order_id = cur.lastrowid
            for item in payload["items"]:
                conn.execute(
                    """
                    insert into order_items (order_id, product_name, quantity, unit_price_original)
                    values (?, ?, ?, ?)
                    """,
                    (order_id, item["product_name"], item["quantity"], item["unit_price_original"]),
                )
        return order_id
    sb = get_supabase()
    order_id = sb.table("orders").insert({
        "reference": payload["reference"],
        "notes": payload.get("notes", ""),
        "currency": payload["currency"],
        "unit_price": payload["unit_price"],
        "exchange_rate": payload["exchange_rate"],
        "unit_price_inr": payload["unit_price_inr"],
        "subtotal_inr": payload["subtotal_inr"],
        "final_inr": payload["final_inr"],
        "status": payload.get("status", "draft"),
    }).execute().data[0]["id"]
    for item in payload["items"]:
        sb.table("order_items").insert({
            "order_id": order_id,
            "product_name": item["product_name"],
            "quantity": item["quantity"],
            "unit_price_original": item["unit_price_original"],
        }).execute()
    return order_id


def update_status(order_id, status):
    if STORAGE == "sqlite":
        with sqlite_conn() as conn:
            conn.execute("update orders set status = ? where id = ?", (status, order_id))
        return
    sb = get_supabase()
    sb.table("orders").update({"status": status}).eq("id", order_id).execute()


def delete_order(order_id):
    if STORAGE == "sqlite":
        with sqlite_conn() as conn:
            conn.execute("delete from order_items where order_id = ?", (order_id,))
            conn.execute("delete from orders where id = ?", (order_id,))
        return
    sb = get_supabase()
    sb.table("order_items").delete().eq("order_id", order_id).execute()
    sb.table("orders").delete().eq("id", order_id).execute()


# ---------- currency ----------

def get_inr_rate(currency):
    currency = currency.upper()
    if currency not in SUPPORTED_CURRENCIES:
        raise ValueError("Only HKD and CNY are supported.")
    now = time.time()
    with _rate_lock:
        cached = _rate_cache.get(currency)
        if cached and now - cached["timestamp"] < RATE_CACHE_SECONDS:
            return cached["rate"]
    response = requests.get(f"{RATE_API_URL}/{currency}", timeout=4)
    response.raise_for_status()
    payload = response.json()
    rate = Decimal(str(payload["rates"]["INR"]))
    with _rate_lock:
        _rate_cache[currency] = {"rate": rate, "timestamp": now}
    return rate


# ---------- parsing ----------

def parse_decimal(name, raw):
    raw = (raw or "").strip()
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        raise ValueError(f"Enter a valid {name.replace('_', ' ')}.")
    if value <= 0:
        raise ValueError(f"{name.replace('_', ' ').title()} must be greater than zero.")
    return value


def parse_int(name, raw):
    raw = (raw or "").strip()
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name.replace('_', ' ').title()} must be a whole number.")
    if value <= 0:
        raise ValueError(f"{name.replace('_', ' ').title()} must be greater than zero.")
    return value


def parse_items(form):
    names = form.getlist("item_product[]")
    qtys = form.getlist("item_quantity[]")
    prices = form.getlist("item_unit_price[]")
    items = []
    for idx, (name, qty_raw, price_raw) in enumerate(zip(names, qtys, prices), start=1):
        name = (name or "").strip()
        if not name and not qty_raw and not price_raw:
            continue
        if not name:
            raise ValueError(f"Item #{idx}: product name is required.")
        quantity = parse_int("quantity", qty_raw)
        price = parse_decimal("unit price", price_raw)
        items.append({
            "product_name": name,
            "quantity": quantity,
            "unit_price_original": float(price),
        })
    if not items:
        raise ValueError("Add at least one item.")
    return items


# ---------- routes ----------

@app.route("/")
def home():
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
def dashboard():
    orders = list_orders()
    total = sum(float(o["final_inr"]) for o in orders)
    total_items = sum(len(o["items"]) for o in orders)
    return render_template("dashboard.html", orders=orders, total_inr=total, total_items=total_items, storage=STORAGE)


@app.route("/orders/new", methods=["GET", "POST"])
def new_order():
    if request.method == "POST":
        require_csrf()
        reference = (request.form.get("reference") or "").strip()
        notes = (request.form.get("notes") or "").strip()
        currency = (request.form.get("currency") or "").upper()
        if not reference:
            flash("Reference is required.", "error")
            return render_template("order_form.html", form=request.form, preview=None, storage=STORAGE)
        try:
            items = parse_items(request.form)
            total_entered = sum(
                Decimal(str(it["unit_price_original"])) * Decimal(it["quantity"])
                for it in items
            )
            total_qty = sum(Decimal(it["quantity"]) for it in items)
            rate = get_inr_rate(currency)
        except (ValueError, requests.RequestException) as exc:
            flash(str(exc), "error")
            return render_template("order_form.html", form=request.form, preview=None, storage=STORAGE)

        subtotal_inr = total_entered * rate
        final_inr = subtotal_inr * MARKUP_RATE
        unit_price_inr_avg = (subtotal_inr / total_qty) if total_qty else Decimal("0")

        payload = {
            "reference": reference,
            "notes": notes,
            "currency": currency,
            "unit_price": float(total_entered),
            "exchange_rate": float(quantize_rate(rate)),
            "unit_price_inr": float(unit_price_inr_avg.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "subtotal_inr": float(subtotal_inr.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "final_inr": float(final_inr.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "items": items,
        }

        if request.form.get("action") == "preview":
            return render_template("order_form.html", form=request.form, preview=payload, storage=STORAGE)

        order_id = create_order(payload)
        flash(f"Order #{order_id} saved.", "success")
        return redirect(url_for("dashboard"))

    return render_template("order_form.html", form={}, preview=None, storage=STORAGE)


@app.route("/orders/<int:order_id>")
def order_detail(order_id):
    order = get_order(order_id)
    if not order:
        abort(404)
    return render_template("order_detail.html", order=order, storage=STORAGE)


@app.route("/orders/<int:order_id>/status", methods=["POST"])
def change_status(order_id):
    require_csrf()
    status = request.form.get("status")
    if status not in {"draft", "sent", "cancelled"}:
        abort(400)
    if not get_order(order_id):
        abort(404)
    update_status(order_id, status)
    flash("Status updated.", "success")
    return redirect(url_for("order_detail", order_id=order_id))


@app.route("/orders/<int:order_id>/delete", methods=["POST"])
def delete_order(order_id):
    require_csrf()
    if not get_order(order_id):
        abort(404)
    delete_order(order_id)
    flash("Order deleted.", "success")
    return redirect(url_for("dashboard"))


@app.route("/api/rates")
def api_rates():
    currency = (request.args.get("from") or "HKD").upper()
    try:
        rate = get_inr_rate(currency)
    except (ValueError, requests.RequestException) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"from": currency, "to": "INR", "rate": float(rate)})


@app.route("/health")
def health():
    return jsonify({"ok": True, "storage": STORAGE})


@app.errorhandler(404)
def not_found(_):
    return render_template("error.html", code=404, message="Not found."), 404


@app.errorhandler(400)
def bad_request(_):
    return render_template("error.html", code=400, message="Bad request."), 400


@app.errorhandler(500)
def server_error(_):
    return render_template("error.html", code=500, message="Something went wrong."), 500


if __name__ == "__main__":
    app.run(debug=True)

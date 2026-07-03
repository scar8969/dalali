import os
import secrets
import time
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
from supabase import create_client
from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
)
app.secret_key = os.environ.get("SECRET_KEY", "dev-change-this-secret")

MARKUP_RATE = Decimal("1.03")
RATE_CACHE_SECONDS = 300
SUPPORTED_CURRENCIES = {"HKD", "CNY"}

_supabase = None
_rate_cache = {}
_bootstrapped = False


def money(value):
    if value is None or value == "":
        return "-"
    amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{amount:,.2f}"


app.jinja_env.filters["money"] = money


def db():
    global _supabase
    if _supabase is None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be configured.")
        _supabase = create_client(url, key)
    return _supabase


def current_user():
    if "user_id" not in session:
        return None
    return {"id": session["user_id"], "username": session.get("username")}


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


def login_required():
    if not current_user():
        return redirect(url_for("login", next=request.path))
    return None


@app.context_processor
def inject_context():
    return {"current_user": current_user(), "csrf_token": csrf_token}


def ensure_admin_user():
    username = os.environ.get("ADMIN_USERNAME")
    password = os.environ.get("ADMIN_PASSWORD")
    if not username or not password:
        return

    existing = db().table("users").select("id").eq("username", username).limit(1).execute().data
    if existing:
        return

    db().table("users").insert(
        {"username": username, "password_hash": generate_password_hash(password)}
    ).execute()


@app.before_request
def bootstrap_once():
    global _bootstrapped
    if _bootstrapped or request.endpoint == "health":
        return
    ensure_admin_user()
    _bootstrapped = True


def parse_decimal(name):
    raw = request.form.get(name, "").strip()
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        raise ValueError(f"Enter a valid {name.replace('_', ' ')}.")
    if value <= 0:
        raise ValueError(f"{name.replace('_', ' ').title()} must be greater than zero.")
    return value


def parse_quantity():
    raw = request.form.get("quantity", "").strip()
    try:
        quantity = int(raw)
    except ValueError:
        raise ValueError("Quantity must be a whole number.")
    if quantity <= 0:
        raise ValueError("Quantity must be greater than zero.")
    return quantity


def get_inr_rate(currency):
    currency = currency.upper()
    if currency not in SUPPORTED_CURRENCIES:
        raise ValueError("Only HKD and CNY are supported.")

    cached = _rate_cache.get(currency)
    now = time.time()
    if cached and now - cached["timestamp"] < RATE_CACHE_SECONDS:
        return cached["rate"]

    response = requests.get(
        f"https://api.exchangerate-api.com/v4/latest/{currency}",
        timeout=4,
    )
    response.raise_for_status()
    payload = response.json()
    rate = Decimal(str(payload["rates"]["INR"]))
    _rate_cache[currency] = {"rate": rate, "timestamp": now}
    return rate


def calculate_final_price(unit_price, quantity, currency):
    rate = get_inr_rate(currency)
    unit_price_inr = unit_price * rate
    subtotal_inr = unit_price_inr * Decimal(quantity)
    final_price_inr = subtotal_inr * MARKUP_RATE
    return {
        "exchange_rate_to_inr": rate.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
        "unit_price_inr": unit_price_inr.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        "final_price_inr": final_price_inr.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
    }


def get_order(order_id):
    result = db().table("orders").select("*").eq("id", order_id).limit(1).execute().data
    return result[0] if result else None


@app.route("/")
def home():
    if current_user():
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        require_csrf()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = db().table("users").select("*").eq("username", username).limit(1).execute().data

        if user and check_password_hash(user[0]["password_hash"], password):
            session.clear()
            session["user_id"] = user[0]["id"]
            session["username"] = user[0]["username"]
            session["csrf_token"] = secrets.token_urlsafe(32)
            return redirect(request.args.get("next") or url_for("dashboard"))

        flash("Invalid username or password.", "error")

    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    require_csrf()
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
def dashboard():
    auth_redirect = login_required()
    if auth_redirect:
        return auth_redirect
    orders = db().table("orders").select("*").order("created_at", desc=True).execute().data
    return render_template("dashboard.html", orders=orders)


@app.route("/orders/new", methods=["GET", "POST"])
def new_order():
    auth_redirect = login_required()
    if auth_redirect:
        return auth_redirect

    preview = None
    form = {}
    if request.method == "POST":
        require_csrf()
        product_name = request.form.get("product_name", "").strip()
        currency = request.form.get("currency", "").upper()
        form = {
            "product_name": product_name,
            "quantity": request.form.get("quantity", ""),
            "currency": currency,
            "unit_price": request.form.get("unit_price", ""),
        }

        try:
            quantity = parse_quantity()
            unit_price = parse_decimal("unit_price")
            if not product_name:
                raise ValueError("Product name is required.")
            calculation = calculate_final_price(unit_price, quantity, currency)
        except (ValueError, requests.RequestException, KeyError) as exc:
            flash(f"Could not calculate price: {exc}", "error")
            return render_template("order_form.html", preview=None, form=form)

        preview = {
            "product_name": product_name,
            "quantity": quantity,
            "currency": currency,
            "unit_price": unit_price,
            **calculation,
        }

        if request.form.get("action") == "preview":
            return render_template("order_form.html", preview=preview, form=form)

        db().table("orders").insert(
            {
                "product_name": product_name,
                "quantity": quantity,
                "currency_used": currency,
                "unit_price_original": float(unit_price),
                "exchange_rate_to_inr": float(calculation["exchange_rate_to_inr"]),
                "unit_price_inr": float(calculation["unit_price_inr"]),
                "final_price_inr": float(calculation["final_price_inr"]),
                "created_by": current_user()["id"],
            }
        ).execute()

        flash("Order saved.", "success")
        return redirect(url_for("dashboard"))

    return render_template("order_form.html", preview=preview, form=form)


@app.route("/orders/<int:order_id>")
def order_detail(order_id):
    auth_redirect = login_required()
    if auth_redirect:
        return auth_redirect
    order = get_order(order_id)
    if not order:
        abort(404)
    return render_template("order_detail.html", order=order)


@app.route("/orders/<int:order_id>/delete", methods=["POST"])
def delete_order(order_id):
    auth_redirect = login_required()
    if auth_redirect:
        return auth_redirect
    require_csrf()
    db().table("orders").delete().eq("id", order_id).execute()
    flash("Order deleted.", "success")
    return redirect(url_for("dashboard"))


@app.route("/api/rates")
def api_rates():
    auth_redirect = login_required()
    if auth_redirect:
        return auth_redirect
    currency = request.args.get("from", "HKD").upper()
    try:
        rate = get_inr_rate(currency)
    except (ValueError, requests.RequestException, KeyError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"from": currency, "to": "INR", "rate": float(rate)})


@app.route("/health")
def health():
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=True)

"""Tests for parsing, math, and HTTP routes (uses Flask test client with sqlite)."""
import os
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ["DATABASE_PATH"] = str(ROOT / "data" / "test_orders.db")
os.environ["SECRET_KEY"] = "test-secret"

import pytest  # noqa: E402

from api import index as app_module  # noqa: E402
from api.index import app, parse_decimal, parse_int, parse_items  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_db(tmp_path, monkeypatch):
    test_db = tmp_path / "test.db"
    monkeypatch.setattr(app_module, "DB_PATH", test_db)
    monkeypatch.setattr(app_module, "STORAGE", "sqlite")
    app_module._rate_cache.clear()
    app_module.init_sqlite()
    yield
    try:
        test_db.unlink()
    except FileNotFoundError:
        pass


@pytest.fixture()
def client():
    return app.test_client()


def test_parse_decimal_accepts_positive():
    assert parse_decimal("price", "12.5") == Decimal("12.5")


def test_parse_decimal_rejects_zero():
    with pytest.raises(ValueError):
        parse_decimal("price", "0")


def test_parse_decimal_rejects_garbage():
    with pytest.raises(ValueError):
        parse_decimal("price", "abc")


def test_parse_int_requires_whole():
    assert parse_int("quantity", "5") == 5
    with pytest.raises(ValueError):
        parse_int("quantity", "5.5")


def test_parse_items_skips_blank_rows():
    from werkzeug.datastructures import MultiDict
    form = MultiDict([
        ("item_product[]", "Cable"),
        ("item_quantity[]", "2"),
        ("item_unit_price[]", "10"),
        ("item_product[]", ""),
        ("item_quantity[]", ""),
        ("item_unit_price[]", ""),
    ])
    items = parse_items(form)
    assert len(items) == 1
    assert items[0]["product_name"] == "Cable"
    assert items[0]["quantity"] == 2


def test_parse_items_requires_one():
    from werkzeug.datastructures import MultiDict
    form = MultiDict([
        ("item_product[]", ""),
        ("item_quantity[]", ""),
        ("item_unit_price[]", ""),
    ])
    with pytest.raises(ValueError):
        parse_items(form)


def test_dashboard_renders_empty(client):
    res = client.get("/dashboard")
    assert res.status_code == 200
    assert b"No orders yet" in res.data


def test_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is True

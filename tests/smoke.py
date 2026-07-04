"""Quick smoke test for the rebuilt app (sqlite, stubbed rate)."""
import os
import re
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ["SECRET_KEY"] = "test"
os.environ["DATABASE_PATH"] = str(ROOT / "data" / "smoke.db")

from api import index as app_module
from api.index import app


def extract_csrf(html):
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    return m.group(1) if m else ""


def main():
    app_module.get_inr_rate = lambda c: Decimal("10.0")

    c = app.test_client()
    g = c.get("/orders/new")
    assert g.status_code == 200, g.status_code
    csrf = extract_csrf(g.get_data(as_text=True))
    assert csrf, "order form should render csrf token"

    # preview
    res = c.post(
        "/orders/new",
        data={
            "csrf_token": csrf,
            "reference": "PO-TEST-1",
            "notes": "demo",
            "currency": "HKD",
            "item_product[]": ["Widget", "Gadget"],
            "item_quantity[]": ["2", "3"],
            "item_unit_price[]": ["10", "5"],
            "action": "preview",
        },
        follow_redirects=False,
    )
    print("preview status:", res.status_code)
    if res.status_code != 200:
        print(res.get_data(as_text=True)[:300])
    assert res.status_code == 200, res.status_code
    body = res.get_data(as_text=True)
    assert "Widget" in body, "preview should show items"
    assert "INR" in body

    # save
    g2 = c.get("/orders/new")
    csrf2 = extract_csrf(g2.get_data(as_text=True))
    res2 = c.post(
        "/orders/new",
        data={
            "csrf_token": csrf2,
            "reference": "PO-TEST-2",
            "notes": "",
            "currency": "CNY",
            "item_product[]": ["Bolt"],
            "item_quantity[]": ["4"],
            "item_unit_price[]": ["12.5"],
            "action": "save",
        },
        follow_redirects=True,
    )
    assert res2.status_code == 200, res2.status_code
    body2 = res2.get_data(as_text=True)
    assert "PO-TEST-2" in body2, "saved order should appear in dashboard"

    # detail
    detail = c.get("/orders/1")
    assert detail.status_code == 200
    assert b"PO-TEST-1" in detail.data or b"PO-TEST-2" in detail.data

    print("SMOKE OK")

    # clean up smoke db
    try:
        (ROOT / "data" / "smoke.db").unlink()
    except FileNotFoundError:
        pass


if __name__ == "__main__":
    main()

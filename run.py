"""Run script for the Sales Order Portal.

Usage:
    python run.py
"""
from api.index import app


if __name__ == "__main__":
    port = int(__import__("os").environ.get("PORT", 5000))
    app.run(host="127.0.0.1", port=port, debug=True)

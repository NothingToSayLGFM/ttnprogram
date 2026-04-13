"""TTNFlow backend client for the desktop app (token-based, no JWT)."""
import json
import os
from pathlib import Path
import sys
import requests

API_BASE = os.environ.get("TTNFLOW_API", "https://ttnflow.com/api/v1")

BASE_DIR = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.json"


def get_credentials() -> tuple[str, str] | None:
    """Return (email, desktop_token) from config.json, or None if not set."""
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        email = data.get("email", "").strip()
        token = data.get("desktop_token", "").strip()
        if email and token:
            return email, token
    except Exception:
        pass
    return None


def check_balance() -> int | None:
    """Return scan_balance for the current user, or None on error/no credentials."""
    creds = get_credentials()
    if not creds:
        return None
    email, token = creds
    try:
        resp = requests.post(
            f"{API_BASE}/desktop/balance",
            json={"email": email, "token": token},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json().get("scan_balance")
    except requests.RequestException:
        pass
    return None


def deduct(count: int) -> int | None:
    """Deduct `count` scans from balance. Returns new balance or None on error."""
    creds = get_credentials()
    if not creds:
        return None
    email, token = creds
    try:
        resp = requests.post(
            f"{API_BASE}/desktop/deduct",
            json={"email": email, "token": token, "count": count},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json().get("scan_balance")
    except requests.RequestException:
        pass
    return None

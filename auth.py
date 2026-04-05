"""Auth module for TTNFlow backend integration."""
import json
import os
import time
import requests

API_BASE = os.environ.get("TTNFLOW_API", "http://localhost:8080/api/v1")
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")


def _load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def is_logged_in() -> bool:
    cfg = _load_config()
    return bool(cfg.get("refresh_token"))


def get_valid_access_token() -> str | None:
    """Return a valid access token, refreshing if needed."""
    cfg = _load_config()
    access = cfg.get("access_token", "")
    refresh = cfg.get("refresh_token", "")

    if not refresh:
        return None

    # Try to use the stored access token; if it fails we'll refresh below.
    # We refresh unconditionally (stateless — no expiry stored locally) to keep it simple.
    try:
        resp = requests.post(
            f"{API_BASE}/auth/refresh",
            json={"refresh_token": refresh},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            cfg["access_token"] = data["access_token"]
            cfg["refresh_token"] = data["refresh_token"]
            _save_config(cfg)
            return data["access_token"]
    except requests.RequestException:
        pass

    # Fall back to stored access token if refresh failed
    return access if access else None


def login(email: str, password: str) -> bool:
    """Log in, store tokens. Returns True on success."""
    try:
        resp = requests.post(
            f"{API_BASE}/auth/login",
            json={"email": email, "password": password},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            cfg = _load_config()
            cfg["access_token"] = data["access_token"]
            cfg["refresh_token"] = data["refresh_token"]
            _save_config(cfg)
            return True
    except requests.RequestException:
        pass
    return False


def logout() -> None:
    """Revoke refresh token and clear local storage."""
    cfg = _load_config()
    refresh = cfg.get("refresh_token")
    if refresh:
        token = get_valid_access_token()
        try:
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            requests.post(
                f"{API_BASE}/auth/logout",
                json={"refresh_token": refresh},
                headers=headers,
                timeout=5,
            )
        except requests.RequestException:
            pass
    cfg.pop("access_token", None)
    cfg.pop("refresh_token", None)
    _save_config(cfg)


def check_subscription() -> bool:
    """Returns True if user has an active subscription."""
    token = get_valid_access_token()
    if not token:
        return False
    try:
        resp = requests.get(
            f"{API_BASE}/me/subscription",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json().get("active", False)
    except requests.RequestException:
        pass
    return False


def get_np_api_key() -> str:
    """Fetch the user's Nova Poshta API key from the backend profile."""
    # First check local config (cached from previous login)
    cfg = _load_config()
    token = get_valid_access_token()
    if not token:
        return cfg.get("api_key", "")
    try:
        resp = requests.get(
            f"{API_BASE}/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if resp.status_code == 200:
            key = resp.json().get("np_api_key", "")
            # Cache locally for offline use
            cfg["api_key"] = key
            _save_config(cfg)
            return key
    except requests.RequestException:
        pass
    return cfg.get("api_key", "")

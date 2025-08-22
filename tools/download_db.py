import os
import pathlib
import requests
import streamlit as st

def _get(key, default=None):
    try:
        return st.secrets["gh"].get(key, default)
    except Exception:
        return os.getenv(f"GH_{key.upper()}", default)

OWNER = _get("owner")
REPO  = _get("repo")
TAG   = _get("tag")
ASSET = _get("asset", "olist.duckdb")
TOKEN = _get("token")

try:
    from app.config import DB_PATH 
except Exception:
    DB_PATH = "olist.duckdb"

API = "https://api.github.com"

def _auth_headers(extra=None):
    h = {"Authorization": f"Bearer {TOKEN}"}
    if extra:
        h.update(extra)
    return h

def _require_settings():
    missing = [k for k, v in [("owner", OWNER), ("repo", REPO), ("tag", TAG), ("token", TOKEN)] if not v]
    if missing:
        raise RuntimeError(
            f"Missing GitHub settings: {', '.join(missing)}. "
            f"Provide them in Streamlit secrets under [gh] or as env vars."
        )

def _get_release_by_tag():
    url = f"{API}/repos/{OWNER}/{REPO}/releases/tags/{TAG}"
    r = requests.get(url, headers=_auth_headers())
    r.raise_for_status()
    return r.json()

def _find_asset_id(release_json, asset_name):
    for a in release_json.get("assets", []):
        if a.get("name") == asset_name:
            return a.get("id")
    return None

def _download_asset(asset_id, dest):
    url = f"{API}/repos/{OWNER}/{REPO}/releases/assets/{asset_id}"
    headers = _auth_headers({"Accept": "application/octet-stream"})
    with requests.get(url, headers=headers, stream=True) as r:
        r.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

def ensure_db() -> pathlib.Path:
    """
    Ensure the DuckDB file is present locally, downloading it once from
    GitHub Releases (private repo) using the asset API.
    """
    _require_settings()
    dest = pathlib.Path(DB_PATH)
    if dest.exists() and dest.stat().st_size > 0:
        return dest

    st.info(f"↓ Downloading {ASSET} from {OWNER}/{REPO}@{TAG} ...")
    rel = _get_release_by_tag()
    asset_id = _find_asset_id(rel, ASSET)
    if not asset_id:
        raise RuntimeError(
            f"Asset '{ASSET}' not found in release {OWNER}/{REPO}@{TAG}."
        )
    _download_asset(asset_id, dest)
    return dest

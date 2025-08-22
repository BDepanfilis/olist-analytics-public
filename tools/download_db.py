from __future__ import annotations

import os
import pathlib
import sys
from typing import Optional

try:
    import streamlit as st  
except Exception: 
    st = None  

import requests


def _get_secret(section: str, key: str, default: Optional[str] = None) -> Optional[str]:
    """Try st.secrets[section][key], fall back to env var of the same UPPER name, then default."""
    env_key = key.upper()
    
    if st is not None:
        try:
            if section and section in st.secrets and key in st.secrets[section]:
                return str(st.secrets[section][key])
        except Exception:
            pass

    val = os.environ.get(env_key)
    if val:
        return val
    
    return default


def _log(msg: str) -> None:
    if st is not None:
        st.write(msg)
    else:
        print(msg)


def _release_api(owner: str, repo: str, tag: str) -> str:
    if tag.lower() == "latest":
        return f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    return f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}"


def _resolve_asset_url(owner: str, repo: str, tag: str, asset_name: str, token: Optional[str]) -> str:
    api = _release_api(owner, repo, tag)
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    r = requests.get(api, headers=headers, timeout=30)
    r.raise_for_status()
    data = r.json()
    assets = data.get("assets", []) or []
    for a in assets:
        if a.get("name") == asset_name:
            url = a.get("browser_download_url")
            if not url:
                break
            return url
    raise RuntimeError(
        f"Asset '{asset_name}' not found in release '{tag}' of {owner}/{repo}. "
        f"Available: {[a.get('name') for a in assets]}"
    )


def ensure_db() -> str:
    """
    Ensure the DuckDB file exists locally.
    If missing or empty, download from a GitHub Release asset.
    Returns the absolute path to the DB file.
    """
    db_path = _get_secret("db", "db_path", "olist.duckdb")
    db_path = os.environ.get("DB_PATH", db_path)  
    db_path = str(db_path)
    path = pathlib.Path(db_path).expanduser().resolve()

    if path.exists() and path.stat().st_size > 1024:
        _log(f"✓ Using local DB: {path}")
        return str(path)

    # Read GitHub settings
    owner = _get_secret("gh", "owner") or ""
    repo = _get_secret("gh", "repo") or ""
    tag = _get_secret("gh", "tag", "latest") or "latest"
    asset = _get_secret("gh", "asset", "olist.duckdb") or "olist.duckdb"
    token = _get_secret("gh", "token")  

    if not (owner and repo and token):
        raise RuntimeError(
            "Missing GitHub settings. Ensure secrets (or env) provide gh.owner, gh.repo, gh.token."
        )

    url = _resolve_asset_url(owner, repo, tag, asset, token)

    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    _log(f"↓ Downloading {asset} from {owner}/{repo}@{tag} …")
    path.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, headers=headers, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

    if path.stat().st_size <= 1024:
        raise RuntimeError(f"Downloaded file looks too small: {path} ({path.stat().st_size} bytes)")

    _log(f"✓ DB downloaded to: {path}")
    return str(path)


if __name__ == "__main__":
    try:
        p = ensure_db()
        print(p)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

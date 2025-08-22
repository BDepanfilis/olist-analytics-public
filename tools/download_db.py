from pathlib import Path
import os, requests
import streamlit as st
from app.config import DB_PATH

def _gh_headers(token:str|None):
    h = {"Accept": "application/vnd.github+json"}
    if token: h["Authorization"] = f"token {token}"
    return h

def _get_secrets():
    s = st.secrets.get("github", {})
    return {
        "owner": s.get("owner"),
        "repo": s.get("repo"),
        "tag":  s.get("tag", "latest"),
        "asset_name": s.get("asset_name", "olist.duckdb"),
        "token": s.get("token"),
    }

def _find_asset_id(meta: dict, asset_name: str) -> int | None:
    for a in meta.get("assets", []):
        if a.get("name") == asset_name:
            return a.get("id")
    return None

def ensure_db(path: Path = DB_PATH) -> Path:
    if path.exists() and path.stat().st_size > 0:
        return path

    cfg = _get_secrets()
    owner, repo, tag, token, asset_name = (
        cfg["owner"], cfg["repo"], cfg["tag"], cfg["token"], cfg["asset_name"]
    )
    if not all([owner, repo, tag, token, asset_name]):
        raise RuntimeError("Missing GitHub secrets. Check .streamlit/secrets.")

    # 1) release metadata
    if tag == "latest":
        url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    else:
        url = f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}"
    r = requests.get(url, headers=_gh_headers(token), timeout=60)
    r.raise_for_status()
    meta = r.json()

    asset_id = _find_asset_id(meta, asset_name)
    if not asset_id:
        raise RuntimeError(f"Asset '{asset_name}' not found in release '{tag}'")

    # 2) asset binary download
    dl = f"https://api.github.com/repos/{owner}/{repo}/releases/assets/{asset_id}"
    headers = _gh_headers(token)
    headers["Accept"] = "application/octet-stream"
    with requests.get(dl, headers=headers, stream=True, timeout=600) as res:
        res.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            for chunk in res.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

    return path

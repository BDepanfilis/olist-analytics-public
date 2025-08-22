import contextlib
import os
from pathlib import Path
import duckdb
import requests
import streamlit as st

# ---------- helpers: resolve DB path & download on first run ----------

def _resolve_db_path(default_path: str) -> Path:
    """
    Allow override via Streamlit secrets or env, else use config default.
    """
    p = st.secrets.get("DB_PATH") or os.environ.get("DB_PATH") or default_path
    return Path(p)

def _download_from_github_release(dst: Path) -> bool:
    """
    Download an asset from a GitHub Release in a *private* repo using a token in st.secrets.
    Required secrets:
      GH_OWNER, GH_REPO, GH_TAG (or 'latest'), GH_ASSET, GH_TOKEN
    """
    owner = st.secrets.get("GH_OWNER")
    repo  = st.secrets.get("GH_REPO")
    tag   = st.secrets.get("GH_TAG", "latest")
    asset = st.secrets.get("GH_ASSET")
    token = st.secrets.get("GH_TOKEN")

    if not all([owner, repo, tag, asset, token]):
        return False

    # Resolve the release (tag or latest) ➜ list assets ➜ pick GH_ASSET
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}",
                            "Accept": "application/vnd.github+json",
                            "X-GitHub-Api-Version": "2022-11-28"})

    if tag == "latest":
        rel_url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    else:
        rel_url = f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}"

    r = session.get(rel_url, timeout=60)
    r.raise_for_status()
    data = r.json()

    asset_id = None
    for a in data.get("assets", []):
        if a.get("name") == asset:
            asset_id = a.get("id")
            break
    if not asset_id:
        raise RuntimeError(f"GH release asset '{asset}' not found on tag '{tag}'.")

    # Download asset (note: need the special Accept header)
    dl_url = f"https://api.github.com/repos/{owner}/{repo}/releases/assets/{asset_id}"
    with session.get(dl_url, headers={"Accept": "application/octet-stream"}, stream=True, timeout=600) as resp:
        resp.raise_for_status()
        dst.parent.mkdir(parents=True, exist_ok=True)
        with open(dst, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
    return True

def _download_from_direct_url(dst: Path) -> bool:
    """
    Download from a direct URL if provided (e.g., pre-signed S3 link).
    Secret: DB_DOWNLOAD_URL
    """
    url = st.secrets.get("DB_DOWNLOAD_URL")
    if not url:
        return False
    with requests.get(url, stream=True, timeout=600) as resp:
        resp.raise_for_status()
        dst.parent.mkdir(parents=True, exist_ok=True)
        with open(dst, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
    return True

def _ensure_local_db(db_path: Path):
    """
    If the DuckDB file does not exist, try to fetch it using the configured method.
    Prefers GitHub Release (private repo) if secrets are present; otherwise tries a direct URL.
    """
    if db_path.exists():
        return
    with st.spinner("Downloading analytics database…"):
        ok = False
        try:
            ok = _download_from_github_release(db_path)
        except Exception as e:
            st.warning(f"GitHub download attempt failed: {e}")
        if not ok:
            try:
                ok = _download_from_direct_url(db_path)
            except Exception as e:
                st.warning(f"Direct download attempt failed: {e}")
        if not ok:
            raise FileNotFoundError(
                f"Could not locate '{db_path}' and no download method succeeded. "
                "Set GitHub or DB_DOWNLOAD_URL secrets."
            )

# ---------- public functions (same API as before) ----------

@contextlib.contextmanager
def connect_cached(db_path: str):
    """
    Cached DuckDB connection. Ensures the DB exists locally (download if needed),
    then opens a single cached connection for the app lifetime.
    """
    # Download-on-first-run if needed
    p = _resolve_db_path(db_path)
    _ensure_local_db(p)

    @st.cache_resource(show_spinner=False)
    def _connect(pth: str):
        con = duckdb.connect(pth, read_only=False)
        con.execute("SET timezone = 'UTC'")
        return con

    con = _connect(str(p))
    try:
        yield con
    finally:
        # Keep cached connection open for the app lifetime.
        pass

def has_table(con, schema: str, table: str) -> bool:
    q = "SELECT 1 FROM information_schema.tables WHERE table_schema=? AND table_name=?"
    return con.execute(q, [schema, table]).fetchone() is not None

@st.cache_data(show_spinner=False, ttl=300)
def run_sql_cached(sql: str, params=None):
    # keep behavior: format {schema} from config, connect to default DB path
    from . import config
    s = sql.format(schema=config.DEFAULT_SCHEMA)
    with connect_cached(config.DEFAULT_DUCKDB_PATH) as con:
        return con.execute(s, params or ()).fetchdf()

def run_sql(sql: str, params=None):
    from . import config
    s = sql.format(schema=config.DEFAULT_SCHEMA)
    with connect_cached(config.DEFAULT_DUCKDB_PATH) as con:
        return con.execute(s, params or ()).fetchdf()
